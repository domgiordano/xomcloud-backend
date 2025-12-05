import boto3
from botocore.config import Config
import os

S3_DOWNLOAD_BUCKET_NAME = os.environ.get("S3_DOWNLOAD_BUCKET_NAME", "xomcloud-downloads")
REGION = os.environ.get("AWS_REGION", "us-east-1")

_s3_client = None


def get_s3_client():
    """Get configured S3 client with signature v4 (required for KMS)."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=REGION,
            config=Config(signature_version='s3v4')
        )
    return _s3_client


def upload_file(file_path: str, key: str, content_type: str = "application/zip") -> str:
    """Upload a file to S3 and return the key."""
    s3 = get_s3_client()
    s3.upload_file(
        file_path,
        S3_DOWNLOAD_BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type}
    )
    return key


def upload_bytes(data: bytes, key: str, content_type: str = "application/zip") -> str:
    """Upload bytes to S3 and return the key."""
    s3 = get_s3_client()
    s3.put_object(
        Bucket=S3_DOWNLOAD_BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=content_type
    )
    return key


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned download URL (signature v4 for KMS support)."""
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_DOWNLOAD_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in
    )
