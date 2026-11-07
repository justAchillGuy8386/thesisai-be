from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, computed_field


DocumentStatusType = Literal["uploaded", "extracting", "indexing", "ready", "failed"]


@dataclass
class ChunkItem:
    """Represents a coherent text chunk with full provenance metadata."""
    chunk_index: int
    section_title: Optional[str]
    page_number: Optional[int]
    text: str


class DocumentResponse(BaseModel):
    """Public detail schema for an uploaded document."""
    id: int
    project_id: int
    original_filename: str
    mime_type: str
    file_size: int
    version: int
    is_archived: bool
    processing_status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    def file_size_formatted(self) -> str:
        """Human-readable file size."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    """List response of project documents with version info."""
    documents: List[DocumentResponse]
    total: int
    active_version: Optional[int] = None

