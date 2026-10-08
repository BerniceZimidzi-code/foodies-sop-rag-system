import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from backend.database import get_user_by_id


JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(minutes=30)
PASSWORD_ITERATIONS = 310_000
BEARER_SCHEME = HTTPBearer(auto_error=False)


def get_jwt_secret() -> str:
    secret = os.getenv("FOODIES_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "FOODIES_JWT_SECRET must be set to at least 32 characters before starting the app."
        )
    return secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        if len(encoded_hash) > 119:
            return False
        scheme, iterations_text, salt_text, expected_digest = encoded_hash.split("$")
        if (
            scheme != "pbkdf2_sha256"
            or not iterations_text.isascii()
            or not iterations_text.isdecimal()
            or len(iterations_text) > 7
            or len(salt_text) != 32
            or len(expected_digest) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in salt_text + expected_digest
            )
        ):
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = bytes.fromhex(salt_text)
        digest = bytes.fromhex(expected_digest)
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return secrets.compare_digest(actual_digest, digest)
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: str,
    secret: str,
    auth_version: int = 0,
    purpose: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + TOKEN_LIFETIME,
        "ver": auth_version,
    }
    if purpose is not None:
        payload["purpose"] = purpose
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(BEARER_SCHEME)
    ],
    *,
    password_change_only: bool,
) -> dict:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
    except InvalidTokenError as exc:
        raise unauthorized from exc

    user_id = payload.get("sub")
    user = get_user_by_id(user_id) if isinstance(user_id, str) else None
    token_version = payload.get("ver", 0)
    if (
        user is None
        or not user["is_active"]
        or not isinstance(token_version, int)
        or isinstance(token_version, bool)
        or token_version != user["auth_version"]
    ):
        raise unauthorized

    is_password_change_token = payload.get("purpose") == "password_change"
    if password_change_only:
        if not user["must_change_password"] or not is_password_change_token:
            raise unauthorized
        return user

    if user["must_change_password"] or is_password_change_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Change your temporary password before continuing.",
        )
    return user


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(BEARER_SCHEME)
    ],
) -> dict:
    return _get_authenticated_user(credentials, password_change_only=False)


def get_password_change_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(BEARER_SCHEME)
    ],
) -> dict:
    return _get_authenticated_user(credentials, password_change_only=True)
