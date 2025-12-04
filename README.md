# Xomcloud Backend

AWS Lambda backend for Xomcloud - SoundCloud track downloader.

## Structure

```
lambdas/
├── common/           # Shared utilities
│   ├── logger.py     # Simple logging
│   ├── errors.py     # Exception classes
│   ├── response.py   # API response builders
│   ├── config.py     # SSM parameter helpers
│   └── s3.py         # S3 upload/download
├── authorizer/       # JWT authorizer
│   └── handler.py
└── download_tracks/  # Track download service
    ├── handler.py    # Lambda entry point
    └── downloader.py # Async download logic
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
    "download_url": "https://...",
    "expires_in": 3600,
    "total": 5,
    "successful": 4,
    "failed": [
      {"id": "789", "title": "Failed Track", "error": "..."}
    ]
  }
}
```

## SSM Parameters Required

```
/xomcloud/aws/ACCESS_KEY
/xomcloud/aws/SECRET_KEY
/xomcloud/soundcloud/CLIENT_ID
/xomcloud/soundcloud/CLIENT_SECRET
/xomcloud/api/API_SECRET_KEY
```

## S3 Bucket

Create bucket: `xomcloud-downloads`

## Deployment

Push to `master` triggers GitHub Actions deployment.

### Manual Deploy

```bash
# Package and deploy
zip -r authorizer.zip lambdas/authorizer/*
zip -r download_tracks.zip lambdas/download_tracks/*

aws lambda update-function-code \
  --function-name xomcloud-authorizer \
  --zip-file fileb://authorizer.zip

aws lambda update-function-code \
  --function-name xomcloud-download-tracks \
  --zip-file fileb://download_tracks.zip
```

## Local Testing

```python
from lambdas.download_tracks.handler import handler

event = {
    "body": {
        "tracks": [
            {
                "id": "123",
                "url": "https://soundcloud.com/artist/track",
                "title": "Test",
                "artist": "Artist"
            }
        ]
    }
}

result = handler(event, None)
print(result)
```
