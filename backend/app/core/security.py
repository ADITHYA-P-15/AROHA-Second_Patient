from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerifyMismatchError, Exception):
        return False


def create_token(user) -> str:
    issued = datetime.now(UTC)
    return jwt.encode({"sub": str(user.id), "role": user.role, "tv": user.token_version,
                       "iat": issued, "exp": issued + timedelta(hours=settings.session_hours)},
                      settings.secret_key, algorithm=ALGORITHM)
