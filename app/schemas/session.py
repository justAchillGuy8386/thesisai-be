from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from app.schemas.question import QuestionResponse


class PracticeSessionCreateRequest(BaseModel):
    mode: str = Field(
        default="question_answer",
        description="Chế độ luyện tập: question_answer (Tập trung câu hỏi) | full_presentation (Thuyết trình slide)",
    )
    target_questions: int = Field(
        default=12,
        ge=5,
        le=20,
        description="Số lượng câu hỏi cần sinh (khuyến nghị 12 câu)",
    )


class PracticeSessionListItemResponse(BaseModel):
    id: int
    session_number: int = 1
    project_id: int
    mode: str
    status: str
    knowledge_profile_version: int
    total_questions: int = 0
    answered_questions: int = 0
    started_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PracticeSessionDetailResponse(BaseModel):
    id: int
    session_number: int = 1
    project_id: int
    mode: str
    status: str
    knowledge_profile_version: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    questions: List[QuestionResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class UpdateSessionStatusRequest(BaseModel):
    status: str = Field(..., description="in_progress | completed | cancelled")

