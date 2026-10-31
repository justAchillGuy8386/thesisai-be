from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import String, Integer, Float, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    # Audio recording storage & provenance (nullable when purged for privacy)
    audio_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    audio_mime_type: Mapped[str] = mapped_column(String(100), default="audio/webm", nullable=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Speech-to-Text transcript
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_segments: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)

    # Status: queued, transcribing, evaluating, completed, failed
    processing_status: Mapped[str] = mapped_column(String(50), default="queued", nullable=False)

    # Privacy by Design & Audio Lifecycle: active, purged, expired
    audio_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    audio_purged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    error_fields: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    question = relationship("Question", back_populates="answer")
    evaluation = relationship(
        "AnswerEvaluation",
        back_populates="answer",
        uselist=False,
        cascade="all, delete-orphan",
    )
    jobs = relationship(
        "ProcessingJob",
        back_populates="answer",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Answer id={self.id} question_id={self.question_id} status='{self.processing_status}' audio_status='{self.audio_status}'>"
