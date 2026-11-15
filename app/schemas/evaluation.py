from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict, AliasChoices


class CriterionScoresDetail(BaseModel):
    """Chi tiết điểm thành phần theo rubric bảo vệ đồ án tốt nghiệp."""
    technical_accuracy: float = Field(..., ge=0.0, le=10.0, description="Độ chính xác kỹ thuật và chuyên môn")
    completeness: float = Field(..., ge=0.0, le=10.0, description="Độ đầy đủ so với yêu cầu câu hỏi và outline")
    reasoning_defense: float = Field(..., ge=0.0, le=10.0, description="Lập luận logic, phản biện và trade-off công nghệ")
    speech_pace: Optional[float] = Field(None, ge=0.0, le=10.0, description="Tốc độ nói (WPM)")
    fluency: Optional[float] = Field(None, ge=0.0, le=10.0, description="Độ trôi chảy và ngắt nghỉ tự nhiên")


class FeedbackDetail(BaseModel):
    """Nhận xét chi tiết mang tính xây dựng cho sinh viên."""
    strengths: List[str] = Field(default_factory=list, description="Các điểm mạnh đáng khen ngợi")
    weaknesses: List[str] = Field(default_factory=list, description="Các điểm thiếu sót hoặc nhầm lẫn")
    suggestions: List[str] = Field(default_factory=list, description="Khuyến nghị cải thiện cụ thể để bảo vệ tốt hơn")
    model_answer: Optional[str] = Field(None, description="Câu trả lời mẫu định hướng bảo vệ đồ án")


class EvidenceDetail(BaseModel):
    """Căn cứ trích dẫn từ tài liệu đồ án (grounding provenance)."""
    cited_chunk_ids: List[int] = Field(default_factory=list, description="Danh sách chunk ID tài liệu căn cứ")
    matched_keywords: List[str] = Field(default_factory=list, description="Từ khóa chuyên môn xuất hiện trong câu trả lời")
    grounding_notes: Optional[str] = Field(None, description="Ghi chú đối chiếu tài liệu")


class ModelMetadataDetail(BaseModel):
    """Minh bạch thuật toán & AI Ethics-by-Design."""
    model: str = Field(..., description="Tên mô hình LLM cục bộ (ví dụ: qwen2.5:7b)")
    evaluation_latency_seconds: Optional[float] = Field(None, description="Thời gian thực thi đánh giá")
    disclaimer: str = Field(
        default="Đánh giá được tạo tự động bởi AI nhằm mục đích rèn luyện phản xạ bảo vệ đồ án tốt nghiệp, không thay thế nhận xét trực tiếp của Hội đồng Chuyên môn.",
        description="Khuyến cáo đạo đức AI"
    )


class AnswerEvaluationResponse(BaseModel):
    """Response DTO trả về cho sinh viên và hội đồng."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    answer_id: int
    overall_score: float = Field(..., description="Điểm tổng thể thang 10 (Nội dung 80% + Phong thái 20%)")
    content_score: float = Field(..., description="Điểm nội dung học thuật (Thang 10)")
    delivery_score: Optional[float] = Field(None, description="Điểm phong thái trình bày (Thang 10)")

    criterion_scores: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("criterion_scores_json", "criterion_scores"),
        description="Chi tiết rubric thành phần"
    )
    feedback: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("feedback_json", "feedback"),
        description="Nhận xét điểm mạnh, điểm yếu và gợi ý"
    )
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("evidence_json", "evidence"),
        description="Căn cứ trích dẫn tài liệu"
    )
    model_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("model_metadata_json", "model_metadata"),
        description="Minh bạch AI"
    )
    created_at: datetime

