from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class AnticipatedQuestion(BaseModel):
    """A projected defense question mapped to an academic council role."""
    role: str = Field(..., description="CHỦ TỊCH HỘI ĐỒNG | GIẢNG VIÊN PHẢN BIỆN | ỦY VIÊN HỘI ĐỒNG")
    question: str = Field(..., description="Câu hỏi phản biện dự kiến")
    reason: str = Field(..., description="Cơ sở/Lý do câu hỏi xuất phát từ đề tài")
    suggested_answer_hint: str = Field(..., description="Định hướng/Gợi ý trả lời bảo vệ quan điểm")


class KnowledgeProfileData(BaseModel):
    """Structured synthesis of thesis document insights."""
    summary: str = Field(..., description="Tóm tắt tổng quan bối cảnh, bài toán và giải pháp của đề tài")
    objectives: List[str] = Field(default_factory=list, description="Danh sách các mục tiêu cụ thể")
    methodology_and_tech: List[str] = Field(default_factory=list, description="Phương pháp luận, kiến trúc & công nghệ cốt lõi")
    contributions: List[str] = Field(default_factory=list, description="Đóng góp mới hoặc tính ứng dụng thực tiễn")
    defense_weaknesses: List[str] = Field(default_factory=list, description="Điểm yếu tiềm ẩn hoặc lỗ hổng dễ bị chất vấn")
    anticipated_questions: List[AnticipatedQuestion] = Field(default_factory=list, description="Bộ câu hỏi dự kiến theo 3 vai trò")


class KnowledgeProfileResponse(BaseModel):
    """API response model for Project Knowledge Profile."""
    id: int
    project_id: int
    version: int
    status: str  # generating, ready, failed
    profile_data: Optional[KnowledgeProfileData] = None
    source_document_ids: List[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GenerateProfileRequest(BaseModel):
    """Optional parameters when triggering profile generation."""
    force_regenerate: bool = False

