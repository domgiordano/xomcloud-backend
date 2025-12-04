import boto3
import os
from lambdas.common.config import aws_access_key, aws_secret_key

S3_DOWNLOAD_BUCKET_NAME = os.environ.get("S3_DOWNLOAD_BUCKET_NAME", "")
REGION = "us-east-1"


def get_s3_client():
    """Get configured S3 client."""
    return boto3.client(
        "s3",
        region_name=REGION,
        aws_access_key_id=aws_access_key(),
        aws_secret_access_key=aws_secret_key()
    )


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
    """Generate a presigned download URL."""
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_DOWNLOAD_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in
    )
