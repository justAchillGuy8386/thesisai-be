from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.rag import RagQueryRequest, RagQueryResponse
from app.services.rag_retriever import rag_retriever
from app.repositories.project_repo import project_repo

router = APIRouter(prefix="/projects/{project_id}/rag", tags=["rag"])


@router.post(
    "/query",
    response_model=RagQueryResponse,
    summary="Truy vấn RAG đối chiếu tài liệu đồ án có trích dẫn nguồn",
)
def query_rag_evidence(
    project_id: int,
    request: RagQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RagQueryResponse:
    """
    Truy vấn ngữ nghĩa vector trên pgvector có bảo vệ cách ly đề tài (project_id)
    và chống tài liệu cũ (is_active=True). Trả về câu trả lời có trích dẫn chính xác số trang/mục.
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
            detail="Bạn không có quyền truy vấn tài liệu của đề tài này.",
        )

    result = rag_retriever.answer_query_with_citations(
        db=db,
        project_id=project_id,
        query=request.query,
        top_k=request.top_k,
        min_similarity=request.min_similarity,
    )
    return result

