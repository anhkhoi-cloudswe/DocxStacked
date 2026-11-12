from pathlib import Path
from typing import Optional

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.storage.base import Storage

logger = get_logger(__name__)


class LocalStorage(Storage):
    """Local disk storage implementation storing files in data/."""

    def __init__(self, root_dir: Optional[Path] = None):
        settings = get_settings()
        self.root_dir = root_dir or settings.STORAGE_DIR
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        clean_rel = relative_path.lstrip("/\\")
        resolved = (self.root_dir / clean_rel).resolve()
        # Security check: prevent directory traversal
        if not str(resolved).startswith(str(self.root_dir.resolve())):
            raise ValueError(f"Path traversal detected: {relative_path}")
        return resolved

    def save(self, relative_path: str, data: bytes) -> str:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        logger.debug(f"Saved {len(data)} bytes to {target}")
        return str(target)

    def read(self, relative_path: str) -> bytes:
        target = self._resolve(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        return target.read_bytes()

    def exists(self, relative_path: str) -> bool:
        target = self._resolve(relative_path)
        return target.exists() and target.is_file()

    def delete(self, relative_path: str) -> bool:
        target = self._resolve(relative_path)
        if target.exists():
            target.unlink()
            return True
        return False

    def get_path(self, relative_path: str) -> str:
        return str(self._resolve(relative_path))

