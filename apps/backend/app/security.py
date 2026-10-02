import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet
from passlib.context import CryptContext
from sqlalchemy import select

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET = os.getenv("JWT_SECRET", "meloli-dev-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)


def create_access_token(user_id: int, role: str, auth_version: int = 0, session_key: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "ver": auth_version,
        "sid": session_key,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def _fernet() -> Fernet:
    raw = os.getenv("SETTINGS_ENCRYPTION_KEY", "meloli-dev-settings-key")
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")



def validate_token_user(token: str, db):
    from .models import AuthSession, User
    payload = decode_access_token(token)
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise ValueError("Account unavailable")
    if int(payload.get("ver", 0)) != int(user.auth_version or 0):
        raise ValueError("Session revoked")
    sid = payload.get("sid")
    if sid:
        session = db.scalar(select(AuthSession).where(AuthSession.session_key == sid, AuthSession.user_id == user.id))
        if not session or session.revoked_at is not None:
            raise ValueError("Session revoked")
    return user
