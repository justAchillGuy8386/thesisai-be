from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import Integer, String, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ProjectKnowledgeProfile(Base):
    __tablename__ = "project_knowledge_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("thesis_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    profile_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # Overview, stack, problem, limitations
    source_document_ids: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="ready", nullable=False)  # generating, ready, failed

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    project = relationship("ThesisProject", back_populates="knowledge_profiles")

    def __repr__(self) -> str:
        return f"<ProjectKnowledgeProfile id={self.id} project_id={self.project_id} v{self.version} status='{self.status}'>"
