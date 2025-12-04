import asyncio
import os
import tempfile
import zipfile
import uuid
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import yt_dlp

from lambdas.common import get_logger, DownloadError

log = get_logger(__name__)

# Thread pool for running yt-dlp (it's not truly async)
_executor = ThreadPoolExecutor(max_workers=4)


@dataclass
class Track:
    """Represents a track to download."""
    id: str
    url: str
    title: str
    artist: str
    
    @property
    def filename(self) -> str:
        """Generate a safe filename."""
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in self.title)
        safe_artist = "".join(c if c.isalnum() or c in " -_" else "" for c in self.artist)
        return f"{safe_artist} - {safe_title}".strip()[:100]


@dataclass
class DownloadResult:
    """Result of a track download."""
    track: Track
    success: bool
    file_path: Optional[str] = None
    error: Optional[str] = None


def _download_track_sync(track: Track, output_dir: str) -> DownloadResult:
    """Synchronous download function (runs in thread pool)."""
    output_template = os.path.join(output_dir, f"{track.filename}.%(ext)s")
    
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }],
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([track.url])
        
        # Find the downloaded file
        expected_path = os.path.join(output_dir, f"{track.filename}.mp3")
        if os.path.exists(expected_path):
            log.info(f"Downloaded: {track.title}")
            return DownloadResult(track=track, success=True, file_path=expected_path)
        
        # Try to find any mp3 that was created
        for f in os.listdir(output_dir):
            if f.endswith(".mp3") and track.filename[:20] in f:
                path = os.path.join(output_dir, f)
                log.info(f"Downloaded (alternate name): {track.title}")
                return DownloadResult(track=track, success=True, file_path=path)
        
        return DownloadResult(track=track, success=False, error="File not found after download")
        
    except Exception as e:
        log.error(f"Failed to download {track.title}: {e}")
        return DownloadResult(track=track, success=False, error=str(e))


async def download_track(track: Track, output_dir: str) -> DownloadResult:
    """Download a single track asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _download_track_sync, track, output_dir)


async def download_tracks(tracks: list[Track]) -> tuple[str, list[DownloadResult]]:
    """
    Download multiple tracks and create a zip file.
    Returns (zip_path, results).
    """
    if not tracks:
        raise DownloadError("No tracks provided")
    
    # Create temp directory for downloads
    temp_dir = tempfile.mkdtemp(prefix="xomcloud_")
    log.info(f"Downloading {len(tracks)} tracks to {temp_dir}")
    
    # Download all tracks concurrently
    tasks = [download_track(track, temp_dir) for track in tracks]
    results = await asyncio.gather(*tasks)
    
    # Create zip file
    successful = [r for r in results if r.success and r.file_path]
    if not successful:
        raise DownloadError("All downloads failed")
    
    zip_filename = f"xomcloud_{uuid.uuid4().hex[:8]}.zip"
    zip_path = os.path.join(temp_dir, zip_filename)
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in successful:
            arcname = os.path.basename(result.file_path)
            zf.write(result.file_path, arcname)
            log.info(f"Added to zip: {arcname}")
    
    log.info(f"Created zip with {len(successful)}/{len(tracks)} tracks")
    return zip_path, results
