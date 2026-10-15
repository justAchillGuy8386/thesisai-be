from app.storage.base import BaseStorage
from app.storage.local import LocalStorage

# Default singleton storage provider for backend
storage_provider: BaseStorage = LocalStorage()

__all__ = ["BaseStorage", "LocalStorage", "storage_provider"]
