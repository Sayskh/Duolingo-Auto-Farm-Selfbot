import base64
import json
import time
from typing import Any

def decode_jwt_payload(token: str) -> dict[str, Any]:
    """
    Decodes the payload section of a JWT token without requiring external dependencies.
    Duolingo JWT format: Header.Payload.Signature
    """
    token = token.strip()
    if token.startswith("Bearer "):
        token = token[7:].strip()

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format: expected 3 parts separated by dots.")

    payload_b64 = parts[1]
    # Add base64 padding if needed
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)

    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(decoded_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to decode JWT payload: {e}") from e

def get_user_id_from_jwt(token: str) -> str:
    """Extracts Duolingo user ID ('sub') from the JWT token."""
    payload = decode_jwt_payload(token)
    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("JWT token does not contain 'sub' (User ID).")
    return str(user_id)

def check_token_validity(token: str) -> tuple[bool, str | None]:
    """
    Checks if token is structurally valid and not expired.
    Returns (is_valid, message).
    """
    try:
        payload = decode_jwt_payload(token)
        exp = payload.get("exp")
        user_id = payload.get("sub")
        username = payload.get("username", "Unknown")

        if exp:
            now = time.time()
            remaining_seconds = exp - now
            if remaining_seconds <= 0:
                return False, f"Token for user '{username}' (ID: {user_id}) has expired."
            remaining_days = remaining_seconds / 86400
            return True, f"Token valid for user '{username}' (ID: {user_id}). Expires in {remaining_days:.1f} days."
        return True, f"Token valid for user '{username}' (ID: {user_id})."
    except ValueError as e:
        return False, f"Token error: {e}"
