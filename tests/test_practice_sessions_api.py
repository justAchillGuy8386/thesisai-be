"""
Comprehensive Integration Tests for Bước 7.2: Practice Session API & Repository.
Validates:
1. POST /api/projects/{project_id}/practice/sessions creates session and auto-generates 12 questions.
2. GET /api/projects/{project_id}/practice/sessions returns session history with counts.
3. GET /api/practice/sessions/{session_id} returns session detail with full question outlines and citations.
4. PATCH /api/practice/sessions/{session_id}/status updates session status (e.g. completed).
5. Authorization checks: 403 Forbidden for cross-student access, 404 Not Found for missing projects.
"""
import sys
import os

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
from app.schemas.document import ChunkItem
from app.schemas.knowledge_profile import KnowledgeProfileData
from app.repositories.chunk_repo import chunk_repo
from app.services.question_generator import question_generator_service

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


def test_practice_session_lifecycle():
    print("\n--- 1. Integration Test: Full Practice Session Lifecycle (Create -> List -> Detail -> Status) ---")
    db = TestingSessionLocal()
    orig_call = question_generator_service._call_ollama_generate_questions
    # Use deterministic heuristic generator for testing speed
    question_generator_service._call_ollama_generate_questions = lambda *args, **kwargs: []

    try:
        # Create student 1 (Owner)
        s1 = User(
            email="owner@student.edu.vn",
            name="Sinh Viên Chủ Sở Hữu",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        # Create student 2 (Attacker)
        s2 = User(
            email="attacker@student.edu.vn",
            name="Sinh Viên Khác",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add_all([s1, s2])
        db.commit()
        db.refresh(s1)
        db.refresh(s2)

        # Create project for s1
        project = ThesisProject(
            student_id=s1.id,
            title="Hệ thống Thương mại Điện tử Đa nền tảng",
            topic="Kỹ thuật phần mềm",
            status="IN_PROGRESS",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        # Create document and chunks
        doc = Document(
            project_id=project.id,
            original_filename="Ecommerce_Spec.pdf",
            mime_type="application/pdf",
            storage_path="path/ecommerce.pdf",
            file_size=5120,
            content_hash="hash_ecom_72",
            version=1,
            processing_status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        chunks_data = [
            ChunkItem(
                chunk_index=0,
                section_title="Chương 1: Tổng quan",
                page_number=1,
                text="Hệ thống thương mại điện tử giải quyết bài toán đặt hàng và thanh toán nhanh chóng.",
            ),
            ChunkItem(
                chunk_index=1,
                section_title="Chương 2: Kiến trúc",
                page_number=10,
                text="Kiến trúc ứng dụng phân tầng Spring Boot và Next.js kết hợp cơ sở dữ liệu PostgreSQL.",
            ),
            ChunkItem(
                chunk_index=2,
                section_title="Chương 3: Bảo mật",
                page_number=25,
                text="Bảo mật bằng JWT token và mã hóa dữ liệu thanh toán chuẩn PCI-DSS.",
            ),
        ]
        embs = [[0.05 * (i + j) for j in range(1024)] for i in range(len(chunks_data))]
        chunk_repo.bulk_create_chunks(
            db=db,
            project_id=project.id,
            document_id=doc.id,
            chunks=chunks_data,
            embeddings=embs,
        )

        # Create Knowledge Profile
        profile_content = KnowledgeProfileData(
            summary="Đề tài sàn thương mại điện tử Spring Boot và Next.js.",
            objectives=["Xây dựng cổng thanh toán", "Tối ưu hóa tìm kiếm sản phẩm"],
            methodology_and_tech=["Spring Boot", "Next.js", "PostgreSQL", "JWT"],
            contributions=["Tích hợp thanh toán an toàn"],
            defense_weaknesses=["Chưa kiểm thử tải cao"],
            anticipated_questions=[],
        )
        prof = ProjectKnowledgeProfile(
            project_id=project.id,
            version=1,
            profile_json=profile_content.model_dump(),
            source_document_ids=[doc.id],
            status="ready",
        )
        db.add(prof)
        db.commit()

        token_s1 = create_access_token({"sub": str(s1.id), "role": "student"})
        token_s2 = create_access_token({"sub": str(s2.id), "role": "student"})
        headers_s1 = {"Authorization": f"Bearer {token_s1}"}
        headers_s2 = {"Authorization": f"Bearer {token_s2}"}

        # Step 1: Create practice session as owner
        res_create = client.post(
            f"/api/projects/{project.id}/practice/sessions",
            headers=headers_s1,
            json={"mode": "question_answer", "target_questions": 12},
        )
        assert res_create.status_code == 201, f"Failed to create session: {res_create.text}"
        data_create = res_create.json()
        session_id = data_create["id"]
        assert data_create["project_id"] == project.id
        assert data_create["mode"] == "question_answer"
        assert data_create["status"] == "in_progress"
        assert len(data_create["questions"]) == 12
        assert data_create["questions"][0]["order_index"] == 1
        assert len(data_create["questions"][0]["expected_answer_outline"]) > 0
        print(f"PASS: Session #{session_id} created with {len(data_create['questions'])} questions.")

        # Step 2: List sessions for project
        res_list = client.get(
            f"/api/projects/{project.id}/practice/sessions",
            headers=headers_s1,
        )
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert len(list_data) == 1
        assert list_data[0]["id"] == session_id
        assert list_data[0]["total_questions"] == 12
        assert list_data[0]["answered_questions"] == 0
        print(f"PASS: GET /projects/{project.id}/practice/sessions returned {len(list_data)} session(s).")

        # Step 3: Get session detail
        res_detail = client.get(
            f"/api/practice/sessions/{session_id}",
            headers=headers_s1,
        )
        assert res_detail.status_code == 200
        detail_data = res_detail.json()
        assert detail_data["id"] == session_id
        assert len(detail_data["questions"]) == 12
        assert detail_data["questions"][0]["is_answered"] is False
        print("PASS: GET /practice/sessions/{id} returned full session detail and questions.")

        # Step 4: Update session status to 'completed'
        res_status = client.patch(
            f"/api/practice/sessions/{session_id}/status",
            headers=headers_s1,
            json={"status": "completed"},
        )
        assert res_status.status_code == 200
        status_data = res_status.json()
        assert status_data["status"] == "completed"
        assert status_data["ended_at"] is not None
        print("PASS: PATCH /practice/sessions/{id}/status successfully marked session as completed.")

        # Step 5: Test Security - Unauthorized user access (s2)
        res_forbid_create = client.post(
            f"/api/projects/{project.id}/practice/sessions",
            headers=headers_s2,
            json={"mode": "question_answer", "target_questions": 12},
        )
        assert res_forbid_create.status_code == 403
        print("PASS: Access control blocked unauthorized session creation (403 Forbidden).")

        res_forbid_get = client.get(
            f"/api/practice/sessions/{session_id}",
            headers=headers_s2,
        )
        assert res_forbid_get.status_code == 403
        print("PASS: Access control blocked unauthorized session detail view (403 Forbidden).")

        # Step 6: Test 404 for non-existent session
        res_nf = client.get(
            "/api/practice/sessions/99999",
            headers=headers_s1,
        )
        assert res_nf.status_code == 404
        print("PASS: Non-existent session returned 404 Not Found.")

    finally:
        question_generator_service._call_ollama_generate_questions = orig_call
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING STEP 7.2 TESTS: PRACTICE SESSION API & REPO")
    print("==================================================")
    test_practice_session_lifecycle()
    print("\n==================================================")
    print(" ALL STEP 7.2 PRACTICE SESSION TESTS PASSED!")
    print("==================================================")
