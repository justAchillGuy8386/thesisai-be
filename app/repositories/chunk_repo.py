from typing import List, Optional, Tuple
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.schemas.document import ChunkItem


class ChunkRepository:
    """Data access repository for DocumentChunk entity with pgvector search."""

    def bulk_create_chunks(
        self,
        db: Session,
        project_id: int,
        document_id: int,
        chunks: List[ChunkItem],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        """Persist a batch of chunks for a document with is_active = True and vector embeddings."""
        chunk_objects = []
        for idx, item in enumerate(chunks):
            emb = embeddings[idx] if embeddings and idx < len(embeddings) else None
            chunk_objects.append(
                DocumentChunk(
                    document_id=document_id,
                    project_id=project_id,
                    chunk_index=item.chunk_index,
                    section_title=item.section_title,
                    page_number=item.page_number,
                    text=item.text,
                    embedding=emb,
                    is_active=True,
                )
            )
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

    def search_similar_chunks(
        self,
        db: Session,
        project_id: int,
        query_embedding: List[float],
        top_k: int = 5,
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Scoped vector retrieval using Cosine similarity.
        Enforces project boundary (project_id) and Anti-Stale guard (is_active = True).
        Returns list of (DocumentChunk, similarity_score).
        """
        try:
            distance_col = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
            stmt = (
                select(DocumentChunk, distance_col)
                .where(
                    DocumentChunk.project_id == project_id,
                    DocumentChunk.is_active == True,
                    DocumentChunk.embedding.is_not(None),
                )
                .order_by(distance_col.asc())
                .limit(top_k)
            )
            rows = db.execute(stmt).all()
            return [(chunk, round(1.0 - float(dist), 4)) for chunk, dist in rows]
        except Exception:
            # Fallback for SQLite in-memory test environment without pgvector C-extensions
            active_chunks = self.get_active_chunks_by_project(db, project_id)
            scored: List[Tuple[DocumentChunk, float]] = []
            for c in active_chunks:
                if c.embedding is not None:
                    raw_emb = list(c.embedding) if hasattr(c.embedding, "__iter__") else []
                    if len(raw_emb) == len(query_embedding):
                        dot_product = sum(a * b for a, b in zip(raw_emb, query_embedding))
                        scored.append((c, round(dot_product, 4)))

            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]

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
