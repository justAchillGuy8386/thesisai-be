from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Text, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)  # easy, medium, hard
    topic_competency: Mapped[str] = mapped_column(String(100), nullable=False)  # Architecture, Database, Security, etc.
    expected_answer_outline: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)  # Provenance grounding
    recommended_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    session = relationship("PracticeSession", back_populates="questions")
    answer = relationship(
        "Answer",
        back_populates="question",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Question id={self.id} order={self.order_index} difficulty='{self.difficulty}'>"
