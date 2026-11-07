import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db, SessionLocal
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.knowledge_profile import KnowledgeProfileResponse, GenerateProfileRequest
from app.services.knowledge_profile_service import knowledge_profile_service
from app.repositories.project_repo import project_repo
from app.repositories.knowledge_profile_repo import knowledge_profile_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/knowledge-profile", tags=["knowledge-profile"])


def run_generate_profile_background(project_id: int):
    """Background task runner for knowledge profile synthesis."""
    from app.db import session as db_session_module
    session_factory = getattr(db_session_module, "SessionLocal", SessionLocal)
    db = session_factory()
    try:
        knowledge_profile_service.generate_profile(db=db, project_id=project_id)
    except Exception as e:
        logger.error(f"Background profile generation failed for project {project_id}: {e}", exc_info=True)
    finally:
        db.close()


@router.post(
    "/generate",
    response_model=KnowledgeProfileResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kích hoạt phân tích và tổng hợp Hồ sơ Tri thức Đồ án",
)
def generate_knowledge_profile(
    project_id: int,
    background_tasks: BackgroundTasks,
    request: GenerateProfileRequest = GenerateProfileRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeProfileResponse:
    """
    Kích hoạt LLM phân tích tài liệu và sinh Hồ sơ Tri thức Đồ án.
    Chạy bất đồng bộ qua BackgroundTasks.
    """
    project = project_repo.get_by_id(db, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
        )

    is_owner = project.student_id == current_user.id
    is_supervisor = project.supervisor_id == current_user.id
    is_admin = current_user.role == "admin"

    if not (is_owner or is_supervisor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thực hiện trên đề tài này.",
        )

    # Check if existing profile is already ready and force_regenerate is False
    existing = knowledge_profile_service.get_project_profile(db, project_id)
    if existing and existing.status == "generating":
        return existing

    # Mark as generating
    profile = knowledge_profile_repo.create_or_update(
        db=db,
        project_id=project_id,
        profile_json={},
        source_document_ids=[],
        status="generating",
    )

    # Dispatch to background task
    background_tasks.add_task(run_generate_profile_background, project_id)

    return KnowledgeProfileResponse(
        id=profile.id,
        project_id=profile.project_id,
        version=profile.version,
        status="generating",
        profile_data=None,
        source_document_ids=profile.source_document_ids,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get(
    "",
    response_model=KnowledgeProfileResponse,
    summary="Lấy Hồ sơ Tri thức Đồ án",
)
def get_knowledge_profile(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeProfileResponse:
    """
    Lấy thông tin Hồ sơ Tri thức Đồ án (Tóm tắt, mục tiêu, công nghệ, điểm yếu, câu hỏi phản biện).
    """
    project = project_repo.get_by_id(db, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
        )

    is_owner = project.student_id == current_user.id
    is_supervisor = project.supervisor_id == current_user.id
    is_admin = current_user.role == "admin"

    if not (is_owner or is_supervisor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xem hồ sơ của đề tài này.",
        )

    profile_resp = knowledge_profile_service.get_project_profile(db, project_id)
    if not profile_resp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Đề tài chưa có Hồ sơ Tri thức. Vui lòng kích hoạt tổng hợp.",
        )

    return profile_resp

