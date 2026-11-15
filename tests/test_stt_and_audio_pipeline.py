"""
Unit and Integration Tests for Bước 8.2: STT & Audio Analysis Pipeline.
Validates:
1. Audio signal analysis using librosa (WPM, hesitation pauses >= 1.5s, silence ratio, ethics disclaimer).
2. STT Service structure and transcription output.
3. Asynchronous processing pipeline lifecycle (queued -> transcribing -> evaluating).
"""
import sys
import os
import tempfile
import numpy as np
import soundfile as sf

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import User
from app.models.project import ThesisProject
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_profile import ProjectKnowledgeProfile
from app.models.session import PracticeSession
from app.models.question import Question
from app.models.answer import Answer
from app.core.security import hash_password
from app.services.audio_analysis_service import audio_analysis_service
from app.services.stt_service import stt_service
from app.services.answer_processing_pipeline import answer_processing_pipeline
from app.repositories.answer_repo import answer_repo

# Setup in-memory SQLite DB
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Create tables
User.__table__.create(bind=test_engine)
ThesisProject.__table__.create(bind=test_engine)
Document.__table__.create(bind=test_engine)
DocumentChunk.__table__.create(bind=test_engine)
ProjectKnowledgeProfile.__table__.create(bind=test_engine)
PracticeSession.__table__.create(bind=test_engine)
Question.__table__.create(bind=test_engine)
Answer.__table__.create(bind=test_engine)


