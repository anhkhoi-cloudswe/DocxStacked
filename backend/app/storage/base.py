from abc import ABC, abstractmethod
from typing import Optional


class Storage(ABC):
    """Abstract file storage interface for raw images, HTML, exports, attachments."""

    @abstractmethod
    def save(self, relative_path: str, data: bytes) -> str:
        """Save file bytes at relative_path. Returns local path or URL."""
        pass

    @abstractmethod
    def read(self, relative_path: str) -> bytes:
        """Read bytes from relative_path."""
        pass

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        """Check if file exists at relative_path."""
        pass

    @abstractmethod
    def delete(self, relative_path: str) -> bool:
        """Delete file at relative_path if it exists."""
        pass

    @abstractmethod
    def get_path(self, relative_path: str) -> str:
        """Get absolute path or storage key."""
        pass

