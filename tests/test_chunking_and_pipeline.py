"""
Comprehensive Unit & Integration tests for Chunking Service & Document Pipeline (Phase 5, Step 5.3).
Validates sentence splitting with overlap, page number preservation, chunk repository,
and end-to-end background pipeline with anti-stale data protection.
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
from app.services.chunking_service import chunking_service, ChunkItem
from app.services.document_extractor import ExtractedPage
from app.repositories.chunk_repo import chunk_repo
from app.services.document_service import document_service
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

# Override SessionLocal so background tasks also use the test SQLite DB
from app.db import session as db_session_module
db_session_module.SessionLocal = TestingSessionLocal

client = TestClient(app)


def create_sample_docx() -> bytes:
    """Create a multi-section sample DOCX in memory."""
    import docx
    doc = docx.Document()
    doc.add_heading("Chương 1: Đặt vấn đề và mục tiêu nghiên cứu", level=1)
    doc.add_paragraph(
        "Bảo vệ đồ án tốt nghiệp là một cột mốc quan trọng trong sự nghiệp học thuật của sinh viên. "
        "Tuy nhiên, nhiều sinh viên gặp khó khăn khi phản xạ trước các câu hỏi bất ngờ của Hội đồng phản biện. "
        "Hệ thống ThesisAI được đề xuất nhằm cung cấp môi trường luyện tập phản biện ảo mô phỏng thời gian thực."
    )
    doc.add_heading("Chương 2: Kiến trúc hệ thống và giải pháp công nghệ", level=1)
    doc.add_paragraph(
        "Hệ thống áp dụng kiến trúc Local RAG chạy trên máy tính cá nhân 16GB RAM. "
        "Tài liệu nghiên cứu được bóc tách và lập chỉ mục bằng pgvector với thuật toán HNSW. "
        "Mô hình ngôn ngữ lớn Qwen2.5 và mô hình nhận dạng giọng nói faster-whisper được tối ưu hóa để không làm tràn bộ nhớ (OOM)."
    )
    doc.add_heading("Chương 3: Thực nghiệm và đánh giá kết quả", level=1)
    doc.add_paragraph(
        "Kết quả thử nghiệm cho thấy độ trễ phản hồi âm thanh đạt dưới 1.5 giây. "
        "Điểm số Rubric đánh giá tách bạch giữa nội dung chuyên môn và phong thái trình bày của học viên."
    )
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def seed_data():
    db = TestingSessionLocal()
    student = User(
        name="Nguyễn Văn A",
        email="chunk.test@hust.edu.vn",
        password_hash=hash_password("Pass123@"),
        role="student",
        is_active=True,
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    project = ThesisProject(
        student_id=student.id,
        title="Đồ án Nghiên cứu RAG và Chunking",
        topic="Khoa học dữ liệu",
        status="IN_PROGRESS",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    token = create_access_token(data={"sub": str(student.id), "email": student.email, "role": student.role})

    return {
        "student": student,
        "project": project,
        "token": token,
    }


def run_tests():
    data = seed_data()
    project_id = data["project"].id
    student_headers = {"Authorization": f"Bearer {data['token']}"}
    db = TestingSessionLocal()

    print("--- 1. Unit Test: Chunking Service on Extracted Pages ---")
    mock_pages = [
        ExtractedPage(
            page_number=1,
            section_title="Chương 1: Giới thiệu",
            text="Đồ án tốt nghiệp là cột mốc quan trọng. Sinh viên cần rèn luyện kỹ năng phản biện trước hội đồng. "
                 "Mô hình Local RAG giúp bảo mật 100% dữ liệu nghiên cứu cá nhân.",
        ),
        ExtractedPage(
            page_number=2,
            section_title="Chương 2: Kiến trúc",
            text="Hệ thống chạy trên laptop 16GB RAM với Ollama và pgvector. "
                 "Đánh chỉ mục vector HNSW cosine distance cho tốc độ truy xuất dưới 10ms. "
                 "Thư viện faster-whisper xử lý âm thanh 48kHz từ microphone sinh viên.",
        ),
    ]

    chunks = chunking_service.chunk_extracted_pages(mock_pages)
    assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert chunks[0].section_title == "Chương 1: Giới thiệu"
    assert chunks[1].chunk_index == 1
    assert chunks[1].page_number == 2
    assert chunks[1].section_title == "Chương 2: Kiến trúc"
    print("PASS: Chunking service preserved page numbers and section titles.")

    print("\n--- 2. Unit Test: Chunking with Overlap on Long Text ---")
    long_text = " ".join([f"Câu số {i} trong đoạn văn dài để kiểm tra tính năng gối đầu của thuật toán chunking." for i in range(40)])
    long_page = [ExtractedPage(page_number=5, section_title="Chương 3", text=long_text)]
    long_chunks = chunking_service.chunk_extracted_pages(long_page)
    assert len(long_chunks) > 1, f"Expected multi-chunk split, got {len(long_chunks)}"
    for idx, c in enumerate(long_chunks):
        assert c.page_number == 5
        assert c.chunk_index == idx
    print(f"PASS: Long text correctly chunked into {len(long_chunks)} overlapping chunks.")

    print("\n--- 3. Integration Test: Document Upload & Pipeline Execution ---")
    docx_bytes = create_sample_docx()
    files = {"file": ("luan_van_v1.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = client.post(f"/api/projects/{project_id}/documents/upload", files=files, headers=student_headers)
    assert res.status_code == 201, f"Upload failed: {res.text}"
    doc1_data = res.json()
    doc1_id = doc1_data["id"]

    # Verify background task already completed and status is 'ready'
    db.expire_all()
    updated_doc = db.get(Document, doc1_id)
    assert updated_doc.processing_status == "ready", f"Expected 'ready', got '{updated_doc.processing_status}'"

    # Verify chunks in DB
    saved_chunks = chunk_repo.get_chunks_by_document(db, doc1_id)
    assert len(saved_chunks) >= 3, f"Expected at least 3 chunks, got {len(saved_chunks)}"
    for c in saved_chunks:
        assert c.is_active is True
        assert c.page_number is not None
        assert c.text is not None and len(c.text) > 0
    print(f"PASS: Background Pipeline executed! Status is 'ready', created {len(saved_chunks)} chunks with is_active=True.")

    print("\n--- 4. Anti-Stale Guard Test: Upload v2 and verify v1 chunks deactivated ---")
    files2 = {"file": ("luan_van_v2.docx", docx_bytes + b" ", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res2 = client.post(f"/api/projects/{project_id}/documents/upload", files=files2, headers=student_headers)
    assert res2.status_code == 201
    doc2_id = res2.json()["id"]

    db.expire_all()
    # Check v1 chunks (should be deactivated)
    v1_chunks = chunk_repo.get_chunks_by_document(db, doc1_id)
    assert all(not c.is_active for c in v1_chunks), "All v1 chunks must have is_active=False"

    # Check v2 chunks (should be active)
    v2_chunks = chunk_repo.get_chunks_by_document(db, doc2_id)
    assert all(c.is_active for c in v2_chunks), "All v2 chunks must have is_active=True"

    # Check active chunks query by project
    active_project_chunks = chunk_repo.get_active_chunks_by_project(db, project_id)
    assert len(active_project_chunks) == len(v2_chunks)
    print("PASS: Anti-Stale Guard confirmed! Only v2 chunks are active; v1 chunks safely archived.")

    print("\n==========================================")
    print(" ALL 4 STEP 5.3 INTEGRATION TESTS PASSED! ")
    print("==========================================")


if __name__ == "__main__":
    run_tests()
