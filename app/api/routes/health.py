import json
import time
import urllib.request
import urllib.error
from fastapi import APIRouter
from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine
from app.storage import storage_provider

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
def health_check():
    start_time = time.time()

    # 1. Check PostgreSQL Database connection
    db_status = {"status": "unknown"}
    try:
        db_start = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = {
            "status": "connected",
            "latency_ms": round((time.time() - db_start) * 1000, 2),
            "database": "postgresql (pgvector)",
        }
    except Exception as e:
        db_status = {
            "status": "disconnected",
            "error": str(e),
        }

    # 2. Check Ollama Local AI connection
    ollama_status = {"status": "unknown"}
    try:
        ollama_start = time.time()
        req = urllib.request.Request(
            f"{settings.OLLAMA_BASE_URL}/api/tags",
            headers={"User-Agent": "ThesisAI-Backend"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in body.get("models", [])]
                ollama_status = {
                    "status": "connected",
                    "latency_ms": round((time.time() - ollama_start) * 1000, 2),
                    "base_url": settings.OLLAMA_BASE_URL,
                    "target_llm": settings.LLM_MODEL,
                    "installed_models": models,
                }
            else:
                ollama_status = {
                    "status": "error",
                    "http_code": resp.status,
                }
    except Exception as e:
        ollama_status = {
            "status": "disconnected",
            "base_url": settings.OLLAMA_BASE_URL,
            "error": str(e),
        }

    # 3. Check Storage & Disk Space
    storage_stats = None
    try:
        storage_stats = storage_provider.get_storage_stats()
    except Exception as e:
        storage_stats = {"error": str(e)}

    # Determine overall system health
    is_db_ok = db_status.get("status") == "connected"
    is_ollama_ok = ollama_status.get("status") == "connected"

    overall_status = "healthy" if (is_db_ok and is_ollama_ok) else "degraded"

    return {
        "status": overall_status,
        "service": settings.PROJECT_NAME,
        "debug": settings.DEBUG,
        "response_time_ms": round((time.time() - start_time) * 1000, 2),
        "database": db_status,
        "ollama": ollama_status,
        "storage": storage_stats,
    }
