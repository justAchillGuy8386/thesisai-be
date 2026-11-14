from typing import List, Optional
from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    """Request model for scoped RAG query."""
    query: str = Field(..., min_length=2, max_length=1000, description="Nội dung câu hỏi kỹ thuật đối chiếu với đề tài")
    top_k: int = Field(default=4, ge=1, le=10, description="Số lượng đoạn trích xuất đối chiếu tối đa")
    min_similarity: float = Field(default=0.2, ge=0.0, le=1.0, description="Ngưỡng tương đồng cosine tối thiểu")


class RagCitation(BaseModel):
    """Citation provenance for evidence-grounded answer."""
    chunk_id: int
    document_id: int
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    text: str
    similarity_score: float

    def format_citation_header(self) -> str:
        loc = f"Trang {self.page_number}" if self.page_number else "Tài liệu"
        sec = f" | Mục: {self.section_title}" if self.section_title else ""
        return f"[{loc}{sec} (Độ khớp: {self.similarity_score:.0%})]"


class RagQueryResponse(BaseModel):
    """Response model returning grounded answer with exact academic citations."""
    project_id: int
    query: str
    answer: str
    citations: List[RagCitation] = Field(default_factory=list)
    has_evidence: bool = True

