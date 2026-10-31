from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    answer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Job type: stt, evaluation, audio_metrics
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Status: queued, running, succeeded, failed, retrying
    status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    session = relationship("PracticeSession", back_populates="jobs")
    answer = relationship("Answer", back_populates="jobs")

    def __repr__(self) -> str:
        return f"<ProcessingJob id={self.id} type='{self.job_type}' status='{self.status}'>"
