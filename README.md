# XOMCLOUD Backend

AWS Lambda backend for XOMCLOUD - SoundCloud track downloader.

## Architecture

```
┌─────────────┐      ┌─────────────────┐      ┌──────────────┐
│   Angular   │ ──▶ │   API Gateway   │ ──▶ │    Lambda    │
│   Frontend  │      │   (authorizer)  │      │  (download)  │
└─────────────┘      └─────────────────┘      └──────┬───────┘
                                                      │
                                              ┌───────▼───────┐
                                              │     scdl      │
                                              │   + ffmpeg    │
                                              └───────┬───────┘
                                                      │
                                              ┌───────▼───────┐
                                              │   S3 Bucket   │
                                              │  (downloads)  │
                                              └───────┬───────┘
                                                      │
                                              ┌───────▼───────┐
                                              │  Presigned    │
                                              │     URL       │
                                              └───────────────┘
```

## Structure

```
lambdas/
├── common/              # Shared utilities
│   ├── __init__.py
│   ├── logger.py        # Logging
│   ├── errors.py        # Exception classes
│   ├── response.py      # API response builders
│   ├── config.py        # SSM parameter helpers
│   └── s3.py            # S3 upload/presigned URLs
├── authorizer/          # JWT authorizer Lambda
│   ├── __init__.py
│   └── handler.py
└── download_tracks/     # Track download Lambda
    ├── __init__.py
    ├── handler.py       # Lambda entry point
    └── downloader.py    # scdl-based download logic
```

## API

### POST /download

Download tracks as a zip file.

**Request:**
```json
{
  "tracks": [
    {
      "id": "123456",
      "url": "https://soundcloud.com/artist/track",
      "title": "Track Name",
      "artist": "Artist Name"
    }
  ]
}
```

**Response:**
```json
{
  "data": {
    "download_url": "https://s3.../xomcloud-tracks.zip?...",
    "expires_in": 3600,
    "total": 5,
    "successful": 4,
    "failed_count": 1,
    "failed": [
      {"id": "789", "title": "Failed Track", "artist": "Artist", "error": "..."}
    ],
    "tracks_downloaded": [
      {"id": "123", "title": "Track 1", "artist": "Artist 1"}
    ]
  }
}
```

## File Naming

Downloaded tracks are named: `{Artist} - {Title}.mp3`

Special characters are removed and filenames are limited to 150 characters.

## Setup

### 1. SSM Parameters (Required)

```bash
aws ssm put-parameter --name "/xomcloud/soundcloud/CLIENT_ID" --value "your-id" --type SecureString
aws ssm put-parameter --name "/xomcloud/soundcloud/CLIENT_SECRET" --value "your-secret" --type SecureString
aws ssm put-parameter --name "/xomcloud/api/API_SECRET_KEY" --value "your-jwt-secret" --type SecureString
```

### 2. S3 Bucket

```bash
aws s3 mb s3://xomcloud-downloads
```

### 3. ECR Repositories

```bash
aws ecr create-repository --repository-name xomcloud-authorizer
aws ecr create-repository --repository-name xomcloud-download-tracks
```

### 4. Lambda Functions

Create two Lambda functions:
- `xomcloud-authorizer` - uses `xomcloud-authorizer` ECR image
- `xomcloud-download-tracks` - uses `xomcloud-download-tracks` ECR image

**Important Lambda Settings:**
- Timeout: 15 minutes (download-tracks)
- Memory: 1024MB minimum
- Environment variable: `S3_DOWNLOAD_BUCKET_NAME=xomcloud-downloads`

### 5. API Gateway

Create HTTP API with:
- POST /download → Lambda integration (download-tracks)
- Lambda authorizer using xomcloud-authorizer
- CORS enabled

## Deployment

Push to `master` triggers GitHub Actions deployment.

### Manual Deploy

```bash
# Build and push download Lambda
docker build -f Dockerfile.download -t YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/xomcloud-download-tracks:latest .
docker push YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/xomcloud-download-tracks:latest

aws lambda update-function-code \
  --function-name xomcloud-download-tracks \
  --image-uri YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/xomcloud-download-tracks:latest

# Build and push authorizer Lambda
docker build -f Dockerfile.authorizer -t YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/xomcloud-authorizer:latest .
docker push YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/xomcloud-authorizer:latest

aws lambda update-function-code \
  --function-name xomcloud-authorizer \
  --image-uri YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/xomcloud-authorizer:latest
```

## Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run test
python -c "
import asyncio
from lambdas.download_tracks.downloader import Track, download_tracks

async def test():
    tracks = [
        Track(id='1', url='https://soundcloud.com/artist/track', title='Test', artist='Artist')
    ]
    zip_path, results = await download_tracks(tracks)
    print(f'Created: {zip_path}')
    for r in results:
        print(f'  {r.track.title}: {\"OK\" if r.success else r.error}')

asyncio.run(test())
"
```

## Timeout Considerations

- API Gateway has a 29-second timeout (hard limit)
- Lambda can run up to 15 minutes
- For large batches, consider:
  - Using Lambda Function URL (no timeout)
  - Async processing with SQS/SNS
  - Step Functions for orchestration

Current solution: Downloads 4 tracks concurrently, which typically completes within 29 seconds for ~10-15 tracks.