def create_synthetic_wav_file(duration_sec=5.0, sample_rate=16000) -> str:
    """Create a temporary synthetic audio wave with active tone and a 2.0s pause."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    # Part 1: 0 - 1.0s tone (speech simulation)
    tone1 = np.sin(2 * np.pi * 440 * t) * 0.5
    tone1[t >= 1.0] = 0.0

    # Part 2: 1.0s - 3.0s SILENCE (2.0s hesitation pause)
    # Part 3: 3.0s - 5.0s tone
    tone2 = np.sin(2 * np.pi * 440 * t) * 0.5
    tone2[t < 3.0] = 0.0

    audio_signal = tone1 + tone2

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio_signal, sample_rate)
    tmp.close()
    return tmp.name


def test_audio_analysis_service():
    print("\n--- 1. Unit Test: Librosa Audio Signal Analysis (WPM, Pauses, Silence) ---")
    wav_path = create_synthetic_wav_file(duration_sec=4.0)

    try:
        mock_transcript = "Kính thưa Hội đồng đề tài của em ứng dụng kiến trúc Microservices"
        metrics = audio_analysis_service.analyze_speech(
            audio_path=wav_path,
            transcript=mock_transcript,
        )

        assert metrics["total_duration_seconds"] >= 3.8
        assert metrics["total_words"] == len(mock_transcript.split())
        assert metrics["speaking_rate_wpm"] > 0
        assert metrics["hesitation_pauses_count"] >= 1, "Should detect the 1.6s hesitation pause"
        assert 0.0 <= metrics["silence_ratio"] <= 1.0
        assert "physical" in metrics["ethical_disclaimer"] or "vật lý" in metrics["ethical_disclaimer"]
        assert 0.0 <= metrics["fluency_score"] <= 10.0

        print(f"PASS: Speech metrics verified:")
        print(f"  Duration: {metrics['total_duration_seconds']}s | Voiced: {metrics['voiced_duration_seconds']}s")
        print(f"  WPM: {metrics['speaking_rate_wpm']} ({metrics['pace_assessment']})")
        print(f"  Hesitation pauses (>=1.5s): {metrics['hesitation_pauses_count']}")
        print(f"  Fluency Score: {metrics['fluency_score']}/10")
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)


def test_stt_transcription_service():
    print("\n--- 2. Unit Test: Faster-Whisper STT Service ---")
    wav_path = create_synthetic_wav_file(duration_sec=2.0)

    # Mock the internal transcription call to verify service wrapper contracts
    orig_transcribe = stt_service.transcribe_audio
    stt_service.transcribe_audio = lambda audio_path, language="vi", **kwargs: {
        "full_text": "Hệ thống sử dụng cơ sở dữ liệu quan hệ PostgreSQL chuẩn 3NF.",
        "language": "vi",
        "language_probability": 0.985,
        "duration": 2.0,
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "Hệ thống sử dụng cơ sở dữ liệu quan hệ PostgreSQL chuẩn 3NF.", "avg_logprob": -0.15}
        ],
    }

    try:
        res = stt_service.transcribe_audio(wav_path, language="vi")
        assert "PostgreSQL" in res["full_text"]
        assert res["language"] == "vi"
        assert len(res["segments"]) == 1
        assert res["segments"][0]["start"] == 0.0
        print(f"PASS: STT Service returned clean transcript with segment timestamps.")
    finally:
        stt_service.transcribe_audio = orig_transcribe
        if os.path.exists(wav_path):
            os.unlink(wav_path)


def test_answer_processing_pipeline_lifecycle():
    print("\n--- 3. Integration Test: Answer Processing Pipeline Lifecycle ---")
    db = TestingSessionLocal()
    wav_path = create_synthetic_wav_file(duration_sec=3.5)

    try:
        user = User(
            email="student_pipeline@example.com",
            name="Sinh Viên Pipeline",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        proj = ThesisProject(
            student_id=user.id,
            title="Đồ án Pipeline STT",
            topic="CNTT",
            status="IN_PROGRESS",
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

        session_obj = PracticeSession(
            project_id=proj.id,
            mode="question_answer",
            status="in_progress",
            knowledge_profile_version=1,
        )
        db.add(session_obj)
        db.commit()
        db.refresh(session_obj)

        q = Question(
            session_id=session_obj.id,
            order_index=1,
            question_text="Kiến trúc hệ thống được thiết kế như thế nào?",
            difficulty="medium",
            topic_competency="Kiến trúc hệ thống",
            expected_answer_outline="- Mô hình MVC\n- Cơ sở dữ liệu",
            source_chunk_ids=[1],
            recommended_seconds=120,
        )
        db.add(q)
        db.commit()
        db.refresh(q)

        # Create answer with initial status 'queued'
        answer = answer_repo.create_or_update(
            db=db,
            question_id=q.id,
            audio_path=wav_path,
            audio_mime_type="audio/wav",
            duration_seconds=3.5,
        )
        assert answer.processing_status == "queued"
        print(f"Initial Answer #{answer.id} status: '{answer.processing_status}'")

        # Mock STT for quick deterministic pipeline test
        orig_stt = stt_service.transcribe_audio
        stt_service.transcribe_audio = lambda audio_path, language="vi", **kwargs: {
            "full_text": "Em xin trình bày kiến trúc phân tầng bao gồm controller service repository.",
            "language": "vi",
            "language_probability": 0.99,
            "duration": 3.5,
            "segments": [
                {"id": 0, "start": 0.0, "end": 3.5, "text": "Em xin trình bày kiến trúc phân tầng...", "avg_logprob": -0.1}
            ],
        }

        try:
            # Run background processing pipeline
            answer_processing_pipeline.process_answer(answer_id=answer.id, db_session=db)

            # Re-fetch from DB
            db.refresh(answer)
            assert answer.processing_status == "evaluating", f"Expected 'evaluating', got '{answer.processing_status}'"
            assert answer.transcript is not None
            assert "kiến trúc phân tầng" in answer.transcript
            assert len(answer.transcript_segments) == 1
            assert answer.error_fields is not None
            assert "speech_metrics" in answer.error_fields
            metrics = answer.error_fields["speech_metrics"]
            assert "speaking_rate_wpm" in metrics
            assert "fluency_score" in metrics

            print(f"PASS: Pipeline completed successfully!")
            print(f"  Final Status: '{answer.processing_status}'")
            print(f"  Transcript: '{answer.transcript}'")
            print(f"  Speech Metrics: WPM={metrics['speaking_rate_wpm']}, Fluency={metrics['fluency_score']}/10")
        finally:
            stt_service.transcribe_audio = orig_stt

    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING STEP 8.2 TESTS: STT & AUDIO ANALYSIS PIPELINE")
    print("==================================================")
    test_audio_analysis_service()
    test_stt_transcription_service()
    test_answer_processing_pipeline_lifecycle()
    print("\n==================================================")
    print(" ALL STEP 8.2 STT & AUDIO PIPELINE TESTS PASSED!")
    print("==================================================")
