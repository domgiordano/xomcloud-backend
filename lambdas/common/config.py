import boto3
from functools import lru_cache
from typing import Optional

_ssm = boto3.client("ssm")
PRODUCT = "xomcloud"


@lru_cache(maxsize=32)
def get_param(name: str, decrypt: bool = True) -> str:
    """Get a parameter from SSM Parameter Store (cached)."""
    response = _ssm.get_parameter(Name=name, WithDecryption=decrypt)
    return response["Parameter"]["Value"]


def aws_access_key() -> str:
    return get_param(f"/{PRODUCT}/aws/ACCESS_KEY")


def aws_secret_key() -> str:
    return get_param(f"/{PRODUCT}/aws/SECRET_KEY")


def soundcloud_client_id() -> str:
    return get_param(f"/{PRODUCT}/soundcloud/CLIENT_ID")


def soundcloud_client_secret() -> str:
    return get_param(f"/{PRODUCT}/soundcloud/CLIENT_SECRET")


def api_secret_key() -> str:
    return get_param(f"/{PRODUCT}/api/API_SECRET_KEY")
