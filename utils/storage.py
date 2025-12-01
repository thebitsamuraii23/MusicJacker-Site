import os
import time
import tempfile
from typing import Optional
import uuid

DEFAULT_TTL_SECONDS = int(os.getenv('TEMP_STORAGE_TTL', '3600'))


class LocalStorageDriver:
    """Simple local /tmp backed storage driver with TTL awareness.

    This is intentionally small — use S3/MinIO production driver instead.
    """

    def __init__(self, base_dir: Optional[str] = None, ttl: int = DEFAULT_TTL_SECONDS):
        self.base_dir = base_dir or tempfile.gettempdir()
        self.ttl = ttl
        os.makedirs(self.base_dir, exist_ok=True)

    def path_for(self, key: str) -> str:
        return os.path.join(self.base_dir, key)

    def save(self, key: str, data: bytes) -> str:
        path = self.path_for(key)
        with open(path, 'wb') as fh:
            fh.write(data)
        # embed timestamp in mtime
        os.utime(path, None)
        return path

    def exists(self, key: str) -> bool:
        path = self.path_for(key)
        return os.path.exists(path)

    def delete(self, key: str) -> None:
        try:
            os.remove(self.path_for(key))
        except FileNotFoundError:
            pass

    def cleanup_old(self) -> int:
        now = time.time()
        removed = 0
        for name in os.listdir(self.base_dir):
            p = os.path.join(self.base_dir, name)
            try:
                mtime = os.path.getmtime(p)
                if now - mtime > self.ttl:
                    os.unlink(p)
                    removed += 1
            except Exception:
                continue
        return removed


class TokenManager:
    """In-memory token manager for short-lived signed file downloads.

    Production should store this mapping in Redis with TTL for reliability.
    """

    def __init__(self):
        # token -> (absolute_path, expires_at)
        self._tokens = {}

    def create_token(self, absolute_path: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
        token = uuid.uuid4().hex
        self._tokens[token] = (absolute_path, time.time() + ttl_seconds)
        return token

    def validate_token(self, token: str) -> Optional[str]:
        item = self._tokens.get(token)
        if not item:
            return None
        path, expires = item
        if time.time() > expires:
            try:
                del self._tokens[token]
            except KeyError:
                pass
            return None
        return path

    def revoke(self, token: str) -> None:
        try:
            del self._tokens[token]
        except KeyError:
            pass


# module-level token manager (replace with Redis-backed store in prod)
token_manager = TokenManager()
