from typing import Optional, List
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from app.models.document import Document


class DocumentRepository:
    """Data access repository for Document entity."""

    def get_by_id(self, db: Session, document_id: int) -> Optional[Document]:
        """Fetch document by ID."""
        return db.get(Document, document_id)

    def get_by_project_id(
        self,
        db: Session,
        project_id: int,
        include_archived: bool = True,
    ) -> List[Document]:
        """Fetch all documents belonging to a project, ordered by version descending."""
        stmt = select(Document).where(Document.project_id == project_id)
        if not include_archived:
            stmt = stmt.where(Document.is_archived == False)
        stmt = stmt.order_by(Document.version.desc(), Document.created_at.desc())
        return list(db.scalars(stmt).all())

    def get_by_hash(
        self,
        db: Session,
        project_id: int,
        content_hash: str,
    ) -> Optional[Document]:
        """Check if identical document content was already uploaded to this project."""
        stmt = select(Document).where(
            Document.project_id == project_id,
            Document.content_hash == content_hash,
        )
        return db.scalars(stmt).first()

    def get_latest_version(self, db: Session, project_id: int) -> int:
        """Find the highest document version number in the project."""
        stmt = select(func.max(Document.version)).where(Document.project_id == project_id)
        max_ver = db.scalar(stmt)
        return int(max_ver) if max_ver is not None else 0

    def archive_older_versions(
        self,
        db: Session,
        project_id: int,
        active_doc_id: int,
    ) -> int:
        """
        Mark all older documents in this project as archived so only the active version is queried.
        """
        stmt = (
            update(Document)
            .where(
                Document.project_id == project_id,
                Document.id != active_doc_id,
            )
            .values(is_archived=True)
        )
        result = db.execute(stmt)
        db.commit()
        return result.rowcount

    def create(
        self,
        db: Session,
        project_id: int,
        original_filename: str,
        mime_type: str,
        storage_path: str,
        file_size: int,
        content_hash: str,
        version: int = 1,
        processing_status: str = "uploaded",
    ) -> Document:
        """Create and persist a new document record."""
        doc = Document(
            project_id=project_id,
            original_filename=original_filename,
            mime_type=mime_type,
            storage_path=storage_path,
            file_size=file_size,
            content_hash=content_hash,
            version=version,
            is_archived=False,
            processing_status=processing_status,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    def update_status(
        self,
        db: Session,
        document: Document,
        status: str,
        error_message: Optional[str] = None,
    ) -> Document:
        """Update processing status and error message."""
        document.processing_status = status
        document.error_message = error_message
        db.commit()
        db.refresh(document)
        return document

    def delete(self, db: Session, document: Document) -> None:
        """Delete document record and cascade chunks."""
        db.delete(document)
        db.commit()


document_repo = DocumentRepository()

