"""
Comprehensive Unit & Integration tests for Thesis Project CRUD API (Phase 4, Step 4.1).
Uses an in-memory SQLite database with StaticPool and FastAPI TestClient with dependency overrides.
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
from app.core.security import hash_password, create_access_token

# Setup SQLite in-memory test DB with StaticPool to share state across all connections
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Create User, ThesisProject, Document tables in test SQLite
User.__table__.create(bind=test_engine)
ThesisProject.__table__.create(bind=test_engine)
Document.__table__.create(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def seed_data():
    db = TestingSessionLocal()
    # 1. Seed Student
    student = User(
        name="Nguyễn Văn A",
        email="student.test@hust.edu.vn",
        password_hash=hash_password("Pass123@"),
        role="student",
        is_active=True,
    )
    # 2. Seed Lecturer
    lecturer = User(
        name="TS. Trần Văn Hướng Dẫn",
        email="lecturer.test@hust.edu.vn",
        password_hash=hash_password("Pass123@"),
        role="lecturer",
        is_active=True,
    )
    # 3. Seed Another Student (for forbidden tests)
    other_student = User(
        name="Lê Thị B",
        email="other.student@hust.edu.vn",
        password_hash=hash_password("Pass123@"),
        role="student",
        is_active=True,
    )
    db.add_all([student, lecturer, other_student])
    db.commit()
    db.refresh(student)
    db.refresh(lecturer)
    db.refresh(other_student)

    # Generate auth tokens
    student_token = create_access_token(data={"sub": str(student.id), "email": student.email, "role": student.role})
    lecturer_token = create_access_token(data={"sub": str(lecturer.id), "email": lecturer.email, "role": lecturer.role})
    other_student_token = create_access_token(data={"sub": str(other_student.id), "email": other_student.email, "role": other_student.role})

    return {
        "student": student,
        "lecturer": lecturer,
        "other_student": other_student,
        "student_token": student_token,
        "lecturer_token": lecturer_token,
        "other_student_token": other_student_token,
    }


def run_tests():
    data = seed_data()
    student_headers = {"Authorization": f"Bearer {data['student_token']}"}
    lecturer_headers = {"Authorization": f"Bearer {data['lecturer_token']}"}
    other_headers = {"Authorization": f"Bearer {data['other_student_token']}"}

    print("--- 1. Test GET /api/projects/lecturers ---")
    res = client.get("/api/projects/lecturers", headers=student_headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    lecturers = res.json()
    assert len(lecturers) >= 1, "Expected at least 1 lecturer"
    assert lecturers[0]["name"] == "TS. Trần Văn Hướng Dẫn"
    print("PASS: /api/projects/lecturers returned available advisor list.")

    print("\n--- 2. Test GET /api/projects/my-project before creation ---")
    res = client.get("/api/projects/my-project", headers=student_headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    assert res.json() is None, "Expected None when student has no project"
    print("PASS: /api/projects/my-project returns null for fresh student.")

    print("\n--- 3. Test POST /api/projects as Student (Success) ---")
    payload = {
        "title": "Hệ thống AI hỗ trợ luyện tập bảo vệ đồ án tốt nghiệp",
        "topic": "Trí tuệ nhân tạo & Xử lý ngôn ngữ tự nhiên",
        "description": "Nghiên cứu kiến trúc Local RAG trên laptop 16GB và voice phản xạ STT/TTS",
        "academic_year": "2023-2024",
        "supervisor_id": data["lecturer"].id,
    }
    res = client.post("/api/projects", json=payload, headers=student_headers)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    created_proj = res.json()
    assert created_proj["id"] is not None
    assert created_proj["title"] == payload["title"]
    assert created_proj["status"] == "PLANNING"
    assert created_proj["student_name"] == "Nguyễn Văn A"
    assert created_proj["supervisor_name"] == "TS. Trần Văn Hướng Dẫn"
    assert created_proj["documents_count"] == 0
    project_id = created_proj["id"]
    print(f"PASS: Created project with ID: {project_id}, status: {created_proj['status']}.")

    print("\n--- 4. Test POST /api/projects with invalid supervisor ---")
    invalid_payload = {
        "title": "Đề tài lỗi supervisor",
        "supervisor_id": 99999,
    }
    res = client.post("/api/projects", json=invalid_payload, headers=student_headers)
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    print("PASS: Validation rejected non-existent supervisor_id.")

    print("\n--- 5. Test POST /api/projects as Lecturer (Forbidden) ---")
    res = client.post("/api/projects", json=payload, headers=lecturer_headers)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    print("PASS: Lecturer role cannot create student thesis project.")

    print("\n--- 6. Test GET /api/projects/my-project after creation ---")
    res = client.get("/api/projects/my-project", headers=student_headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    my_proj = res.json()
    assert my_proj["id"] == project_id
    assert my_proj["title"] == payload["title"]
    assert my_proj["supervisor_name"] == "TS. Trần Văn Hướng Dẫn"
    print("PASS: /api/projects/my-project retrieved the active project successfully.")

    print("\n--- 7. Test GET /api/projects/{id} access control ---")
    # Student owner
    res = client.get(f"/api/projects/{project_id}", headers=student_headers)
    assert res.status_code == 200
    # Assigned supervisor
    res = client.get(f"/api/projects/{project_id}", headers=lecturer_headers)
    assert res.status_code == 200
    # Other student (Forbidden)
    res = client.get(f"/api/projects/{project_id}", headers=other_headers)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    print("PASS: Proper RBAC & ownership enforcement on GET /api/projects/{id}.")

    print("\n--- 8. Test PATCH /api/projects/{id} update status ---")
    update_payload = {
        "status": "IN_PROGRESS",
        "description": "Cập nhật tiến độ: Đã hoàn thiện tài liệu đề cương và cấu trúc chương mục.",
    }
    res = client.patch(f"/api/projects/{project_id}", json=update_payload, headers=student_headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    updated_proj = res.json()
    assert updated_proj["status"] == "IN_PROGRESS"
    assert "Đã hoàn thiện" in updated_proj["description"]
    print(f"PASS: Project status updated to {updated_proj['status']}.")

    print("\n--- 9. Test PATCH with invalid status ---")
    invalid_status_payload = {"status": "INVALID_STATUS_TEST"}
    res = client.patch(f"/api/projects/{project_id}", json=invalid_status_payload, headers=student_headers)
    assert res.status_code == 422, f"Expected 422 (Pydantic validation), got {res.status_code}: {res.text}"
    print("PASS: Invalid project status rejected by schema validation.")

    print("\n==========================================")
    print(" ALL 9 STEP 4.1 INTEGRATION TESTS PASSED! ")
    print("==========================================")


if __name__ == "__main__":
    run_tests()
