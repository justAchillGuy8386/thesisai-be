from fastapi import APIRouter, Depends, UploadFile, File, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user, require_student
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.services.document_service import document_service

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tải lên tài liệu đồ án (PDF, DOCX, PPTX)",
)
def upload_document(
    project_id: int,
    file: UploadFile = File(..., description="Tệp tài liệu đồ án (tối đa 50MB, định dạng PDF, DOCX, PPTX)"),
    db: Session = Depends(get_db),
    current_student: User = Depends(require_student),
) -> DocumentResponse:
    """
    Sinh viên tải lên tài liệu đề cương hoặc toàn văn luận văn tốt nghiệp.
    Hệ thống kiểm tra bảo mật, định dạng, sinh mã băm SHA-256 và tự động cập nhật số phiên bản (versioning).
    """
    return document_service.upload_document(
        db=db,
        project_id=project_id,
        current_user=current_student,
        file=file,
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="Lấy danh sách tài liệu của đề tài",
)
def list_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentListResponse:
    """
    Lấy toàn bộ danh sách tài liệu đã tải lên của đề tài, bao gồm các phiên bản cũ đã lưu trữ.
    """
    return document_service.get_project_documents(
        db=db,
        project_id=project_id,
        current_user=current_user,
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Xóa tài liệu khỏi đề tài",
)
def delete_document(
    project_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_student: User = Depends(require_student),
):
    """
    Xóa tài liệu và tệp tin lưu trữ tương ứng khỏi hệ thống.
    """
    document_service.delete_document(
        db=db,
        project_id=project_id,
        document_id=document_id,
        current_user=current_student,
    )
    return {"message": "Đã xóa tài liệu thành công"}

