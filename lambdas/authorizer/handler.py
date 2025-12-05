import jwt
from lambdas.common import get_logger, api_secret_key

log = get_logger(__name__)


def generate_policy(effect: str, resource: str, principal: str = "xomcloud") -> dict:
    """Generate an IAM policy for API Gateway."""
    return {
        "principalId": principal,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": effect,
                "Resource": resource
            }]
        }
    }


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token."""
    try:
        clean_token = token.replace("Bearer ", "").strip()
        return jwt.decode(clean_token, api_secret_key(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        log.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        log.warning(f"Invalid token: {e}")
        return None


def handler(event: dict, context) -> dict:
    """Lambda authorizer handler for XOMCLOUD API."""
    try:
        method_arn = event.get("methodArn", "")
        auth_token = event.get("authorizationToken", "")
        
        if not method_arn:
            log.warning("Missing method ARN")
            return generate_policy("Deny", "*")
        
        if not auth_token:
            log.warning("Missing authorization token")
            return generate_policy("Deny", method_arn)
        
        # Decode and validate JWT
        user = decode_token(auth_token)
        if user:
            log.info(f"Authorized user: {user.get('sub', 'unknown')}")
            return generate_policy("Allow", method_arn, principal=str(user.get('sub', 'xomcloud')))
        
        log.warning("Authorization denied - invalid token")
        return generate_policy("Deny", method_arn)

    except Exception as e:
        log.error(f"Error in authorizer: {e}")
        return generate_policy("Deny", event.get("methodArn", "*"))
