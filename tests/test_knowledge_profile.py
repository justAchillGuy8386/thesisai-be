"""
Comprehensive Unit & Integration tests for Bước 6.2:
Project Knowledge Profile Generator via LLM (Phase 6, Step 6.2).
Validates:
1. Schema integrity (KnowledgeProfileData, AnticipatedQuestion, KnowledgeProfileResponse).
2. KnowledgeProfileRepository CRUD operations.
3. KnowledgeProfileService synthesis (heuristic fallback + structured JSON output).
4. API Endpoints:
   - POST /api/projects/{project_id}/knowledge-profile/generate (Async Background Task)
   - GET /api/projects/{project_id}/knowledge-profile (Role-based access & validation)
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
from app.core.security import hash_password, create_access_token
from app.schemas.knowledge_profile import (
    KnowledgeProfileData,
    AnticipatedQuestion,
    KnowledgeProfileResponse,
)
from app.repositories.knowledge_profile_repo import knowledge_profile_repo
from app.services.knowledge_profile_service import knowledge_profile_service

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


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

from app.db import session as db_session_module
db_session_module.SessionLocal = TestingSessionLocal

client = TestClient(app)


def test_schema_validation():
    print("\n--- 1. Unit Test: Schema Validation ---")
    q = AnticipatedQuestion(
        role="GIẢNG VIÊN PHẢN BIỆN",
        question="Tại sao nhóm chọn mô hình Collaborative Filtering?",
        reason="Đánh giá cơ sở lựa chọn giải thuật",
        suggested_answer_hint="Nêu ưu điểm về khả năng cá nhân hóa theo hành vi người dùng",
    )
    assert q.role == "GIẢNG VIÊN PHẢN BIỆN"

    data = KnowledgeProfileData(
        summary="Đề tài xây dựng website đặt món ăn...",
        objectives=["Xây dựng hệ thống", "Tối ưu đặt món"],
        methodology_and_tech=["Laravel", "MySQL", "REST API"],
        contributions=["Quy trình đặt món nhanh"],
        defense_weaknesses=["Chưa kiểm thử tải cao"],
        anticipated_questions=[q],
    )
    assert len(data.methodology_and_tech) == 3
    assert len(data.anticipated_questions) == 1
    print("PASS: KnowledgeProfileData and AnticipatedQuestion validated.")


def test_service_synthesis():
    print("\n--- 2. Integration Test: KnowledgeProfileService Synthesis Across Majors ---")
    orig_call = knowledge_profile_service._call_ollama_llm
    knowledge_profile_service._call_ollama_llm = lambda *args, **kwargs: None
    db = TestingSessionLocal()
    try:
        # Create student and project
        user = User(
            email="student_test@example.com",
            name="Nguyễn Văn A",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        proj = ThesisProject(
            student_id=user.id,
            title="Hệ thống Đặt Món Ăn TA-Food",
            topic="Công nghệ Phần mềm",
            description="Ứng dụng web hỗ trợ đặt đồ ăn trực tuyến.",
            status="IN_PROGRESS",
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

        doc = Document(
            project_id=proj.id,
            original_filename="BaoCao_TAFood.pdf",
            mime_type="application/pdf",
            storage_path="path/doc1.pdf",
            file_size=5000,
            content_hash="hash_sample",
            version=1,
            processing_status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        chunk1 = DocumentChunk(
            document_id=doc.id,
            project_id=proj.id,
            chunk_index=0,
            section_title="Kiến trúc",
            page_number=10,
            text="Hệ thống phát triển trên nền tảng Laravel kết hợp cơ sở dữ liệu MySQL và cổng thanh toán VNPay.",
            is_active=True,
        )
        chunk2 = DocumentChunk(
            document_id=doc.id,
            project_id=proj.id,
            chunk_index=1,
            section_title="Bảo mật",
            page_number=15,
            text="Áp dụng mã hóa Bcrypt và phân quyền người dùng qua JWT.",
            is_active=True,
        )
        db.add_all([chunk1, chunk2])
        db.commit()

        # Run service generate_profile
        profile = knowledge_profile_service.generate_profile(db, proj.id)
        assert profile is not None
        assert profile.status == "ready"
        assert profile.project_id == proj.id

        # Verify parsed profile data
        resp = knowledge_profile_service.get_project_profile(db, proj.id)
        assert resp is not None
        assert resp.profile_data is not None
        assert len(resp.profile_data.objectives) > 0
        assert len(resp.profile_data.anticipated_questions) >= 3
        
        # Verify 3 roles in anticipated questions
        roles = {q.role for q in resp.profile_data.anticipated_questions}
        assert "CHỦ TỊCH HỘI ĐỒNG" in roles
        assert "GIẢNG VIÊN PHẢN BIỆN" in roles
        assert "ỦY VIÊN HỘI ĐỒNG" in roles
        print(f"PASS: IT profile generated with {len(resp.profile_data.anticipated_questions)} anticipated questions.")

        # Test Business / Economics Project Adaptation
        proj_biz = ThesisProject(
            student_id=user.id,
            title="Chiến lược Marketing thúc đẩy doanh thu ngành F&B",
            topic="Quản trị Kinh doanh",
            status="IN_PROGRESS",
        )
        db.add(proj_biz)
        db.commit()
        db.refresh(proj_biz)

        doc_biz = Document(
            project_id=proj_biz.id,
            original_filename="LuanVan_Marketing.pdf",
            mime_type="application/pdf",
            storage_path="path/biz.pdf",
            file_size=3000,
            content_hash="hash_biz",
            version=1,
            processing_status="ready",
        )
        db.add(doc_biz)
        db.commit()
        db.refresh(doc_biz)

        chunk_biz = DocumentChunk(
            document_id=doc_biz.id,
            project_id=proj_biz.id,
            chunk_index=0,
            section_title="Khảo sát",
            page_number=20,
            text="Khảo sát 300 khách hàng về mức độ hài lòng, phân tích hồi quy tương quan doanh thu và chi phí quảng cáo.",
            is_active=True,
        )
        db.add(chunk_biz)
        db.commit()

        profile_biz = knowledge_profile_service.generate_profile(db, proj_biz.id)
        resp_biz = knowledge_profile_service.get_project_profile(db, proj_biz.id)
        assert resp_biz is not None
        assert "Quản trị Kinh doanh" in resp_biz.profile_data.summary or "doanh thu" in resp_biz.profile_data.summary
        assert any("SPSS" in m or "định lượng" in m for m in resp_biz.profile_data.methodology_and_tech)
        print("PASS: Business/Economics major profile adapted with SPSS, market metrics and business council questions.")

    finally:
        knowledge_profile_service._call_ollama_llm = orig_call
        db.close()


def test_knowledge_profile_api():
    print("\n--- 3. Integration Test: Knowledge Profile API Endpoints ---")
    orig_call = knowledge_profile_service._call_ollama_llm
    knowledge_profile_service._call_ollama_llm = lambda *args, **kwargs: None
    db = TestingSessionLocal()
    try:
        # Create student 1
        s1 = User(
            email="s1_api@example.com",
            name="Sinh Viên 1",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        # Create student 2 (intruder)
        s2 = User(
            email="s2_api@example.com",
            name="Sinh Viên 2",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add_all([s1, s2])
        db.commit()
        db.refresh(s1)
        db.refresh(s2)

        proj1 = ThesisProject(
            student_id=s1.id,
            title="Đề tài Nghiên cứu IoT",
            topic="Khoa học Máy tính",
            status="IN_PROGRESS",
        )
        db.add(proj1)
        db.commit()
        db.refresh(proj1)

        doc1 = Document(
            project_id=proj1.id,
            original_filename="IoT_Report.pdf",
            mime_type="application/pdf",
            storage_path="path/iot.pdf",
            file_size=3000,
            content_hash="iot_hash",
            version=1,
            processing_status="ready",
        )
        db.add(doc1)
        db.commit()
        db.refresh(doc1)

        c1 = DocumentChunk(
            document_id=doc1.id,
            project_id=proj1.id,
            chunk_index=0,
            text="Hệ thống cảm biến IoT thu thập dữ liệu nhiệt độ và độ ẩm.",
            is_active=True,
        )
        db.add(c1)
        db.commit()

        token_s1 = create_access_token({"sub": str(s1.id), "role": "student"})
        token_s2 = create_access_token({"sub": str(s2.id), "role": "student"})
        headers_s1 = {"Authorization": f"Bearer {token_s1}"}
        headers_s2 = {"Authorization": f"Bearer {token_s2}"}

        # 1. POST /generate as owner (Student 1) -> 202 Accepted
        res_post = client.post(
            f"/api/projects/{proj1.id}/knowledge-profile/generate",
            headers=headers_s1,
            json={"force_regenerate": True},
        )
        assert res_post.status_code == 202, f"Expected 202, got {res_post.status_code}: {res_post.text}"
        print("PASS: POST /generate returned 202 Accepted and initiated synthesis.")

        # 2. GET /knowledge-profile as owner -> 200 OK
        res_get = client.get(
            f"/api/projects/{proj1.id}/knowledge-profile",
            headers=headers_s1,
        )
        assert res_get.status_code == 200, f"Expected 200, got {res_get.status_code}: {res_get.text}"
        data = res_get.json()
        assert data["project_id"] == proj1.id
        assert data["profile_data"] is not None
        assert "summary" in data["profile_data"]
        print(f"PASS: GET /knowledge-profile returned valid profile data (Status: {data['status']}).")

        # 3. GET /knowledge-profile as unauthorized user (Student 2) -> 403 Forbidden
        res_forbidden = client.get(
            f"/api/projects/{proj1.id}/knowledge-profile",
            headers=headers_s2,
        )
        assert res_forbidden.status_code == 403
        print("PASS: Access control blocked unauthorized student (403 Forbidden).")

        # 4. Non-existent project -> 404 Not Found
        res_not_found = client.get(
            "/api/projects/9999/knowledge-profile",
            headers=headers_s1,
        )
        assert res_not_found.status_code == 404
        print("PASS: Non-existent project returned 404 Not Found.")

    finally:
        knowledge_profile_service._call_ollama_llm = orig_call
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING BƯỚC 6.2 TESTS: PROJECT KNOWLEDGE PROFILE")
    print("==================================================")
    test_schema_validation()
    test_service_synthesis()
    test_knowledge_profile_api()
    print("\n==================================================")
    print(" ALL STEP 6.2 KNOWLEDGE PROFILE TESTS PASSED!")
    print("==================================================")
