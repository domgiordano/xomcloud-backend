import asyncio
import os
import uuid

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


def validate_request(body: dict) -> list[Track]:
    """Validate and parse the download request."""
    if not body:
        raise ValidationError("Request body is required")
    
    tracks_data = body.get("tracks", [])
    if not tracks_data:
        raise ValidationError("At least one track is required")
    
    if len(tracks_data) > 50:
        raise ValidationError("Maximum 50 tracks per request")
    
    tracks = []
    for i, t in enumerate(tracks_data):
        if not isinstance(t, dict):
            raise ValidationError(f"Track {i} must be an object")
        
        required = ["id", "url", "title", "artist"]
        missing = [f for f in required if not t.get(f)]
        if missing:
            raise ValidationError(f"Track {i} missing fields: {', '.join(missing)}")
        
        tracks.append(Track(
            id=str(t["id"]),
            url=t["url"],
            title=t["title"],
            artist=t["artist"]
        ))
    
    return tracks


async def process_download(tracks: list[Track]) -> dict:
    """Process the download and return result."""
    zip_path, results = await download_tracks(tracks)
    
    # Upload to S3
    s3_key = f"downloads/{uuid.uuid4().hex}/{os.path.basename(zip_path)}"
    upload_file(zip_path, s3_key)
    
    # Generate presigned URL
    download_url = generate_presigned_url(s3_key, expires_in=3600)
    
    # Clean up temp file
    try:
        os.remove(zip_path)
    except:
        pass
    
    # Build response
    successful = sum(1 for r in results if r.success)
    failed = [{"id": r.track.id, "title": r.track.title, "error": r.error} 
              for r in results if not r.success]
    
    return {
        "download_url": download_url,
        "expires_in": 3600,
        "total": len(tracks),
        "successful": successful,
        "failed": failed
    }


def handler(event: dict, context) -> dict:
    """Lambda handler for track downloads."""
    try:
        log.info("Processing download request")
        
        body = parse_body(event)
        tracks = validate_request(body)
        
        log.info(f"Downloading {len(tracks)} tracks")
        
        # Run async download
        result = asyncio.run(process_download(tracks))
        
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
