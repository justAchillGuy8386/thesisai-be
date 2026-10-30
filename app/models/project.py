from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ThesisProject(Base):
    __tablename__ = "thesis_projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supervisor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="PLANNING", nullable=False
    )  # PLANNING, IN_PROGRESS, READY_FOR_DEFENSE, COMPLETED
    academic_year: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    student = relationship(
        "User",
        foreign_keys=[student_id],
        back_populates="projects",
    )
    supervisor = relationship(
        "User",
        foreign_keys=[supervisor_id],
        back_populates="supervised_projects",
    )

    def __repr__(self) -> str:
        return f"<ThesisProject id={self.id} title='{self.title[:30]}' status='{self.status}'>"
