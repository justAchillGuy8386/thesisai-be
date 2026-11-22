from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from app.models.session import PracticeSession
from app.models.question import Question


class SessionRepository:
    """Repository managing PracticeSession records."""

    def create(
        self,
        db: Session,
        project_id: int,
        mode: str = "question_answer",
        knowledge_profile_version: int = 1,
    ) -> PracticeSession:
        session = PracticeSession(
            project_id=project_id,
            mode=mode,
            status="in_progress",
            knowledge_profile_version=knowledge_profile_version,
            started_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def get_by_id(self, db: Session, session_id: int) -> Optional[PracticeSession]:
        return (
            db.query(PracticeSession)
            .options(
                joinedload(PracticeSession.questions).joinedload(Question.answer)
            )
            .filter(PracticeSession.id == session_id)
            .first()
        )

    def get_by_id_and_project(
        self, db: Session, session_id: int, project_id: int
    ) -> Optional[PracticeSession]:
        return (
            db.query(PracticeSession)
            .options(
                joinedload(PracticeSession.questions).joinedload(Question.answer)
            )
            .filter(
                PracticeSession.id == session_id,
                PracticeSession.project_id == project_id,
            )
            .first()
        )

    def list_by_project_id(
        self, db: Session, project_id: int, skip: int = 0, limit: int = 20
    ) -> List[PracticeSession]:
        return (
            db.query(PracticeSession)
            .options(
                joinedload(PracticeSession.questions).joinedload(Question.answer)
            )
            .filter(PracticeSession.project_id == project_id)
            .order_by(PracticeSession.started_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_by_project_id(self, db: Session, project_id: int) -> int:
        return db.query(PracticeSession).filter(PracticeSession.project_id == project_id).count()

    def get_session_number(
        self, db: Session, project_id: int, session_id: int
    ) -> int:
        """Calculate 1-based chronological index of the session for a project."""
        return (
            db.query(PracticeSession)
            .filter(
                PracticeSession.project_id == project_id,
                PracticeSession.id <= session_id,
            )
            .count()
        )

    def update_status(
        self, db: Session, session: PracticeSession, status: str
    ) -> PracticeSession:
        session.status = status
        if status in ("completed", "cancelled"):
            session.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(session)
        return session


session_repo = SessionRepository()
