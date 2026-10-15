import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from app.core.config import settings
from app.storage.base import BaseStorage


class LocalStorage(BaseStorage):
    """
    Local filesystem implementation of BaseStorage.
    Ensures safe path operations, UUID-based file storage, and privacy cleanup.
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or settings.STORAGE_DIR).resolve()
        self.documents_dir = (self.base_dir / "uploads" / "documents").resolve()
        self.audio_dir = (self.base_dir / "uploads" / "audio").resolve()

        # Ensure directories exist
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    # chan viec truy cap ra ngoai folder storage
    def _resolve_safe_path(self, relative_path: str) -> Path:
        """
        Resolve relative path and verify it stays inside base_dir (Path Traversal Protection).
        """
        # Normalize slashes
        clean_rel = Path(relative_path.replace("\\", "/").lstrip("/"))
        target_path = (self.base_dir / clean_rel).resolve()

        if not str(target_path).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected: {relative_path}")

        return target_path

    def save_file(
        self,
        content: bytes,
        subfolder: str,
        extension: str,
        custom_filename: Optional[str] = None,
    ) -> str:
        """
        Save file content to base_dir / subfolder.
        Returns normalized relative path string.
        """
        # Ensure subfolder exists
        target_dir = (self.base_dir / subfolder.strip("/\\")).resolve()
        if not str(target_dir).startswith(str(self.base_dir)):
            raise ValueError(f"Invalid subfolder: {subfolder}")
        target_dir.mkdir(parents=True, exist_ok=True)

        # Generate safe filename
        ext = extension.lstrip(".")
        if custom_filename:
            # Strip dangerous chars
            safe_name = "".join(c for c in custom_filename if c.isalnum() or c in "._-")
            filename = f"{safe_name}.{ext}" if not safe_name.endswith(f".{ext}") else safe_name
        else:
            filename = f"{uuid.uuid4().hex}.{ext}"

        file_path = target_dir / filename
        with open(file_path, "wb") as f:
            f.write(content)

        # Return relative path from base_dir with forward slashes
        rel_path = file_path.relative_to(self.base_dir).as_posix()
        return rel_path

    def get_file_path(self, relative_path: str) -> Optional[Path]:
        try:
            target_path = self._resolve_safe_path(relative_path)
            if target_path.is_file():
                return target_path
            return None
        except ValueError:
            return None

    def read_file(self, relative_path: str) -> bytes:
        target_path = self._resolve_safe_path(relative_path)
        if not target_path.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")
        with open(target_path, "rb") as f:
            return f.read()

    def delete_file(self, relative_path: str) -> bool:
        try:
            target_path = self._resolve_safe_path(relative_path)
            if target_path.is_file():
                target_path.unlink()
                return True
            return False
        except (ValueError, FileNotFoundError):
            return False

    def purge_session_audio(self, session_id: str) -> int:
        """
        Purge all audio files under uploads/audio/{session_id}/
        or files prefixed with session_id.
        """
        deleted_count = 0
        session_folder = (self.audio_dir / session_id).resolve()

        if session_folder.is_dir() and str(session_folder).startswith(str(self.audio_dir)):
            for item in session_folder.glob("*"):
                if item.is_file():
                    item.unlink()
                    deleted_count += 1
            # Remove the empty directory
            try:
                session_folder.rmdir()
            except OSError:
                pass
        else:
            # Also check for files prefixed with session_id
            for file_path in self.audio_dir.glob(f"{session_id}_*"):
                if file_path.is_file():
                    file_path.unlink()
                    deleted_count += 1

        return deleted_count

    def cleanup_expired_files(self, subfolder: str, max_age_hours: int) -> int:
        """
        Delete files older than max_age_hours in uploads/{subfolder}.
        """
        target_dir = (self.base_dir / subfolder.strip("/\\")).resolve()
        if not target_dir.is_dir() or not str(target_dir).startswith(str(self.base_dir)):
            return 0

        cutoff_time = time.time() - (max_age_hours * 3600)
        deleted_count = 0

        for root, _, files in os.walk(target_dir):
            for file in files:
                file_path = Path(root) / file
                try:
                    if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                except (OSError, PermissionError):
                    continue

        return deleted_count

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Return disk space and directory sizes in MB / GB.
        """
        disk = shutil.disk_usage(self.base_dir)

        def get_dir_size(path: Path) -> float:
            total = 0
            if path.is_dir():
                for entry in path.rglob("*"):
                    if entry.is_file():
                        total += entry.stat().st_size
            return round(total / (1024 * 1024), 2)  # in MB

        return {
            "storage_root": str(self.base_dir),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "documents_size_mb": get_dir_size(self.documents_dir),
            "audio_size_mb": get_dir_size(self.audio_dir),
        }
