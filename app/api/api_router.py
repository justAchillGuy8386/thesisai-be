from fastapi import APIRouter
from app.api.routes import health, auth, projects, documents, knowledge_profiles, rag, practice_sessions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(documents.router)
api_router.include_router(knowledge_profiles.router)
api_router.include_router(rag.router)
api_router.include_router(practice_sessions.router)
