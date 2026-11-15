from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from app.models.answer import Answer


class AnswerRepository:
    """Repository managing Answer database records."""

    def create_or_update(
        self,
        db: Session,
        question_id: int,
        audio_path: str,
        audio_mime_type: str = "audio/webm",
        duration_seconds: Optional[float] = None,
    ) -> Answer:
        """
        Creates a new Answer record for a question or updates existing one
        if the student re-records their defense answer.
        """
        answer = db.query(Answer).filter(Answer.question_id == question_id).first()

        if answer:
            answer.audio_path = audio_path
            answer.audio_mime_type = audio_mime_type
            answer.duration_seconds = duration_seconds
            answer.processing_status = "queued"
            answer.audio_status = "active"
            answer.audio_purged_at = None
            answer.transcript = None
            answer.transcript_segments = None
            answer.error_fields = None
            answer.updated_at = datetime.utcnow()
        else:
            answer = Answer(
                question_id=question_id,
                audio_path=audio_path,
                audio_mime_type=audio_mime_type,
                duration_seconds=duration_seconds,
                processing_status="queued",
                audio_status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(answer)

        db.commit()
        db.refresh(answer)
        return answer

    def get_by_id(self, db: Session, answer_id: int) -> Optional[Answer]:
        return db.query(Answer).filter(Answer.id == answer_id).first()

    def get_by_question_id(self, db: Session, question_id: int) -> Optional[Answer]:
        return db.query(Answer).filter(Answer.question_id == question_id).first()

    def update_processing_status(
        self,
        db: Session,
        answer: Answer,
        status: str,
        error_fields: Optional[Dict[str, Any]] = None,
    ) -> Answer:
        answer.processing_status = status
        if error_fields:
            answer.error_fields = error_fields
        answer.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(answer)
        return answer

    def update_audio_status(
        self,
        db: Session,
        answer: Answer,
        audio_status: str,
        purged_at: Optional[datetime] = None,
    ) -> Answer:
        answer.audio_status = audio_status
        if purged_at:
            answer.audio_purged_at = purged_at
        answer.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(answer)
        return answer


answer_repo = AnswerRepository()

