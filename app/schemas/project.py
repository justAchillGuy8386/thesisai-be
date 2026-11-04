from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


ProjectStatusType = Literal["PLANNING", "IN_PROGRESS", "READY_FOR_DEFENSE", "COMPLETED"]


class ProjectCreateRequest(BaseModel):
    """Payload for creating a new thesis project."""
    title: str = Field(..., min_length=3, max_length=255, description="Tên đề tài đồ án tốt nghiệp")
    topic: Optional[str] = Field(None, max_length=255, description="Chuyên ngành / Hướng nghiên cứu")
    description: Optional[str] = Field(None, description="Mô tả tóm tắt nội dung và mục tiêu đề tài")
    academic_year: Optional[str] = Field(None, max_length=20, description="Niên khóa / Năm học (ví dụ: 2023-2024)")
    supervisor_id: Optional[int] = Field(None, description="ID của Giảng viên hướng dẫn (tùy chọn)")


class ProjectUpdateRequest(BaseModel):
    """Payload for updating an existing thesis project."""
    title: Optional[str] = Field(None, min_length=3, max_length=255, description="Tên đề tài đồ án")
    topic: Optional[str] = Field(None, max_length=255, description="Chuyên ngành / Hướng nghiên cứu")
    description: Optional[str] = Field(None, description="Mô tả tóm tắt đề tài")
    status: Optional[ProjectStatusType] = Field(
        None,
        description="Trạng thái đề tài: PLANNING, IN_PROGRESS, READY_FOR_DEFENSE, COMPLETED"
    )
    academic_year: Optional[str] = Field(None, max_length=20, description="Niên khóa / Năm học")
    supervisor_id: Optional[int] = Field(None, description="ID của Giảng viên hướng dẫn")


class LecturerSimpleResponse(BaseModel):
    """Simple lecturer info for selection dropdown."""
    id: int
    name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class ProjectResponse(BaseModel):
    """Full detail of a thesis project response."""
    id: int
    student_id: int
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    supervisor_id: Optional[int] = None
    supervisor_name: Optional[str] = None
    title: str
    topic: Optional[str] = None
    description: Optional[str] = None
    status: str
    academic_year: Optional[str] = None
    documents_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

