import hashlib
import hmac

from .config import settings


def sign_body(body: bytes, secret: str | None = None) -> str:
    key = (secret or settings.webhook_secret).encode("utf-8")
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, supplied: str) -> bool:
    expected = sign_body(body)
    return hmac.compare_digest(expected, supplied.strip().lower())
