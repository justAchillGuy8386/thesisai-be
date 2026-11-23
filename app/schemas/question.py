from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class QuestionDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class GeneratedQuestionItem(BaseModel):
    """A generated defense question with grounded outline and chunk citations."""
    order_index: int = Field(..., description="Thứ tự câu hỏi trong phiên luyện tập (bắt đầu từ 1)")
    question_text: str = Field(..., description="Nội dung câu hỏi bảo vệ đồ án")
    difficulty: QuestionDifficulty = Field(default=QuestionDifficulty.MEDIUM, description="Mức độ khó: easy, medium, hard")
    topic_competency: str = Field(..., description="Lĩnh vực / năng lực chuyên môn đang đánh giá")
    expected_answer_outline: str = Field(..., description="Dàn ý câu trả lời kỳ vọng (các ý cốt lõi sinh viên cần trình bày)")
    source_chunk_ids: List[int] = Field(default_factory=list, description="Danh sách ID các đoạn trích tài liệu làm căn cứ")
    recommended_seconds: int = Field(default=120, description="Thời gian khuyến nghị trả lời (giây)")


class GeneratedQuestionSet(BaseModel):
    """Collection of generated questions for a defense session."""
    project_id: int
    questions: List[GeneratedQuestionItem] = Field(default_factory=list)
    total_questions: int = Field(0)
    easy_count: int = Field(0)
    medium_count: int = Field(0)
    hard_count: int = Field(0)


class QuestionResponse(BaseModel):
    """API response model for an existing Question."""
    id: int
    session_id: int
    order_index: int
    question_text: str
    difficulty: str
    topic_competency: str
    expected_answer_outline: str
    source_chunk_ids: List[int] = Field(default_factory=list)
    recommended_seconds: int
    is_answered: bool = False
    answer_id: Optional[int] = None
    answer_processing_status: str = "unanswered"
    created_at: datetime

    class Config:
        from_attributes = True

