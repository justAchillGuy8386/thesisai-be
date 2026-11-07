from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.schemas.document import ChunkItem


class ChunkRepository:
    """Data access repository for DocumentChunk entity."""

    def bulk_create_chunks(
        self,
        db: Session,
        project_id: int,
        document_id: int,
        chunks: List[ChunkItem],
    ) -> int:
        """Persist a batch of chunks for a document with is_active = True."""
        chunk_objects = [
            DocumentChunk(
                document_id=document_id,
                project_id=project_id,
                chunk_index=item.chunk_index,
                section_title=item.section_title,
                page_number=item.page_number,
                text=item.text,
                is_active=True,
            )
            for item in chunks
        ]
        db.add_all(chunk_objects)
        db.commit()
        return len(chunk_objects)

    def deactivate_older_chunks(
        self,
        db: Session,
        project_id: int,
        active_document_id: int,
    ) -> int:
        """
        Anti-Stale Guard: Mark chunks of previously superseded documents as is_active = False.
        Only the active document version will be queried during RAG retrieval.
        """
        stmt = (
            update(DocumentChunk)
            .where(
                DocumentChunk.project_id == project_id,
                DocumentChunk.document_id != active_document_id,
            )
            .values(is_active=False)
        )
        result = db.execute(stmt)
        db.commit()
        return result.rowcount

    def get_chunks_by_document(
        self,
        db: Session,
        document_id: int,
    ) -> List[DocumentChunk]:
        """Fetch all chunks belonging to a document ordered by index."""
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(db.scalars(stmt).all())

    def get_active_chunks_by_project(
        self,
        db: Session,
        project_id: int,
    ) -> List[DocumentChunk]:
        """Fetch all active chunks belonging to the current document version of a project."""
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.project_id == project_id,
                DocumentChunk.is_active == True,
            )
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(db.scalars(stmt).all())

    def delete_chunks_by_document(
        self,
        db: Session,
        document_id: int,
    ) -> int:
        """Delete all chunks of a document."""
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        result = db.execute(stmt)
        db.commit()
        return result.rowcount


chunk_repo = ChunkRepository()
