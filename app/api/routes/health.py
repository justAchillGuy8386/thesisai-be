from fastapi import APIRouter
from app.core.config import settings
from app.storage import storage_provider

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    storage_stats = None
    try:
        storage_stats = storage_provider.get_storage_stats()
    except Exception as e:
        storage_stats = {"error": str(e)}

    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "debug": settings.DEBUG,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "storage": storage_stats,
    }
