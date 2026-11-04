"""
Comprehensive Integration & Unit tests for Document Upload & Extraction (Phase 5, Step 5.1).
Tests PDF, DOCX, PPTX parsing, versioning, duplicate detection, and REST endpoints.
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
from app.core.security import hash_password, create_access_token
from app.services.document_extractor import document_extractor
from app.storage import storage_provider

# Setup SQLite in-memory test DB with StaticPool
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


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def create_sample_pdf() -> bytes:
    """Create a minimal valid PDF in memory using pypdf."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def create_sample_docx() -> bytes:
    """Create a valid DOCX with headings and body text using python-docx."""
    import docx
    doc = docx.Document()
    doc.add_heading("Chương 1: Tổng quan đề tài", level=1)
    doc.add_paragraph("Nghiên cứu về mô hình học máy và ứng dụng trong phản biện đồ án tốt nghiệp.")
    doc.add_heading("Chương 2: Phương pháp nghiên cứu", level=1)
    doc.add_paragraph("Sử dụng kiến trúc Local RAG với HNSW index và faster-whisper.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def create_sample_pptx() -> bytes:
    """Create a valid PPTX with slide titles and bullet points using python-pptx."""
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Báo cáo Đồ án Tốt nghiệp ThesisAI"
    slide.placeholders[1].text = "Học viên: Nguyễn Văn A - Lớp K65"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def seed_data():
    db = TestingSessionLocal()
    student = User(
        name="Nguyễn Văn A",
        email="student.doc@hust.edu.vn",
        password_hash=hash_password("Pass123@"),
        role="student",
        is_active=True,
    )
    other_student = User(
        name="Trần Thị B",
        email="other.doc@hust.edu.vn",
        password_hash=hash_password("Pass123@"),
        role="student",
        is_active=True,
    )
    db.add_all([student, other_student])
    db.commit()
    db.refresh(student)
    db.refresh(other_student)

    project = ThesisProject(
        student_id=student.id,
        title="Đồ án AI phản biện",
        topic="Khoa học máy tính",
        status="IN_PROGRESS",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    student_token = create_access_token(data={"sub": str(student.id), "email": student.email, "role": student.role})
    other_token = create_access_token(data={"sub": str(other_student.id), "email": other_student.email, "role": other_student.role})

    return {
        "student": student,
        "other_student": other_student,
        "project": project,
        "student_token": student_token,
        "other_token": other_token,
    }


def run_tests():
    data = seed_data()
    project_id = data["project"].id
    student_headers = {"Authorization": f"Bearer {data['student_token']}"}
    other_headers = {"Authorization": f"Bearer {data['other_token']}"}

    print("--- 1. Test Document Extractor on DOCX ---")
    docx_bytes = create_sample_docx()
    temp_docx_path = storage_provider.save_file(docx_bytes, "uploads/documents", "docx")
    abs_docx = storage_provider.get_file_path(temp_docx_path)
    extracted_docx = document_extractor.extract(abs_docx, "thesis.docx")
    assert len(extracted_docx) >= 2, f"Expected at least 2 sections in docx, got {len(extracted_docx)}"
    assert "Tổng quan" in extracted_docx[0].section_title
    print(f"PASS: Extracted {len(extracted_docx)} sections from DOCX successfully.")

    print("\n--- 2. Test Document Extractor on PPTX ---")
    pptx_bytes = create_sample_pptx()
    temp_pptx_path = storage_provider.save_file(pptx_bytes, "uploads/documents", "pptx")
    abs_pptx = storage_provider.get_file_path(temp_pptx_path)
    extracted_pptx = document_extractor.extract(abs_pptx, "presentation.pptx")
    assert len(extracted_pptx) == 1
    assert "ThesisAI" in extracted_pptx[0].section_title or "ThesisAI" in extracted_pptx[0].text
    print("PASS: Extracted slide from PPTX successfully.")

    print("\n--- 3. Test POST /upload PDF document (Version 1) ---")
    pdf_bytes = create_sample_pdf()
    files = {"file": ("thesis_v1.pdf", pdf_bytes, "application/pdf")}
    res = client.post(f"/api/projects/{project_id}/documents/upload", files=files, headers=student_headers)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    doc1 = res.json()
    assert doc1["id"] is not None
    assert doc1["original_filename"] == "thesis_v1.pdf"
    assert doc1["version"] == 1
    assert doc1["is_archived"] is False
    assert doc1["processing_status"] == "uploaded"
    doc1_id = doc1["id"]
    print(f"PASS: Uploaded PDF version 1 (ID: {doc1_id}).")

    print("\n--- 4. Test POST /upload duplicate file (Rejected) ---")
    files_dup = {"file": ("thesis_v1.pdf", pdf_bytes, "application/pdf")}
    res = client.post(f"/api/projects/{project_id}/documents/upload", files=files_dup, headers=student_headers)
    assert res.status_code == 400, f"Expected 400 for duplicate, got {res.status_code}: {res.text}"
    assert "giống hệt" in res.json()["detail"]
    print("PASS: Duplicate content hash rejected properly.")

    print("\n--- 5. Test POST /upload DOCX document (Version 2 & Auto-archive v1) ---")
    files2 = {"file": ("thesis_v2.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = client.post(f"/api/projects/{project_id}/documents/upload", files=files2, headers=student_headers)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    doc2 = res.json()
    assert doc2["version"] == 2
    assert doc2["is_archived"] is False
    doc2_id = doc2["id"]
    print(f"PASS: Uploaded DOCX version 2 (ID: {doc2_id}).")

    print("\n--- 6. Test GET /documents list and verify auto-archiving ---")
    res = client.get(f"/api/projects/{project_id}/documents", headers=student_headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data_list = res.json()
    assert data_list["total"] == 2
    assert data_list["active_version"] == 2
    # Verify doc1 is now archived
    v1_doc = next(d for d in data_list["documents"] if d["id"] == doc1_id)
    v2_doc = next(d for d in data_list["documents"] if d["id"] == doc2_id)
    assert v1_doc["is_archived"] is True
    assert v2_doc["is_archived"] is False
    print("PASS: Document list confirms v2 is active and v1 is archived.")

    print("\n--- 7. Test Access Control: other student cannot upload or delete ---")
    files_other = {"file": ("hack.pdf", pdf_bytes, "application/pdf")}
    res = client.post(f"/api/projects/{project_id}/documents/upload", files=files_other, headers=other_headers)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    res = client.delete(f"/api/projects/{project_id}/documents/{doc1_id}", headers=other_headers)
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    print("PASS: Access control blocks unauthorized students.")

    print("\n--- 8. Test Invalid file extension rejection ---")
    files_invalid = {"file": ("malware.exe", b"fake binary", "application/octet-stream")}
    res = client.post(f"/api/projects/{project_id}/documents/upload", files=files_invalid, headers=student_headers)
    assert res.status_code == 400
    assert "không được hỗ trợ" in res.json()["detail"]
    print("PASS: Invalid file extension rejected.")

    print("\n--- 9. Test DELETE /documents/{id} ---")
    res = client.delete(f"/api/projects/{project_id}/documents/{doc1_id}", headers=student_headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    # Verify doc1 is gone
    res = client.get(f"/api/projects/{project_id}/documents", headers=student_headers)
    assert res.json()["total"] == 1
    print("PASS: Deleted document successfully.")

    print("\n==========================================")
    print(" ALL 9 STEP 5.1 INTEGRATION TESTS PASSED! ")
    print("==========================================")


if __name__ == "__main__":
    run_tests()
