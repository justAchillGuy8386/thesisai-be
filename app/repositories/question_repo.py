from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.question import Question
from app.schemas.question import GeneratedQuestionItem


class QuestionRepository:
    """Repository managing Question records associated with PracticeSessions."""

    def bulk_create(
        self,
        db: Session,
        session_id: int,
        items: List[GeneratedQuestionItem],
    ) -> List[Question]:
        questions = []
        for item in items:
            diff_val = item.difficulty.value if hasattr(item.difficulty, "value") else str(item.difficulty)
            q = Question(
                session_id=session_id,
                order_index=item.order_index,
                question_text=item.question_text,
                difficulty=diff_val,
                topic_competency=item.topic_competency,
                expected_answer_outline=item.expected_answer_outline,
                source_chunk_ids=item.source_chunk_ids,
                recommended_seconds=item.recommended_seconds,
            )
            db.add(q)
            questions.append(q)
        db.commit()
        for q in questions:
            db.refresh(q)
        return questions

    def get_by_id(self, db: Session, question_id: int) -> Optional[Question]:
        return db.query(Question).filter(Question.id == question_id).first()

    def list_by_session_id(self, db: Session, session_id: int) -> List[Question]:
        return (
            db.query(Question)
            .filter(Question.session_id == session_id)
            .order_by(Question.order_index.asc())
            .all()
        )


question_repo = QuestionRepository()

