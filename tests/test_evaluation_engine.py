"""
Unit and Integration Tests for Bước 8.3: LLM Evaluation Engine & Privacy Lifecycle.
Validates:
1. Multi-dimensional Rubric Scoring (80% Content + 20% Delivery).
2. AnswerEvaluation schemas and repository upsert & retrieval.
3. Speech delivery metrics integration (WPM pacing, hesitation pauses).
4. Local Ollama LLM evaluation with resilient Heuristic Fallback.
5. End-to-end background pipeline completion (queued -> transcribing -> evaluating -> completed).
6. Privacy-by-Design lifecycle: Audio purging with 100% transcript & evaluation preservation.
7. REST API endpoints for evaluation retrieval, re-evaluation, and audio purge.
"""
import sys
import os
import tempfile
import datetime
from unittest.mock import patch, MagicMock

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.user import User
from app.models.project import ThesisProject
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_profile import ProjectKnowledgeProfile
from app.models.session import PracticeSession
from app.models.question import Question
from app.models.answer import Answer
from app.models.evaluation import AnswerEvaluation
from app.core.security import hash_password, create_access_token
from app.schemas.evaluation import AnswerEvaluationResponse, CriterionScoresDetail, FeedbackDetail
from app.repositories.evaluation_repo import evaluation_repo
from app.repositories.answer_repo import answer_repo
from app.services.evaluation_service import evaluation_service
from app.services.audio_privacy_service import audio_privacy_service
from app.services.answer_processing_pipeline import answer_processing_pipeline
from app.api.deps import get_db
from app.main import app

