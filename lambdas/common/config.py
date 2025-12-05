import boto3
import os
from functools import lru_cache

_ssm = None
PRODUCT = "xomcloud"


def _get_ssm():
    """Get SSM client (lazy initialization)."""
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


@lru_cache(maxsize=32)
def get_param(name: str, decrypt: bool = True) -> str:
    """Get a parameter from SSM Parameter Store (cached)."""
    response = _get_ssm().get_parameter(Name=name, WithDecryption=decrypt)
    return response["Parameter"]["Value"]


def aws_access_key() -> str:
    """Get AWS access key from SSM or environment."""
    return os.environ.get("AWS_ACCESS_KEY_ID") or get_param(f"/{PRODUCT}/aws/ACCESS_KEY")


def aws_secret_key() -> str:
    """Get AWS secret key from SSM or environment."""
    return os.environ.get("AWS_SECRET_ACCESS_KEY") or get_param(f"/{PRODUCT}/aws/SECRET_KEY")


def soundcloud_client_id() -> str:
    """Get SoundCloud client ID from SSM or environment."""
    return os.environ.get("SOUNDCLOUD_CLIENT_ID") or get_param(f"/{PRODUCT}/soundcloud/CLIENT_ID")


def soundcloud_client_secret() -> str:
    """Get SoundCloud client secret from SSM or environment."""
    return os.environ.get("SOUNDCLOUD_CLIENT_SECRET") or get_param(f"/{PRODUCT}/soundcloud/CLIENT_SECRET")


def api_secret_key() -> str:
    """Get API secret key from SSM or environment."""
    return os.environ.get("API_SECRET_KEY") or get_param(f"/{PRODUCT}/api/API_SECRET_KEY")
