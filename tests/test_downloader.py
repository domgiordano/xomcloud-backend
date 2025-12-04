#!/usr/bin/env python3
"""
Local test script for the scdl async downloader.
Run with: python -m pytest tests/test_downloader.py
Or directly: python tests/test_downloader.py
"""

import asyncio
import sys
import os
import pytest
import boto3
import uuid as _uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lambdas.download_tracks.downloader_scdl import Track, download_tracks
from lambdas.common import get_logger

log = get_logger(__name__)


async def test_download():
    """Test downloading SoundCloud tracks."""
    # Example SoundCloud tracks - replace with real URLs
    tracks = [
        Track(
            id="1",
            url="https://soundcloud.com/example/track-1",
            title="Example Track 1",
            artist="Example Artist"
        ),
        Track(
            id="2",
            url="https://soundcloud.com/example/track-2",
            title="Example Track 2",
            artist="Example Artist"
        ),
    ]
    
    log.info(f"Testing download of {len(tracks)} tracks...")
    
    try:
        zip_path, results = await download_tracks(tracks)
        
        log.info(f"\n✅ Download complete!")
        log.info(f"📦 Zip file: {zip_path}")
        log.info(f"\nResults:")
        for result in results:
            status = "✅ Success" if result.success else "❌ Failed"
            log.info(f"  {status}: {result.track.title} - {result.track.artist}")
            if not result.success and result.error:
                log.warning(f"    Error: {result.error}")
            
    except Exception as e:
        log.error(f"❌ Error: {e}")
        raise


DEFAULT_TEST_URL = os.getenv(
    "SCDL_TEST_URL",
    "https://soundcloud.com/user-63968721/bass-cannon-costa-flip",
)


@pytest.mark.asyncio
async def test_single_track():
    """Test downloading a single track. Uses `SCDL_TEST_URL` env or default provided URL."""
    url = os.getenv("SCDL_TEST_URL", DEFAULT_TEST_URL)
    track = Track(
        id="test-1",
        url=url,
        title="Bass Cannon (Costa Flip)",
        artist="user-63968721",
    )
    
    log.info(f"Testing single track download...")
    log.info(f"URL: {track.url}")
    
    try:
        zip_path, results = await download_tracks([track])
        
        if results[0].success:
            log.info(f"✅ Downloaded successfully!")
            log.info(f"📦 Location: {zip_path}")
        else:
            log.warning(f"❌ Download failed: {results[0].error}")
            
    except Exception as e:
        log.error(f"❌ Error: {e}")
        raise


@pytest.mark.asyncio
async def test_many_tracks_25():
    """Download 25 tracks concurrently (same song repeated) and show results.

    WARNING: This will perform real network downloads. It uses the same
    `SCDL_TEST_URL` (or default) and requests 25 downloads concurrently.
    """
    url = os.getenv("SCDL_TEST_URL", DEFAULT_TEST_URL)
    count = int(os.getenv("SCDL_TEST_COUNT", "25"))

    log.info(f"Running {count} concurrent downloads for URL: {url}")

    tracks = [
        Track(id=str(i), url=url, title=f"Test Track {i}", artist="TestArtist")
        for i in range(count)
    ]

    try:
        zip_path, results = await download_tracks(tracks)

        log.info(f"Download complete. Zip: {zip_path}")
        success_count = sum(1 for r in results if r.success)
        log.info(f"Successful: {success_count}/{len(results)}")

        # Print brief per-track outcomes
        for r in results:
            status = "OK" if r.success else "FAIL"
            log.info(f"{status}: {r.track.title} -> {r.file_path or r.error}")

        # Basic assertions
        assert len(results) == count
        assert any(r.success for r in results), "Expected at least one successful download"

    except Exception as e:
        log.error(f"Error during many-track download: {e}")
        raise


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_SCDL_E2E") != "1", reason="E2E upload tests disabled by default")
async def test_e2e_single_upload():
    """E2E: download 1 track, upload zip to S3, and log presigned URL."""
    url = os.getenv("SCDL_TEST_URL", DEFAULT_TEST_URL)

    track = Track(id="e2e-1", url=url, title="E2E Test", artist="E2E")
    zip_path, results = await download_tracks([track])

    if not results or not results[0].success:
        pytest.skip("Download failed; skipping upload")

    s3 = boto3.client("s3")
    bucket = os.getenv("S3_DOWNLOAD_BUCKET_NAME", "xomcloud-downloads")
    key = f"downloads/{_uuid.uuid4().hex}/{os.path.basename(zip_path)}"

    log.info(f"Uploading {zip_path} to s3://{bucket}/{key}")
    s3.upload_file(zip_path, bucket, key, ExtraArgs={"ContentType": "application/zip"})

    presigned = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=3600,
    )

    log.info(f"Presigned URL: {presigned}")
    assert isinstance(presigned, str) and bucket in presigned


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_SCDL_E2E") != "1", reason="E2E upload tests disabled by default")
async def test_e2e_many_upload_25():
    """E2E: download 25 tracks concurrently (same URL), upload zip to S3, and log presigned URL."""
    url = os.getenv("SCDL_TEST_URL", DEFAULT_TEST_URL)
    count = int(os.getenv("SCDL_TEST_COUNT", "25"))

    tracks = [Track(id=str(i), url=url, title=f"E2E {i}", artist="E2E") for i in range(count)]
    zip_path, results = await download_tracks(tracks)

    success_count = sum(1 for r in results if r.success)
    log.info(f"Downloaded {success_count}/{len(results)} successfully. Zip: {zip_path}")

    if success_count == 0:
        pytest.skip("No successful downloads; skipping upload")

    s3 = boto3.client("s3")
    bucket = os.getenv("S3_DOWNLOAD_BUCKET_NAME", "xomcloud-downloads")
    key = f"downloads/{_uuid.uuid4().hex}/{os.path.basename(zip_path)}"

    log.info(f"Uploading {zip_path} to s3://{bucket}/{key}")
    s3.upload_file(zip_path, bucket, key, ExtraArgs={"ContentType": "application/zip"})

    presigned = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=3600,
    )

    log.info(f"Presigned URL: {presigned}")
    assert isinstance(presigned, str) and bucket in presigned


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("SoundCloud Downloader Test")
    log.info("=" * 60)
    log.info("\nNOTE: Update the track URLs in this script to test with real SoundCloud tracks")
    log.info("\nRunning test...\n")
    
    # Run the test
    # Use env var or default URL when running locally
    asyncio.run(test_single_track())
    
    log.info("\n" + "=" * 60)
    log.info("Test complete!")
    log.info("=" * 60)


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_SCDL_INTEGRATION") != "1", reason="Integration test: set RUN_SCDL_INTEGRATION=1 to enable")
async def test_download_many_integration():
    """Integration test to download many tracks concurrently (disabled by default).

    Enable with environment variable `RUN_SCDL_INTEGRATION=1` and optionally
    set `SCDL_TEST_COUNT` and `SCDL_TEST_URL`.
    """
    count = int(os.getenv("SCDL_TEST_COUNT", "50"))
    url = os.getenv("SCDL_TEST_URL")
    if not url:
        pytest.skip("SCDL_TEST_URL not set")

    tracks = [
        Track(id=str(i), url=url, title=f"Integration Track {i}", artist="IntegrationArtist")
        for i in range(count)
    ]

    zip_path, results = await download_tracks(tracks)

    # Basic assertions: we should have a result per requested track
    assert len(results) == count
    # At least one should succeed if network and URL valid
    assert any(r.success for r in results)
    # Clean up zip file if present
    if zip_path and os.path.exists(zip_path):
        os.remove(zip_path)
