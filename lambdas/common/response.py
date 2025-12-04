import json
from typing import Any, Optional
from lambdas.common.errors import AppError

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json"
}


def success(data: Any = None, status: int = 200) -> dict:
    """Build a successful API response."""
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({"data": data}) if data is not None else json.dumps({"success": True})
    }


def error(err: AppError | Exception, status: int = 500) -> dict:
    """Build an error API response."""
    if isinstance(err, AppError):
        return {
            "statusCode": err.status,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "error": {
                    "code": err.code,
                    "message": err.message
                }
            })
        }
    
    # Generic exception fallback
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(err)
            }
        })
    }


def parse_body(event: dict) -> Optional[dict]:
    """Parse JSON body from API Gateway event."""
    body = event.get("body")
    if not body:
        return None
    if isinstance(body, dict):
        return body
    return json.loads(body)
