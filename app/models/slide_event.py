from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class PresentationSlideEvent(Base):
    __tablename__ = "presentation_slide_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(50), default="slide_change", nullable=False
    )  # slide_change, pause, resume
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)  # Time offset from session start

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    session = relationship("PracticeSession", back_populates="slide_events")

    def __repr__(self) -> str:
        return f"<PresentationSlideEvent id={self.id} session_id={self.session_id} slide={self.slide_index} event='{self.event_type}'>"
