from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class AnswerSubmitResponse(BaseModel):
    """API response immediately returned upon audio upload."""
    id: int
    question_id: int
    audio_path: Optional[str] = None
    audio_mime_type: str = "audio/webm"
    duration_seconds: Optional[float] = None
    processing_status: str = "queued"
    audio_status: str = "active"
    created_at: datetime
    message: str = "Đã tiếp nhận file ghi âm thành công. Tác vụ xử lý ngầm đang xếp hàng."

    class Config:
        from_attributes = True


class AnswerDetailResponse(BaseModel):
    """Detailed response for an Answer record, including transcript and audio status."""
    id: int
    question_id: int
    audio_mime_type: str
    duration_seconds: Optional[float] = None
    transcript: Optional[str] = None
    transcript_segments: Optional[List[Dict[str, Any]]] = None
    processing_status: str  # queued, transcribing, evaluating, completed, failed
    audio_status: str  # active, purged, expired
    audio_url: Optional[str] = None
    error_fields: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

