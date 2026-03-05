from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

SECRET_ENV = "HENU_SECRET_KEY"
SECRET_FILE = Path(__file__).resolve().parent / ".henu_secret.key"
PREFIX = "enc:v1:"


def _normalize_key(secret: str) -> bytes:
    key_bytes = secret.strip().encode("utf-8")
    try:
        Fernet(key_bytes)
        return key_bytes
    except Exception:
        digest = hashlib.sha256(key_bytes).digest()
        return base64.urlsafe_b64encode(digest)


def _load_or_create_secret() -> str:
    env_secret = os.getenv(SECRET_ENV)
    if env_secret:
        return env_secret

    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()

    generated = Fernet.generate_key().decode("utf-8")
    SECRET_FILE.write_text(generated, encoding="utf-8")
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return generated


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(_normalize_key(_load_or_create_secret()))


def is_encrypted_value(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if is_encrypted_value(value):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not is_encrypted_value(value):
        return value
    token = value[len(PREFIX):]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            f"密文解密失败，请确认环境变量 {SECRET_ENV} 与加密时一致"
        ) from exc
