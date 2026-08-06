from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)
        self._signing_key = hashlib.sha256(key + b":download-signing").digest()

    @classmethod
    def load(cls, data_dir: Path) -> "SecretBox":
        configured = os.getenv("PATENTRADAR_MASTER_KEY", "").strip()
        if configured:
            return cls(configured.encode("ascii"))
        data_dir.mkdir(parents=True, exist_ok=True)
        key_path = data_dir / ".master_key"
        if key_path.exists():
            return cls(key_path.read_bytes().strip())
        key = Fernet.generate_key()
        key_path.write_bytes(key + b"\n")
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return cls(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("密钥无法解密，请检查 PATENTRADAR_MASTER_KEY") from exc

    def sign_download(self, *, workspace_id: str, case_id: str, expires_in: int = 900) -> str:
        expires_at = int(time.time()) + expires_in
        message = f"{workspace_id}:{case_id}:{expires_at}".encode()
        signature = hmac.new(self._signing_key, message, hashlib.sha256).digest()
        raw = f"{expires_at}.".encode() + base64.urlsafe_b64encode(signature).rstrip(b"=")
        return raw.decode("ascii")

    def verify_download(self, token: str, *, workspace_id: str, case_id: str) -> bool:
        try:
            expires_raw, signature_raw = token.split(".", 1)
            expires_at = int(expires_raw)
            padding = "=" * (-len(signature_raw) % 4)
            supplied = base64.urlsafe_b64decode(signature_raw + padding)
        except (ValueError, TypeError):
            return False
        if expires_at < int(time.time()):
            return False
        message = f"{workspace_id}:{case_id}:{expires_at}".encode()
        expected = hmac.new(self._signing_key, message, hashlib.sha256).digest()
        return hmac.compare_digest(supplied, expected)


def new_workspace_token() -> str:
    return "prw_" + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
