import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

_hasher = PasswordHash.recommended()  # Argon2id


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return _hasher.verify(password, password_hash)


# Hash konstan untuk menyamakan waktu verifikasi bila email tidak ditemukan.
DUMMY_HASH = _hasher.hash("timing-equalizer")


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, expires_at: datetime) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm], options={"require": ["sub", "sid", "exp"]})


def session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=get_settings().access_token_minutes)
