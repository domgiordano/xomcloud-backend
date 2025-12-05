# lambdas/download_tracks/downloader.py
# Async SoundCloud downloader using scdl with proper file naming

import asyncio
import os
import tempfile
import zipfile
import uuid
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from lambdas.common import get_logger, DownloadError, soundcloud_client_id

log = get_logger(__name__)

# Thread pool for blocking operations (scdl is not truly async)
_executor = ThreadPoolExecutor(max_workers=4)


@dataclass
class Track:
    """Represents a track to download."""
    id: str
    url: str
    title: str
    artist: str
    
    @property
    def safe_filename(self) -> str:
        """Generate a safe filename: Artist - Title"""
        safe_artist = self._sanitize(self.artist)
        safe_title = self._sanitize(self.title)
        
        if safe_artist and safe_title:
            name = f"{safe_artist} - {safe_title}"
        elif safe_title:
            name = safe_title
        else:
            name = f"track_{self.id}"
        
        # Limit length
        return name[:150]
    
    @staticmethod
    def _sanitize(s: str) -> str:
        """Remove unsafe characters from filename."""
        if not s:
            return ""
        # Remove characters that are unsafe for filenames
        s = re.sub(r'[<>:"/\\|?*]', '', s)
        # Replace multiple spaces with single space
        s = re.sub(r'\s+', ' ', s)
        return s.strip()


@dataclass
class DownloadResult:
    """Result of a track download."""
    track: Track
    success: bool
    file_path: Optional[str] = None
    error: Optional[str] = None


def _download_track_sync(track: Track, output_dir: str, client_id: str) -> DownloadResult:
    """
    Synchronous download using scdl (runs in thread pool).
    """
    try:
        from scdl import download_url
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Build scdl arguments
        scdl_args = {
            "l": track.url,
            "path": Path(output_dir),
            "name_format": track.safe_filename,
            "client_id": client_id,
            # Disable most options
            "C": False,
            "a": False,
            "add_description": False,
            "addtimestamp": False,
            "addtofile": False,
            "auth_token": None,
            "c": False,
            "debug": False,
            "download_archive": None,
            "error": False,
            "extract_artist": False,
            "f": False,
            "flac": False,
            "force_metadata": False,
            "hide_progress": True,
            "hidewarnings": True,
            "max_size": None,
            "me": False,
            "min_size": None,
            "n": None,
            "no_album_tag": False,
            "no_original": False,
            "no_playlist": True,
            "no_playlist_folder": True,
            "o": None,
            "only_original": False,
            "onlymp3": True,  # Prefer MP3
            "opus": False,
            "original_art": False,
            "original_metadata": False,
            "original_name": False,
            "overwrite": True,
            "p": False,
            "playlist_name_format": "%(playlist)s - %(title)s",
            "r": False,
            "strict_playlist": False,
            "sync": None,
            "s": None,
            "t": False,
            "yt_dlp_args": "",
        }
        
        log.info(f"Downloading: {track.artist} - {track.title}")
        download_url(track.url, **scdl_args)
        
        # Find the downloaded file
        downloaded_file = _find_downloaded_file(output_dir, track)
        
        if downloaded_file:
            log.info(f"✓ Downloaded: {track.safe_filename}")
            return DownloadResult(track=track, success=True, file_path=downloaded_file)
        
        return DownloadResult(
            track=track, 
            success=False, 
            error="File not found after download"
        )
        
    except ImportError:
        log.error("scdl not installed")
        return DownloadResult(track=track, success=False, error="scdl not installed")
    except Exception as e:
        log.error(f"Failed to download {track.title}: {e}")
        return DownloadResult(track=track, success=False, error=str(e))


def _find_downloaded_file(output_dir: str, track: Track) -> Optional[str]:
    """Find the downloaded file in output directory."""
    audio_extensions = ('.mp3', '.m4a', '.wav', '.opus', '.flac', '.ogg')
    safe_name = track.safe_filename.lower()
    
    for fname in os.listdir(output_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in audio_extensions:
            continue
        
        path = os.path.join(output_dir, fname)
        fname_lower = fname.lower()
        
        # Check if filename matches our expected pattern
        if safe_name[:20].lower() in fname_lower:
            return path
        
        # Also check by track ID
        if track.id in fname:
            return path
    
    # If still not found, return the first audio file (last resort)
    for fname in os.listdir(output_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext in audio_extensions:
            return os.path.join(output_dir, fname)
    
    return None


async def download_track(track: Track, output_dir: str, client_id: str) -> DownloadResult:
    """Download a single track asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, 
        _download_track_sync, 
        track, 
        output_dir,
        client_id
    )


async def download_tracks(tracks: list[Track]) -> tuple[str, list[DownloadResult]]:
    """
    Download multiple tracks and create a zip file.
    Returns (zip_path, results).
    """
    if not tracks:
        raise DownloadError("No tracks provided")
    
    # Get SoundCloud client ID from SSM
    try:
        client_id = soundcloud_client_id()
    except Exception as e:
        log.warning(f"Could not get client_id from SSM: {e}")
        client_id = None
    
    # Create temp directory for this batch
    temp_dir = tempfile.mkdtemp(prefix="xomcloud_")
    log.info(f"Downloading {len(tracks)} tracks to {temp_dir}")
    
    # Download all tracks concurrently
    # Each track gets its own subdirectory to avoid naming conflicts
    tasks = []
    for i, track in enumerate(tracks):
        track_dir = os.path.join(temp_dir, f"track_{i}")
        os.makedirs(track_dir, exist_ok=True)
        tasks.append(download_track(track, track_dir, client_id))
    
    results = await asyncio.gather(*tasks)
    
    # Collect successful downloads
    successful = [r for r in results if r.success and r.file_path]
    
    if not successful:
        raise DownloadError("All downloads failed")
    
    # Create zip file with proper names
    zip_filename = f"xomcloud_{uuid.uuid4().hex[:8]}.zip"
    zip_path = os.path.join(temp_dir, zip_filename)
    
    log.info(f"Creating zip with {len(successful)} tracks")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in successful:
            # Use the track's safe filename for the zip entry
            original_ext = os.path.splitext(result.file_path)[1]
            arcname = f"{result.track.safe_filename}{original_ext}"
            
            zf.write(result.file_path, arcname)
            log.info(f"  Added: {arcname}")
    
    log.info(f"Created zip: {zip_path} ({len(successful)}/{len(tracks)} tracks)")
    return zip_path, results
