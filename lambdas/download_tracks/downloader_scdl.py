import asyncio
import os
import tempfile
import zipfile
import uuid
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from scdl import download_url
from mutagen import File as MutagenFile
import re

from lambdas.common import get_logger, DownloadError

log = get_logger(__name__)

# Thread pool for blocking operations
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
    """Synchronous download implemented via scdl.download_url (runs in thread pool).

    scdl.download_url writes files to the provided `path`. We call it synchronously
    in the executor and then try to find the downloaded file in `output_dir`.
    """
    try:
        # ensure output dir exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Use scdl to download the given URL into the output directory.
        # scdl expects many arguments present; to avoid KeyError inside scdl,
        # provide a complete set of defaults and override the important ones.
        scdl_args = {
            "C": False,
            "a": False,
            "add_description": False,
            "addtimestamp": False,
            "addtofile": False,
            "auth_token": None,
            "c": False,
            "client_id": None,
            "debug": False,
            "download_archive": None,
            "error": False,
            "extract_artist": False,
            "f": False,
            "flac": False,
            "force_metadata": False,
            "hide_progress": False,
            "hidewarnings": False,
            "l": track.url,
            "max_size": None,
            "me": False,
            "min_size": None,
            "n": None,
            "name_format": f"{track.filename}",
            "no_album_tag": False,
            "no_original": False,
            "no_playlist": False,
            "no_playlist_folder": False,
            "o": None,
            "only_original": False,
            "onlymp3": False,
            "opus": False,
            "original_art": False,
            "original_metadata": False,
            "original_name": False,
            "overwrite": False,
            "p": False,
            "path": Path(output_dir),
            "playlist_name_format": "%(playlist)s - %(title)s",
            "r": False,
            "strict_playlist": False,
            "sync": None,
            "s": None,
            "t": False,
            "yt_dlp_args": "",
        }

        download_url(track.url, **scdl_args)

        # Try to find the file created by scdl using metadata matching first
        candidate = _find_file_by_metadata(output_dir, track)
        if candidate:
            log.info(f"Downloaded (scdl, metadata): {track.title} -> {candidate}")
            return DownloadResult(track=track, success=True, file_path=candidate)

        # Fallback: filename prefix matching. Log candidates for debugging.
        candidates = []
        for f in os.listdir(output_dir):
            if f.startswith(track.filename) and os.path.splitext(f)[1].lower() in (
                ".mp3",
                ".m4a",
                ".wav",
                ".webm",
                ".opus",
            ):
                path = os.path.join(output_dir, f)
                candidates.append(path)
        if candidates:
            log.debug(f"Filename-fallback candidates for {track.filename}: {candidates}")
            # return first candidate
            path = candidates[0]
            log.info(f"Downloaded (scdl, filename): {track.title} -> {path}")
            return DownloadResult(track=track, success=True, file_path=path)

        return DownloadResult(track=track, success=False, error="File not found after scdl download")
    except Exception as e:
        log.error(f"Failed to download {track.title} via scdl: {e}")
        return DownloadResult(track=track, success=False, error=str(e))


def _normalize(s: str) -> str:
    """Normalize strings for comparison: lower, remove non-alphanum."""
    if not s:
        return ""
    return re.sub(r"[^0-9a-z]", "", s.lower())


def _find_file_by_metadata(output_dir: str, track: Track) -> Optional[str]:
    """Scan audio files in `output_dir` and try to match by metadata tags.

    Returns the matching file path or None.
    """
    want_title = _normalize(track.title)
    want_artist = _normalize(track.artist)

    candidates = []
    for fname in os.listdir(output_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in (".mp3", ".m4a", ".wav", ".webm", ".opus"):
            continue
        path = os.path.join(output_dir, fname)
        candidates.append(path)
        try:
            m = MutagenFile(path, easy=True)
            if not m:
                log.debug(f"No tags for candidate {fname}")
                continue
            # mutagen easy tags typically use 'title' and 'artist' keys
            tags_title = " ".join(m.get("title", [])).strip()
            tags_artist = " ".join(m.get("artist", [])).strip()

            log.debug(f"Candidate {fname}: title={tags_title!r}, artist={tags_artist!r}")

            if tags_title:
                if want_title and _normalize(tags_title) == want_title:
                    return path
            if tags_artist and want_artist and _normalize(tags_artist) == want_artist:
                return path
        except Exception as exc:
            # ignore files mutagen cannot parse but log for debugging
            log.debug(f"Mutagen failed to read {fname}: {exc}")
            continue
    if candidates:
        log.debug(f"_find_file_by_metadata candidates: {candidates}")
    return None


async def download_track(track: Track, output_dir: str) -> DownloadResult:
    """Download a single SoundCloud track asynchronously by delegating to the thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _download_track_sync, track, output_dir)
 


async def download_tracks(tracks: list[Track]) -> tuple[str, list[DownloadResult]]:
    """
    Download multiple SoundCloud tracks concurrently and create a zip file.
    Returns (zip_path, results).
    """
    if not tracks:
        raise DownloadError("No tracks provided")
    
    # Create temp directory for downloads
    temp_dir = tempfile.mkdtemp(prefix="xomcloud_scdl_")
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
