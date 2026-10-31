from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Integer, Float, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class AnswerEvaluation(Base):
    __tablename__ = "answer_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    # Multi-dimensional scores (Content 80%, Delivery 20% experimental)
    content_score: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # WPM, pause count
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Detailed feedback and rubric breakdowns
    criterion_scores_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    feedback_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )  # strengths, gaps, suggestions
    evidence_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )  # cited pages/slides & quotes

    # AI Model Transparency (e.g. model name, prompt version, latency)
    model_metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    answer = relationship("Answer", back_populates="evaluation")

    def __repr__(self) -> str:
        return f"<AnswerEvaluation id={self.id} answer_id={self.answer_id} score={self.overall_score}>"
