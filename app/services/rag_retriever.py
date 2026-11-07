import logging
from dataclasses import dataclass
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repo import chunk_repo
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """Represents a retrieved document chunk with provenance and similarity score."""
    chunk_id: int
    document_id: int
    page_number: Optional[int]
    section_title: Optional[str]
    text: str
    similarity_score: float

    def format_citation(self) -> str:
        """Format an academic citation header for LLM context injection."""
        loc = f"Trang {self.page_number}" if self.page_number else "Tài liệu"
        sec = f" | Mục: {self.section_title}" if self.section_title else ""
        return f"[{loc}{sec} (Độ khớp: {self.similarity_score:.0%})]"


class RagRetriever:
    """
    Scoped Vector Retriever with Anti-Stale protection.
    Retrieves most relevant document chunks for a query within a specific project.
    """

    def retrieve(
        self,
        db: Session,
        project_id: int,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.25,
    ) -> List[RetrievedChunk]:
        """
        Embed the user query and perform scoped Cosine similarity search in PostgreSQL.
        Enforces project boundary and active document version guard.
        """
        query_clean = query.strip()
        if not query_clean:
            return []

        # 1. Generate query vector embedding (1024 dims)
        query_embedding = embedding_service.embed_text(query_clean)

        # 2. Vector search in database scoped to project_id and is_active = True
        scored_chunks = chunk_repo.search_similar_chunks(
            db=db,
            project_id=project_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )

        # 3. Filter by similarity threshold
        retrieved: List[RetrievedChunk] = []
        for chunk, score in scored_chunks:
            if score >= min_similarity:
                retrieved.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        text=chunk.text,
                        similarity_score=score,
                    )
                )

        logger.info(
            f"RAG Scoped Search (Project {project_id}): Query '{query_clean[:40]}...' matched {len(retrieved)} active chunks."
        )
        return retrieved

    def format_context_for_prompt(self, chunks: List[RetrievedChunk]) -> str:
        """
        Format retrieved chunks into a clean context block for Council LLM prompts.
        Avoids polluting context window while providing clear citation references.
        """
        if not chunks:
            return "Không tìm thấy nội dung tài liệu đối chiếu trực tiếp từ đề cương."

        formatted_blocks = []
        for idx, c in enumerate(chunks, start=1):
            block = f"--- Đoạn trích #{idx} {c.format_citation()} ---\n{c.text}"
            formatted_blocks.append(block)

        return "\n\n".join(formatted_blocks)


rag_retriever = RagRetriever()

