import logging
import httpx
from dataclasses import dataclass
from typing import List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repo import chunk_repo
from app.services.embedding_service import embedding_service
from app.schemas.rag import RagCitation, RagQueryResponse

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
    Scoped Vector Retriever with Anti-Stale protection and Citation Generation.
    Retrieves most relevant document chunks for a query within a specific project.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 35.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout_seconds

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

    def answer_query_with_citations(
        self,
        db: Session,
        project_id: int,
        query: str,
        top_k: int = 4,
        min_similarity: float = 0.2,
    ) -> RagQueryResponse:
        """
        End-to-End RAG flow (Phase 6, Step 6.3):
        Query -> pgvector Scoped Retrieval -> Citation Extraction -> LLM Evidence-grounded Answer.
        """
        chunks = self.retrieve(
            db=db,
            project_id=project_id,
            query=query,
            top_k=top_k,
            min_similarity=min_similarity,
        )

        if not chunks:
            return RagQueryResponse(
                project_id=project_id,
                query=query,
                answer=(
                    "Tài liệu đồ án hiện tại không có thông tin hoặc bằng chứng trực tiếp đối chiếu với câu hỏi này. "
                    "Đề nghị sinh viên kiểm tra lại phạm vi đề cương hoặc bổ sung thêm tài liệu nghiên cứu."
                ),
                citations=[],
                has_evidence=False,
            )

        citations = [
            RagCitation(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                page_number=c.page_number,
                section_title=c.section_title,
                text=c.text,
                similarity_score=c.similarity_score,
            )
            for c in chunks
        ]

        # Call local LLM or fallback grounded synthesis
        context_block = self.format_context_for_prompt(chunks)
        llm_answer = self._call_ollama_grounded_answer(query, context_block)

        if not llm_answer:
            # Fallback grounded answer synthesis
            top = citations[0]
            header = top.format_citation_header()
            llm_answer = (
                f"Căn cứ trực tiếp theo tài liệu đồ án {header}: {top.text.strip()}\n\n"
                f"Các tài liệu tham chiếu bổ sung liên quan gồm {len(citations)} đoạn trích xuất xứ rõ ràng trong hệ thống."
            )

        return RagQueryResponse(
            project_id=project_id,
            query=query,
            answer=llm_answer,
            citations=citations,
            has_evidence=True,
        )

    def _call_ollama_grounded_answer(self, query: str, context: str) -> Optional[str]:
        """Call local Ollama to answer query grounded strictly in provided evidence."""
        sys_prompt = (
            "Bạn là Trợ lý Học thuật Phản biện Đồ án Tốt nghiệp. Hãy trả lời câu hỏi của người dùng "
            "CHỈ DỰA TRÊN các đoạn trích từ tài liệu đồ án được cung cấp. Bắt buộc dẫn nguồn số trang hoặc mục [Trang X | Mục: Y] "
            "cho từng luận điểm. Trả lời súc tích, văn phong khoa học, không bịa đặt thông tin ngoài tài liệu."
        )
        user_prompt = f"CÂU HỎI:\n{query}\n\nCĂN CỨ TÀI LIỆU ĐỒ ÁN:\n{context}\n\nHÃY TRẢ LỜI CÓ TRÍCH DẪN RÕ RÀNG:"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 450},
                    },
                )
                if res.status_code == 200:
                    payload = res.json()
                    content = payload.get("message", {}).get("content", "").strip()
                    if content:
                        return content
        except Exception as e:
            logger.debug(f"Ollama RAG answer call failed or timed out: {e}")
            return None

        return None


rag_retriever = RagRetriever()


