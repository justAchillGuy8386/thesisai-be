import hashlib
from pathlib import Path
from typing import List, Optional
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.repositories.document_repo import document_repo
from app.repositories.project_repo import project_repo
from app.storage import storage_provider
from app.services.document_extractor import document_extractor, ExtractedPage


MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB limit
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx"}


class DocumentService:
    """Business logic for document uploads, versioning, and text extraction."""

    def upload_document(
        self,
        db: Session,
        project_id: int,
        current_user: User,
        file: UploadFile,
    ) -> DocumentResponse:
        """
        Validate, save file to disk, compute SHA-256 hash, and register in database.
        Increments document version and archives previous versions.
        """
        # 1. Project existence & ownership check
        project = project_repo.get_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
            )

        is_owner = project.student_id == current_user.id
        is_admin = current_user.role == "admin"
        if not (is_owner or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền tải tài liệu lên đề tài này.",
            )

        # 2. Filename & Extension validation
        original_filename = file.filename or "tailieu"
        ext = Path(original_filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Định dạng tệp '{ext}' không được hỗ trợ. Vui lòng tải lên file .pdf, .docx hoặc .pptx.",
            )

        # 3. Read content & validate file size
        content = file.file.read()
        file_size = len(content)

        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tệp rỗng. Vui lòng chọn tệp có nội dung.",
            )

        if file_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dung lượng tệp ({file_size / (1024 * 1024):.1f}MB) vượt quá giới hạn tối đa cho phép là 50MB.",
            )

        # 4. Compute SHA-256 hash
        content_hash = hashlib.sha256(content).hexdigest()

        # 5. Check duplicate upload in this project
        duplicate = document_repo.get_by_hash(db, project_id, content_hash)
        if duplicate and not duplicate.is_archived:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tài liệu có nội dung giống hệt đã tồn tại trong đồ án (Phiên bản v{duplicate.version}).",
            )

        # 6. Determine new version number
        latest_version = document_repo.get_latest_version(db, project_id)
        new_version = latest_version + 1

        # 7. Store file on local disk via storage_provider (outside web root)
        storage_rel_path = storage_provider.save_file(
            content=content,
            subfolder="uploads/documents",
            extension=ext,
        )

        mime_type = file.content_type or "application/octet-stream"

        # 8. Persist document record
        document = document_repo.create(
            db=db,
            project_id=project_id,
            original_filename=original_filename,
            mime_type=mime_type,
            storage_path=storage_rel_path,
            file_size=file_size,
            content_hash=content_hash,
            version=new_version,
            processing_status="uploaded",
        )

        # 9. Archive previous documents so only current version is active
        document_repo.archive_older_versions(
            db=db,
            project_id=project_id,
            active_doc_id=document.id,
        )

        return DocumentResponse.model_validate(document)

    def get_project_documents(
        self,
        db: Session,
        project_id: int,
        current_user: User,
    ) -> DocumentListResponse:
        """Fetch all documents of a project with ownership validation."""
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
                detail="Bạn không có quyền xem tài liệu của đề tài này.",
            )

        docs = document_repo.get_by_project_id(db, project_id, include_archived=True)
        active_ver = next((d.version for d in docs if not d.is_archived), None)

        return DocumentListResponse(
            documents=[DocumentResponse.model_validate(d) for d in docs],
            total=len(docs),
            active_version=active_ver,
        )

    def delete_document(
        self,
        db: Session,
        project_id: int,
        document_id: int,
        current_user: User,
    ) -> None:
        """Delete document file and record."""
        project = project_repo.get_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
            )

        is_owner = project.student_id == current_user.id
        is_admin = current_user.role == "admin"

        if not (is_owner or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền xóa tài liệu của đề tài này.",
            )

        document = document_repo.get_by_id(db, document_id)
        if not document or document.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy tài liệu cần xóa.",
            )

        # Delete physical file
        storage_provider.delete_file(document.storage_path)

        # Delete from database
        document_repo.delete(db, document)

    def extract_document_text(
        self,
        db: Session,
        document_id: int,
    ) -> List[ExtractedPage]:
        """Extract structured text from a document."""
        document = document_repo.get_by_id(db, document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy tài liệu.",
            )

        abs_path = storage_provider.get_file_path(document.storage_path)
        if not abs_path or not abs_path.is_file():
            document_repo.update_status(
                db, document, status="failed", error_message="Tệp vật lý không tồn tại trên đĩa."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tệp tài liệu không tồn tại trên hệ thống lưu trữ.",
            )

        document_repo.update_status(db, document, status="extracting")

        try:
            pages = document_extractor.extract(abs_path, document.original_filename)
            return pages
        except Exception as e:
            document_repo.update_status(
                db, document, status="failed", error_message=str(e)
            )
            raise


document_service = DocumentService()

