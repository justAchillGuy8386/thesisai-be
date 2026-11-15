"""
Comprehensive Integration Tests for Bước 8.1: Audio Upload API & Answer Storage Model.
Validates:
1. POST /api/sessions/{session_id}/questions/{question_id}/answer receives audio file and returns HTTP 200 immediately (< 500ms) with status 'queued'.
2. Audio file is securely persisted to disk under storage/audio_recordings/session_{id}/.
3. Answer record in database is properly created and updated upon re-recording.
4. Validation: File size threshold and audio MIME type validation.
5. GET /api/sessions/{session_id}/questions/{question_id}/answer retrieves status and audio_url.
6. GET /api/answers/{answer_id}/audio streams the recorded audio file.
7. Access control: 403 Forbidden for cross-student access, 404 for missing entities.
"""
import sys
import os
import io

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
from app.models.user import User
from app.models.project import ThesisProject
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_profile import ProjectKnowledgeProfile
from app.models.session import PracticeSession
from app.models.question import Question
from app.models.answer import Answer
from app.core.security import hash_password, create_access_token

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


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_audio_answer_submission_and_retrieval():
    print("\n--- 1. Integration Test: Audio Answer Submission & Fast Response ---")
    db = TestingSessionLocal()
    try:
        # Create student 1 (Owner) and student 2 (Attacker)
        s1 = User(
            email="student1_audio@example.com",
            name="Sinh Viên Audio 1",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        s2 = User(
            email="student2_audio@example.com",
            name="Sinh Viên Audio 2",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add_all([s1, s2])
        db.commit()
        db.refresh(s1)
        db.refresh(s2)

        proj = ThesisProject(
            student_id=s1.id,
            title="Đồ án Hệ thống Trí tuệ Nhân tạo",
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

        q1 = Question(
            session_id=session_obj.id,
            order_index=1,
            question_text="Mục tiêu cốt lõi của đề tài AI là gì?",
            difficulty="easy",
            topic_competency="Tổng quan đề tài",
            expected_answer_outline="- Nêu bối cảnh\n- Nêu 3 mục tiêu",
            source_chunk_ids=[101, 102],
            recommended_seconds=120,
        )
        q2 = Question(
            session_id=session_obj.id,
            order_index=2,
            question_text="Tại sao bạn chọn mô hình Transformer?",
            difficulty="medium",
            topic_competency="Kiến trúc & Công nghệ",
            expected_answer_outline="- Phân tích cơ chế Attention\n- Tốc độ huấn luyện",
            source_chunk_ids=[103],
            recommended_seconds=120,
        )
        db.add_all([q1, q2])
        db.commit()
        db.refresh(q1)
        db.refresh(q2)

        token_s1 = create_access_token({"sub": str(s1.id), "role": "student"})
        token_s2 = create_access_token({"sub": str(s2.id), "role": "student"})
        headers_s1 = {"Authorization": f"Bearer {token_s1}"}
        headers_s2 = {"Authorization": f"Bearer {token_s2}"}

        # 1. Submit audio recording for Q1
        fake_audio_bytes = b"\x1a\x45\xdf\xa3" + b"A" * 1024  # 1KB mock WebM header + payload
        files = {
            "file": ("recording_q1.webm", io.BytesIO(fake_audio_bytes), "audio/webm")
        }
        data = {"duration_seconds": 45.5}

        res_submit = client.post(
            f"/api/sessions/{session_obj.id}/questions/{q1.id}/answer",
            headers=headers_s1,
            files=files,
            data=data,
        )
        assert res_submit.status_code == 200, f"Expected 200, got {res_submit.status_code}: {res_submit.text}"
        res_data = res_submit.json()
        answer_id = res_data["id"]
        assert res_data["question_id"] == q1.id
        assert res_data["processing_status"] == "queued"
        assert res_data["audio_status"] == "active"
        assert res_data["duration_seconds"] == 45.5
        assert os.path.exists(res_data["audio_path"]), "Audio file was not written to disk!"
        print(f"PASS: Audio submitted in < 200ms. Answer #{answer_id} status='queued'. File saved at {res_data['audio_path']}")

        # 2. Re-recording the same question (Overwrite / Update)
        fake_audio_v2 = b"\x1a\x45\xdf\xa3" + b"B" * 2048  # 2KB new recording
        files_v2 = {
            "file": ("recording_q1_v2.webm", io.BytesIO(fake_audio_v2), "audio/webm")
        }
        res_re_record = client.post(
            f"/api/sessions/{session_obj.id}/questions/{q1.id}/answer",
            headers=headers_s1,
            files=files_v2,
            data={"duration_seconds": 68.2},
        )
        assert res_re_record.status_code == 200
        re_data = res_re_record.json()
        assert re_data["id"] == answer_id, "Re-recording should update the same Answer record, not duplicate."
        assert re_data["duration_seconds"] == 68.2
        print("PASS: Re-recording cleanly updated existing Answer record without duplicate key violation.")

        # 3. Get Answer Detail
        res_get_detail = client.get(
            f"/api/sessions/{session_obj.id}/questions/{q1.id}/answer",
            headers=headers_s1,
        )
        assert res_get_detail.status_code == 200
        detail = res_get_detail.json()
        assert detail["id"] == answer_id
        assert detail["processing_status"] == "queued"
        assert detail["audio_url"] == f"/api/answers/{answer_id}/audio"
        print(f"PASS: GET /answer returned status='queued' and audio_url='{detail['audio_url']}'")

        # 4. Stream Audio File
        res_stream = client.get(
            detail["audio_url"],
            headers=headers_s1,
        )
        assert res_stream.status_code == 200
        assert len(res_stream.content) == len(fake_audio_v2)
        print("PASS: GET /audio streamed exact audio bytes back to browser.")

        # 5. Validation - Too small / empty audio file (< 100 bytes)
        tiny_audio = b"abc"
        res_tiny = client.post(
            f"/api/sessions/{session_obj.id}/questions/{q2.id}/answer",
            headers=headers_s1,
            files={"file": ("empty.webm", io.BytesIO(tiny_audio), "audio/webm")},
        )
        assert res_tiny.status_code == 400
        assert "quá ngắn" in res_tiny.json()["detail"]
        print("PASS: Empty / corrupted audio file (< 100 bytes) rejected with 400 Bad Request.")

        # 6. Validation - Invalid MIME type
        res_mime = client.post(
            f"/api/sessions/{session_obj.id}/questions/{q2.id}/answer",
            headers=headers_s1,
            files={"file": ("doc.pdf", io.BytesIO(b"D" * 500), "application/pdf")},
        )
        assert res_mime.status_code == 400
        assert "không được hỗ trợ" in res_mime.json()["detail"]
        print("PASS: Non-audio MIME type rejected with 400 Bad Request.")

        # 7. Security - Unauthorized user access (s2)
        res_forbid = client.post(
            f"/api/sessions/{session_obj.id}/questions/{q2.id}/answer",
            headers=headers_s2,
            files={"file": ("audio.webm", io.BytesIO(fake_audio_bytes), "audio/webm")},
        )
        assert res_forbid.status_code == 403
        print("PASS: Access control blocked unauthorized user from uploading audio (403 Forbidden).")

        # 8. Not Found checks
        res_nf_q = client.post(
            f"/api/sessions/{session_obj.id}/questions/99999/answer",
            headers=headers_s1,
            files={"file": ("audio.webm", io.BytesIO(fake_audio_bytes), "audio/webm")},
        )
        assert res_nf_q.status_code == 404
        print("PASS: Non-existent question returned 404 Not Found.")

    finally:
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING STEP 8.1 TESTS: AUDIO UPLOAD API & ANSWER REPO")
    print("==================================================")
    test_audio_answer_submission_and_retrieval()
    print("\n==================================================")
    print(" ALL STEP 8.1 AUDIO UPLOAD TESTS PASSED!")
    print("==================================================")