# Setup in-memory SQLite DB
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Create all relevant tables
User.__table__.create(bind=test_engine)
ThesisProject.__table__.create(bind=test_engine)
Document.__table__.create(bind=test_engine)
DocumentChunk.__table__.create(bind=test_engine)
ProjectKnowledgeProfile.__table__.create(bind=test_engine)
PracticeSession.__table__.create(bind=test_engine)
Question.__table__.create(bind=test_engine)
Answer.__table__.create(bind=test_engine)
AnswerEvaluation.__table__.create(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_1_evaluation_repo_and_schemas():
    """Unit Test: Evaluation Repository upsert, get, and Pydantic validation."""
    print("\n--- 1. Unit Test: Evaluation Repository & Schemas ---")
    db = TestingSessionLocal()

    # Create dummy answer
    ans = Answer(
        question_id=999,
        processing_status="completed",
        audio_status="active",
        transcript="Em xin trình bày kiến trúc phân tầng 3 lớp.",
    )
    db.add(ans)
    db.commit()
    db.refresh(ans)

    # Upsert evaluation
    eval_rec = evaluation_repo.create_or_update(
        db=db,
        answer_id=ans.id,
        overall_score=8.5,
        content_score=8.8,
        delivery_score=7.2,
        criterion_scores_json={
            "technical_accuracy": 9.0,
            "completeness": 8.5,
            "reasoning_defense": 8.8,
            "speech_pace": 7.0,
            "fluency": 7.4,
        },
        feedback_json={
            "strengths": ["Nắm chắc kiến trúc phân tầng", "Lập luận mạch lạc"],
            "weaknesses": ["Chưa nói rõ cơ chế xử lý ngoại lệ giữa các tầng"],
            "suggestions": ["Bổ sung sơ đồ tương tác giữa DTO và Entity"],
            "model_answer": "Kiến trúc gồm Controller, Service và Repository phân định rõ trách nhiệm...",
        },
        evidence_json={"cited_chunk_ids": [10, 12], "matched_keywords": ["controller", "service", "repository"]},
        model_metadata_json={"model": "qwen2.5:7b", "evaluation_latency_seconds": 2.15, "is_fallback": False},
    )

    assert eval_rec.id is not None
    assert eval_rec.answer_id == ans.id
    assert eval_rec.overall_score == 8.5
    assert eval_rec.content_score == 8.8
    assert eval_rec.delivery_score == 7.2
    assert "technical_accuracy" in eval_rec.criterion_scores_json

    # Test retrieval
    retrieved = evaluation_repo.get_by_answer_id(db, ans.id)
    assert retrieved is not None
    assert retrieved.id == eval_rec.id

    # Test Pydantic validation
    response_dto = AnswerEvaluationResponse.model_validate(retrieved)
    assert response_dto.overall_score == 8.5
    assert response_dto.criterion_scores["technical_accuracy"] == 9.0
    assert len(response_dto.feedback["strengths"]) == 2

    # Test update (upsert)
    updated = evaluation_repo.create_or_update(
        db=db,
        answer_id=ans.id,
        overall_score=9.0,
        content_score=9.2,
        delivery_score=8.0,
    )
    assert updated.id == eval_rec.id
    assert updated.overall_score == 9.0

    db.close()
    print("PASS: Evaluation repository and schemas verified with 100% accuracy.")


def test_2_speech_delivery_and_heuristic_fallback():
    """Unit Test: Delivery score calculation and heuristic fallback evaluation."""
    print("\n--- 2. Unit Test: Speech Delivery Scoring & Heuristic Fallback ---")
    db = TestingSessionLocal()

    # 1. Delivery score testing
    score_fast, _ = evaluation_service._calculate_delivery_score({"speaking_rate_wpm": 220, "fluency_score": 6.0})
    score_ideal, _ = evaluation_service._calculate_delivery_score({"speaking_rate_wpm": 145, "fluency_score": 9.0})
    score_slow, _ = evaluation_service._calculate_delivery_score({"speaking_rate_wpm": 75, "fluency_score": 5.0})

    assert score_ideal > score_fast
    assert score_ideal > score_slow
    assert 9.0 <= score_ideal <= 10.0
    print(f"PASS: Delivery scoring: Ideal WPM (145) = {score_ideal}/10 | Fast WPM (220) = {score_fast}/10 | Slow WPM (75) = {score_slow}/10")

    # 2. Heuristic fallback testing
    q = Question(
        session_id=1,
        order_index=1,
        question_text="Tại sao bạn chọn kiến trúc Microservices thay vì Monolith?",
        topic_competency="Architecture",
        expected_answer_outline="Độc lập triển khai, khả năng mở rộng từng service (scalability), cô lập lỗi (fault isolation), tuy nhiên đánh đổi độ phức tạp mạng và dữ liệu phân tán.",
        source_chunk_ids=[],
        recommended_seconds=120,
    )
    student_answer = (
        "Em chọn Microservices vì nó giúp hệ thống mở rộng linh hoạt theo từng dịch vụ, "
        "khi một service gặp sự cố thì các service khác vẫn hoạt động bình thường nhờ cô lập lỗi. "
        "Tuy nhiên nhược điểm là phức tạp hơn về mặt mạng và dữ liệu phân tán."
    )

    fallback_eval = evaluation_service._heuristic_fallback_evaluation(q, student_answer)
    assert fallback_eval["is_fallback"] is True
    assert fallback_eval["technical_accuracy"] >= 7.0
    assert fallback_eval["completeness"] >= 7.0
    assert len(fallback_eval["strengths"]) >= 1
    assert len(fallback_eval["weaknesses"]) >= 1
    assert len(fallback_eval["suggestions"]) >= 1
    print(f"PASS: Heuristic Fallback generated constructive feedback and scores: Tech={fallback_eval['technical_accuracy']}, Comp={fallback_eval['completeness']}")

    # 3. Empty transcript testing
    ans_empty = Answer(
        question_id=1001,
        processing_status="evaluating",
        transcript="",
        error_fields={"speech_metrics": {"speaking_rate_wpm": 0, "fluency_score": 2.0}},
    )
    db.add(ans_empty)
    q_empty = Question(
        session_id=1,
        order_index=2,
        question_text="Giải thích JWT authentication",
        topic_competency="Security",
        expected_answer_outline="Stateless token, signature verification, expiration",
        source_chunk_ids=[],
        recommended_seconds=120,
    )
    db.add(q_empty)
    db.commit()
    db.refresh(ans_empty)
    db.refresh(q_empty)
    ans_empty.question_id = q_empty.id
    db.commit()

    empty_eval = evaluation_service.evaluate_answer(db, ans_empty.id)
    assert empty_eval.content_score == 0.0
    assert "Không phát hiện thấy phát biểu" in empty_eval.feedback_json["weaknesses"][0]
    print("PASS: Empty transcript handled gracefully with zero content score and guidance message.")

    db.close()


def test_3_privacy_lifecycle_audio_purge():
    """Unit & Integration Test: Privacy-by-Design Audio Purge Lifecycle."""
    print("\n--- 3. Integration Test: Privacy-by-Design Audio Purging ---")
    db = TestingSessionLocal()

    # Create a temporary audio file
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    tmp_audio.write(b"AUDIO_DATA_FOR_PRIVACY_TESTING_123456789")
    tmp_audio.close()
    audio_path = tmp_audio.name
    assert os.path.exists(audio_path)

    # Create answer record with active audio
    ans = Answer(
        question_id=2001,
        audio_path=audio_path,
        audio_mime_type="audio/webm",
        duration_seconds=12.5,
        transcript="Em đã hoàn thành phần phân tích yêu cầu phi chức năng.",
        processing_status="completed",
        audio_status="active",
        created_at=datetime.datetime.utcnow() - datetime.timedelta(hours=25),  # expired > 24h
    )
    db.add(ans)
    db.commit()
    db.refresh(ans)

    # Attach an evaluation
    eval_rec = evaluation_repo.create_or_update(
        db=db,
        answer_id=ans.id,
        overall_score=8.0,
        content_score=8.0,
        delivery_score=8.0,
    )

    # Purge expired audios (> 24 hours)
    purged_count = audio_privacy_service.purge_expired_audio_recordings(db, retention_hours=24)
    assert purged_count >= 1

    # Verify physical file is unlinked
    assert not os.path.exists(audio_path)

    # Verify DB state
    db.refresh(ans)
    assert ans.audio_path is None
    assert ans.audio_status == "purged"
    assert ans.audio_purged_at is not None

    # CRITICAL: Verify transcript and evaluation remain 100% intact for student review!
    assert ans.transcript == "Em đã hoàn thành phần phân tích yêu cầu phi chức năng."
    eval_after = evaluation_repo.get_by_answer_id(db, ans.id)
    assert eval_after is not None
    assert eval_after.overall_score == 8.0

    print("PASS: Audio file securely destroyed on disk. Transcript and evaluation preserved 100% intact.")
    db.close()


def test_4_full_pipeline_end_to_end():
    """Integration Test: Full Pipeline queued -> transcribing -> evaluating -> completed."""
    print("\n--- 4. Integration Test: Full End-to-End Processing Pipeline ---")
    db = TestingSessionLocal()

    # Create temporary audio
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    # 2 seconds simple tone
    import numpy as np
    import soundfile as sf
    t = np.linspace(0, 2.0, int(16000 * 2.0), endpoint=False)
    tone = np.sin(2 * np.pi * 440 * t) * 0.3
    sf.write(tmp_audio.name, tone, 16000)
    tmp_audio.close()

    # Setup User, Project, Session, Question
    user = User(
        email="student_pipeline@test.com",
        password_hash=hash_password("password123"),
        name="Nguyễn Văn Sinh Viên",
        role="student",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    project = ThesisProject(
        student_id=user.id,
        title="Hệ thống chấm thi trực tuyến an toàn",
        topic="Software Engineering & Security",
        status="active",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    session_obj = PracticeSession(
        project_id=project.id,
        mode="question_answer",
        status="in_progress",
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    question = Question(
        session_id=session_obj.id,
        order_index=1,
        question_text="Cơ chế phòng chống gian lận trong hệ thống được thiết kế như thế nào?",
        difficulty="hard",
        topic_competency="Security",
        expected_answer_outline="Giám sát camera AI phát hiện nhiều khuôn mặt, khoá trình duyệt fullscreen, mã hóa gói tin bài nộp bằng chữ ký số RSA.",
        source_chunk_ids=[],
        recommended_seconds=120,
    )
    db.add(question)
    db.commit()
    db.refresh(question)

    answer = Answer(
        question_id=question.id,
        audio_path=tmp_audio.name,
        audio_mime_type="audio/wav",
        duration_seconds=2.0,
        processing_status="queued",
        audio_status="active",
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    # Mock STT to return structured transcript so test doesn't depend on microphone voice
    with patch.object(
        answer_processing_pipeline,
        "process_answer",
        wraps=answer_processing_pipeline.process_answer,
    ):
        with patch(
            "app.services.answer_processing_pipeline.stt_service.transcribe_audio",
            return_value={
                "full_text": "Hệ thống sử dụng AI nhận diện khuôn mặt qua webcam, kết hợp khoá toàn màn hình trình duyệt và mã hoá bài thi bằng chữ ký RSA.",
                "segments": [{"start": 0.0, "end": 2.0, "text": "Hệ thống sử dụng AI nhận diện khuôn mặt..."}],
                "duration": 2.0,
            },
        ):
            # Run pipeline
            answer_processing_pipeline.process_answer(answer_id=answer.id, db_session=db)

    # Verify pipeline results
    db.refresh(answer)
    assert answer.processing_status == "completed", f"Expected 'completed', got '{answer.processing_status}'"
    assert answer.transcript is not None
    assert "chữ ký RSA" in answer.transcript

    # Verify AnswerEvaluation was automatically generated and saved
    evaluation = evaluation_repo.get_by_answer_id(db, answer.id)
    assert evaluation is not None
    assert evaluation.overall_score >= 5.0
    assert evaluation.content_score >= 5.0
    assert evaluation.delivery_score >= 5.0
    assert "technical_accuracy" in evaluation.criterion_scores_json
    assert len(evaluation.feedback_json.get("strengths", [])) >= 1

    print(f"PASS: Pipeline completed successfully: Status='completed' | Overall Score={evaluation.overall_score}/10 (Content={evaluation.content_score}, Delivery={evaluation.delivery_score})")

    # Clean up temp file
    if os.path.exists(tmp_audio.name):
        os.remove(tmp_audio.name)
    db.close()


def test_5_api_endpoints():
    """Integration Test: REST API endpoints for Evaluation & Privacy."""
    print("\n--- 5. Integration Test: Evaluation & Privacy API Endpoints ---")
    db = TestingSessionLocal()

    # User & auth token
    user = User(
        email="api_test_student@test.com",
        password_hash=hash_password("secret123"),
        name="Trần Thị Lan",
        role="student",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "role": user.role})
    headers = {"Authorization": f"Bearer {token}"}

    project = ThesisProject(
        student_id=user.id,
        title="Ứng dụng RAG hỏi đáp đồ án",
        topic="AI & NLP",
        status="active",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    session_obj = PracticeSession(
        project_id=project.id,
        mode="question_answer",
        status="in_progress",
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    question = Question(
        session_id=session_obj.id,
        order_index=1,
        question_text="Trình bày giải pháp chống ảo giác (hallucination) trong RAG?",
        difficulty="medium",
        topic_competency="RAG Architecture",
        expected_answer_outline="Reranking bằng Cross-Encoder, kiểm tra provenance trích dẫn tài liệu, thiết lập ngưỡng cosine similarity chặt chẽ.",
        source_chunk_ids=[],
        recommended_seconds=120,
    )
    db.add(question)
    db.commit()
    db.refresh(question)

    tmp_file = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    tmp_file.write(b"SAMPLE_AUDIO_BYTES_TEST")
    tmp_file.close()

    answer = Answer(
        question_id=question.id,
        audio_path=tmp_file.name,
        audio_mime_type="audio/webm",
        duration_seconds=15.0,
        transcript="Để chống ảo giác, em dùng kỹ thuật reranking và đối chiếu trích dẫn nguồn gốc chunk tài liệu.",
        processing_status="completed",
        audio_status="active",
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    # 1. Test GET evaluation before evaluation exists -> 404 or 202
    resp = client.get(f"/api/sessions/{session_obj.id}/questions/{question.id}/evaluation", headers=headers)
    assert resp.status_code == 404

    # Create evaluation
    eval_rec = evaluation_repo.create_or_update(
        db=db,
        answer_id=answer.id,
        overall_score=8.7,
        content_score=9.0,
        delivery_score=7.5,
        criterion_scores_json={"technical_accuracy": 9.0, "completeness": 9.0, "reasoning_defense": 9.0},
        feedback_json={"strengths": ["Nắm chắc RAG"], "weaknesses": [], "suggestions": [], "model_answer": "Model answer"},
    )

    # 2. Test GET evaluation -> 200 OK
    resp = client.get(f"/api/sessions/{session_obj.id}/questions/{question.id}/evaluation", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_score"] == 8.7
    assert data["content_score"] == 9.0
    assert data["delivery_score"] == 7.5
    assert data["criterion_scores"]["technical_accuracy"] == 9.0
    print("PASS: GET /sessions/{session_id}/questions/{question_id}/evaluation returned HTTP 200 with full Rubric details.")

    # 3. Test POST reevaluate
    resp_reeval = client.post(f"/api/sessions/{session_obj.id}/questions/{question.id}/evaluation/reevaluate", headers=headers)
    assert resp_reeval.status_code == 200
    reeval_data = resp_reeval.json()
    assert "overall_score" in reeval_data
    print("PASS: POST /sessions/{session_id}/questions/{question_id}/evaluation/reevaluate returned HTTP 200 with re-evaluated scores.")

    # 4. Test POST purge-audio
    assert os.path.exists(tmp_file.name)
    resp_purge = client.post(f"/api/sessions/{session_obj.id}/questions/{question.id}/purge-audio", headers=headers)
    assert resp_purge.status_code == 200
    assert not os.path.exists(tmp_file.name)
    db.refresh(answer)
    assert answer.audio_status == "purged"
    print("PASS: POST /sessions/{session_id}/questions/{question_id}/purge-audio successfully deleted physical audio and updated status.")

    # 5. Test POST /privacy/purge-expired-audios
    resp_maint = client.post("/api/privacy/purge-expired-audios", headers=headers)
    assert resp_maint.status_code == 200
    assert "purged_count" in resp_maint.json()
    print("PASS: POST /privacy/purge-expired-audios maintenance endpoint executed successfully.")

    db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING STEP 8.3 TESTS: LLM EVALUATION ENGINE & PRIVACY")
    print("=" * 60)
    test_1_evaluation_repo_and_schemas()
    test_2_speech_delivery_and_heuristic_fallback()
    test_3_privacy_lifecycle_audio_purge()
    test_4_full_pipeline_end_to_end()
    test_5_api_endpoints()
    print("\n" + "=" * 60)
    print(" ALL STEP 8.3 EVALUATION & PRIVACY TESTS PASSED! ")
    print("=" * 60)
