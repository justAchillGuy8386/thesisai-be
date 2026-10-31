from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("thesis_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Mode: question_answer (Mode A - Core), full_presentation (Mode B - Slide Presentation)
    mode: Mapped[str] = mapped_column(String(50), default="question_answer", nullable=False)
    # Status: in_progress, completed, partial_failed, cancelled
    status: Mapped[str] = mapped_column(String(50), default="in_progress", nullable=False)
    # Version of knowledge profile bound to this session
    knowledge_profile_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    project = relationship("ThesisProject", back_populates="practice_sessions")
    questions = relationship(
        "Question",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
    )
    slide_events = relationship(
        "PresentationSlideEvent",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    jobs = relationship(
        "ProcessingJob",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PracticeSession id={self.id} project_id={self.project_id} mode='{self.mode}' status='{self.status}'>"
