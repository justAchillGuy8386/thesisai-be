from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "debug": settings.DEBUG,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
    }
