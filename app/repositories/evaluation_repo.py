from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.evaluation import AnswerEvaluation


class EvaluationRepository:
    """Repository quản lý bảng answer_evaluations."""

    def create_or_update(
        self,
        db: Session,
        answer_id: int,
        overall_score: float,
        content_score: float,
        delivery_score: Optional[float] = None,
        criterion_scores_json: Optional[Dict[str, Any]] = None,
        feedback_json: Optional[Dict[str, Any]] = None,
        evidence_json: Optional[Dict[str, Any]] = None,
        model_metadata_json: Optional[Dict[str, Any]] = None,
    ) -> AnswerEvaluation:
        """
        Tạo mới hoặc cập nhật bản đánh giá câu trả lời (upsert).
        """
        evaluation = db.query(AnswerEvaluation).filter(AnswerEvaluation.answer_id == answer_id).first()

        criterion_scores = criterion_scores_json or {}
        feedback = feedback_json or {}
        evidence = evidence_json or {}
        model_metadata = model_metadata_json or {}

        if evaluation:
            evaluation.overall_score = overall_score
            evaluation.content_score = content_score
            evaluation.delivery_score = delivery_score
            evaluation.criterion_scores_json = criterion_scores
            evaluation.feedback_json = feedback
            evaluation.evidence_json = evidence
            evaluation.model_metadata_json = model_metadata
            evaluation.created_at = datetime.utcnow()
        else:
            evaluation = AnswerEvaluation(
                answer_id=answer_id,
                overall_score=overall_score,
                content_score=content_score,
                delivery_score=delivery_score,
                criterion_scores_json=criterion_scores,
                feedback_json=feedback,
                evidence_json=evidence,
                model_metadata_json=model_metadata,
                created_at=datetime.utcnow(),
            )
            db.add(evaluation)

        db.commit()
        db.refresh(evaluation)
        return evaluation

    def get_by_answer_id(self, db: Session, answer_id: int) -> Optional[AnswerEvaluation]:
        return db.query(AnswerEvaluation).filter(AnswerEvaluation.answer_id == answer_id).first()

    def get_by_id(self, db: Session, evaluation_id: int) -> Optional[AnswerEvaluation]:
        return db.query(AnswerEvaluation).filter(AnswerEvaluation.id == evaluation_id).first()

    def delete_by_answer_id(self, db: Session, answer_id: int) -> bool:
        evaluation = self.get_by_answer_id(db, answer_id)
        if evaluation:
            db.delete(evaluation)
            db.commit()
            return True
        return False


evaluation_repo = EvaluationRepository()

