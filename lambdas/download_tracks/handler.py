# lambdas/download_tracks/handler.py
# Improved handler with async support and better error handling

import asyncio
import os
import uuid
import json
from datetime import datetime

from lambdas.common import (
    get_logger,
    success,
    error,
    parse_body,
    ValidationError,
    DownloadError,
    upload_file,
    generate_presigned_url
)
from lambdas.download_tracks.downloader import Track, download_tracks

log = get_logger(__name__)

# Maximum tracks per request (limited for reliability with long tracks)
MAX_TRACKS = 5

# S3 presigned URL expiry (1 hour)
PRESIGNED_EXPIRY = 3600


def validate_request(body: dict) -> tuple[list[Track], str]:
    """Validate and parse the download request. Returns (tracks, username)."""
    if not body:
        raise ValidationError("Request body is required")
    
    tracks_data = body.get("tracks", [])
    if not tracks_data:
        raise ValidationError("At least one track is required")
    
    if len(tracks_data) > MAX_TRACKS:
        raise ValidationError(f"Maximum {MAX_TRACKS} tracks per request")
    
    tracks = []
    username = None
    
    for i, t in enumerate(tracks_data):
        if not isinstance(t, dict):
            raise ValidationError(f"Track {i} must be an object")
        
        # Required fields
        track_id = t.get("id")
        url = t.get("url") or t.get("permalink_url")
        title = t.get("title", f"Track {i + 1}")
        
        # Artist can come from different fields
        artist = (
            t.get("artist") or 
            (t.get("user", {}).get("username") if isinstance(t.get("user"), dict) else None) or
            "Unknown Artist"
        )
        
        # Capture username for folder naming (first artist)
        if not username and artist != "Unknown Artist":
            username = artist
        
        if not track_id:
            raise ValidationError(f"Track {i} missing 'id' field")
        
        if not url:
            # Build URL from track ID if not provided
            url = f"https://api.soundcloud.com/tracks/{track_id}"
        
        tracks.append(Track(
            id=str(track_id),
            url=url,
            title=title,
            artist=artist
        ))
    
    return tracks, username or "xomcloud"


async def process_download(tracks: list[Track], username: str) -> dict:
    """Process the download and return result with presigned URL."""
    log.info(f"Starting download of {len(tracks)} tracks")
    
    # Download tracks and create zip
    zip_path, results = await download_tracks(tracks)
    
    # Generate folder name: username_timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_username = "".join(c if c.isalnum() or c in "-_" else "_" for c in username)[:30]
    folder_name = f"{safe_username}_{timestamp}"
    
    s3_key = f"downloads/{folder_name}/xomcloud-tracks.zip"
    
    # Upload to S3
    log.info(f"Uploading zip to S3: {s3_key}")
    upload_file(zip_path, s3_key, content_type="application/zip")
    
    # Generate presigned URL for download
    download_url = generate_presigned_url(s3_key, expires_in=PRESIGNED_EXPIRY)
    
    # Clean up temp files
    try:
        os.remove(zip_path)
        temp_dir = os.path.dirname(zip_path)
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        log.warning(f"Failed to clean up temp files: {e}")
    
    # Build response with detailed results
    successful = [r for r in results if r.success]
    failed = [
        {
            "id": r.track.id,
            "title": r.track.title,
            "artist": r.track.artist,
            "error": r.error or "Unknown error"
        }
        for r in results if not r.success
    ]
    
    return {
        "download_url": download_url,
        "expires_in": PRESIGNED_EXPIRY,
        "total": len(tracks),
        "successful": len(successful),
        "failed_count": len(failed),
        "failed": failed if failed else None,
        "tracks_downloaded": [
            {"id": r.track.id, "title": r.track.title, "artist": r.track.artist}
            for r in successful
        ]
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for track downloads."""
    try:
        log.info("Processing download request")
        
        body = parse_body(event)
        tracks, username = validate_request(body)
        
        log.info(f"Validated {len(tracks)} tracks for download (user: {username})")
        
        # Run async download process
        result = asyncio.run(process_download(tracks, username))
        
        log.info(f"Download complete: {result['successful']}/{result['total']} tracks")
        return success(result)
        
    except ValidationError as e:
        log.warning(f"Validation error: {e}")
        return error(e)
    except DownloadError as e:
        log.error(f"Download error: {e}")
        return error(e)
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        return error(e)
