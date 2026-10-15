from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any


class BaseStorage(ABC):
    """
    Abstract interface for file storage provider.
    Allows easy swapping between LocalStorage, MinIO, or Cloudflare R2 / S3.
    """

    @abstractmethod
    def save_file(
        self,
        content: bytes,
        subfolder: str,
        extension: str,
        custom_filename: Optional[str] = None,
    ) -> str:
        """
        Save file content and return relative storage path.
        """
        pass

    @abstractmethod
    def get_file_path(self, relative_path: str) -> Optional[Path]:
        """
        Get absolute path for a stored file, validating path traversal.
        """
        pass

    @abstractmethod
    def read_file(self, relative_path: str) -> bytes:
        """
        Read file bytes by relative path.
        """
        pass

    @abstractmethod
    def delete_file(self, relative_path: str) -> bool:
        """
        Delete a file by its relative path. Returns True if deleted.
        """
        pass

    @abstractmethod
    def purge_session_audio(self, session_id: str) -> int:
        """
        Purge all audio files related to a specific session (Privacy / Data Minimization).
        Returns count of deleted files.
        """
        pass

    @abstractmethod
    def cleanup_expired_files(self, subfolder: str, max_age_hours: int) -> int:
        """
        Delete files older than max_age_hours in a specific subfolder.
        Returns count of deleted files.
        """
        pass

    @abstractmethod
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Return disk and directory usage statistics.
        """
        pass
