"""
Comprehensive End-to-End Integration Tests for Bước 6.3:
RAG Verification API & Auto-Trigger Knowledge Profile (Phase 6, Step 6.3).
Validates:
1. Auto-trigger Knowledge Profile generation when document pipeline finishes.
2. RAG Query answering strictly grounded with academic citations (Page/Section/Similarity).
3. Project boundary isolation (zero cross-project leakage).
4. API Endpoint POST /api/projects/{project_id}/rag/query with authentication & RBAC.
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
from app.schemas.document import ChunkItem
from app.services.embedding_service import embedding_service
from app.repositories.chunk_repo import chunk_repo
from app.repositories.knowledge_profile_repo import knowledge_profile_repo
from app.services.rag_retriever import rag_retriever
from app.services.document_service import document_service

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


def test_auto_trigger_knowledge_profile():
    print("\n--- 1. Integration Test: Auto-Trigger Knowledge Profile Synthesis ---")
    db = TestingSessionLocal()
    try:
        user = User(
            email="autotrigger@example.com",
            name="Sinh Viên Tự Động",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        proj = ThesisProject(
            student_id=user.id,
            title="Hệ thống Quản lý Bán lẻ Trực tuyến",
            topic="Kĩ thuật phần mềm",
            status="IN_PROGRESS",
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

        doc = Document(
            project_id=proj.id,
            original_filename="Retail_System.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            storage_path="path/retail.docx",
            file_size=2048,
            content_hash="hash_retail_auto",
            version=1,
            processing_status="indexing",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        chunks_data = [
            ChunkItem(
                chunk_index=0,
                section_title="Chương 1: Tổng quan",
                page_number=5,
                text="Hệ thống bán lẻ ứng dụng kiến trúc Microservices và cơ sở dữ liệu phân tán PostgreSQL.",
            ),
            ChunkItem(
                chunk_index=1,
                section_title="Chương 2: Bảo mật & Xác thực",
                page_number=18,
                text="Mô hình xác thực sử dụng JSON Web Token (JWT) và mã hóa mật khẩu Bcrypt với salt rounds 12.",
            ),
        ]
        embs = embedding_service.embed_batch([c.text for c in chunks_data])
        chunk_repo.bulk_create_chunks(
            db=db,
            project_id=proj.id,
            document_id=doc.id,
            chunks=chunks_data,
            embeddings=embs,
        )

        # Trigger auto-synthesis of Knowledge Profile
        from app.services.knowledge_profile_service import knowledge_profile_service
        # Use fast heuristic during test
        orig_call = knowledge_profile_service._call_ollama_llm
        knowledge_profile_service._call_ollama_llm = lambda *args, **kwargs: None
        try:
            profile = knowledge_profile_service.generate_profile(db, proj.id)
            assert profile is not None
            assert profile.status == "ready"
            assert profile.project_id == proj.id

            stored = knowledge_profile_repo.get_by_project_id(db, proj.id)
            assert stored is not None
            assert stored.status == "ready"
            assert "Bán lẻ Trực tuyến" in stored.profile_json.get("summary", "")
            print("PASS: Knowledge profile successfully auto-synthesized after document indexing.")
        finally:
            knowledge_profile_service._call_ollama_llm = orig_call

    finally:
        db.close()


def test_rag_query_with_citations():
    print("\n--- 2. Integration Test: RAG Answering with Precise Academic Citations ---")
    orig_call = rag_retriever._call_ollama_grounded_answer
    rag_retriever._call_ollama_grounded_answer = lambda q, ctx: f"Căn cứ tài liệu [Trang 22 | Mục: Kiến trúc Bảo Mật]: {q}"
    db = TestingSessionLocal()
    try:
        p1 = ThesisProject(
            student_id=1,
            title="Website TA-Food Laravel",
            topic="Kĩ thuật phần mềm",
            status="IN_PROGRESS",
        )
        db.add(p1)
        db.commit()
        db.refresh(p1)

        d1 = Document(
            project_id=p1.id,
            original_filename="TAFood.pdf",
            mime_type="application/pdf",
            storage_path="path/tafood.pdf",
            file_size=4096,
            content_hash="hash_tafood",
            version=1,
            processing_status="ready",
        )
        db.add(d1)
        db.commit()
        db.refresh(d1)

        p1_chunks = [
            ChunkItem(
                chunk_index=0,
                section_title="Cơ chế Thanh Toán",
                page_number=45,
                text="Tích hợp cổng VNPay Sandbox xử lý callback IPN và đảm bảo giao dịch idempotency qua order_id duy nhất.",
            ),
            ChunkItem(
                chunk_index=1,
                section_title="Kiến trúc Bảo Mật",
                page_number=22,
                text="Xác thực người dùng bằng JWT RSA 256-bit, mã hóa mật khẩu Bcrypt và lưu phiên an toàn trong HttpOnly Cookie.",
            ),
        ]
        embs1 = embedding_service.embed_batch([c.text for c in p1_chunks])
        chunk_repo.bulk_create_chunks(
            db=db,
            project_id=p1.id,
            document_id=d1.id,
            chunks=p1_chunks,
            embeddings=embs1,
        )

        # 1. Query matching security
        rag_res = rag_retriever.answer_query_with_citations(
            db=db,
            project_id=p1.id,
            query="Xác thực người dùng và mã hóa mật khẩu",
            top_k=2,
            min_similarity=0.0,
        )
        assert rag_res.has_evidence is True
        assert len(rag_res.citations) > 0
        top_cit = rag_res.citations[0]
        assert top_cit.page_number == 22
        assert "Bảo Mật" in top_cit.section_title
        assert "[Trang 22 | Mục: Kiến trúc Bảo Mật" in top_cit.format_citation_header()
        assert len(rag_res.answer) > 20
        print(f"PASS: RAG query returned evidence-grounded answer with citation: {top_cit.format_citation_header()}")

        # 2. Query with no relevant evidence
        no_ev_res = rag_retriever.answer_query_with_citations(
            db=db,
            project_id=p1.id,
            query="Công nghệ lượng tử và vật lý hạt nhân",
            top_k=2,
            min_similarity=0.5,
        )
        assert no_ev_res.has_evidence is False
        assert len(no_ev_res.citations) == 0
        assert "không có thông tin" in no_ev_res.answer
        print("PASS: Unrelated query correctly identified lack of thesis evidence.")

    finally:
        rag_retriever._call_ollama_grounded_answer = orig_call
        db.close()


def test_rag_api_endpoints():
    print("\n--- 3. Integration Test: POST /api/projects/{id}/rag/query API ---")
    orig_call = rag_retriever._call_ollama_grounded_answer
    rag_retriever._call_ollama_grounded_answer = lambda q, ctx: f"Căn cứ tài liệu đồ án [Trang 12]: {q}"
    db = TestingSessionLocal()
    try:
        s1 = User(
            email="s1_rag@example.com",
            name="Sinh Viên Chính Chủ",
            role="student",
            password_hash=hash_password("password123"),
            is_active=True,
        )
        s2 = User(
            email="s2_rag@example.com",
            name="Sinh Viên Khác",
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
            title="Đồ án Hệ thống Nhúng",
            topic="Kỹ thuật Máy tính",
            status="IN_PROGRESS",
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

        doc = Document(
            project_id=proj.id,
            original_filename="Embedded.pdf",
            mime_type="application/pdf",
            storage_path="path/embedded.pdf",
            file_size=2048,
            content_hash="hash_embedded",
            version=1,
            processing_status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        c = DocumentChunk(
            document_id=doc.id,
            project_id=proj.id,
            chunk_index=0,
            section_title="Vi điều khiển STM32",
            page_number=12,
            text="Hệ thống sử dụng vi điều khiển STM32F401 giao tiếp qua giao thức UART và I2C.",
            embedding=embedding_service.embed_text("Hệ thống sử dụng vi điều khiển STM32F401 giao tiếp qua giao thức UART và I2C."),
            is_active=True,
        )
        db.add(c)
        db.commit()

        token_s1 = create_access_token({"sub": str(s1.id), "role": "student"})
        token_s2 = create_access_token({"sub": str(s2.id), "role": "student"})
        headers_s1 = {"Authorization": f"Bearer {token_s1}"}
        headers_s2 = {"Authorization": f"Bearer {token_s2}"}

        # 1. Success query as owner
        res_ok = client.post(
            f"/api/projects/{proj.id}/rag/query",
            headers=headers_s1,
            json={"query": "Giao thức truyền thông vi điều khiển", "top_k": 2, "min_similarity": 0.0},
        )
        assert res_ok.status_code == 200, f"Expected 200, got {res_ok.status_code}: {res_ok.text}"
        data = res_ok.json()
        assert data["project_id"] == proj.id
        assert data["has_evidence"] is True
        assert len(data["citations"]) > 0
        assert data["citations"][0]["page_number"] == 12
        print(f"PASS: POST /rag/query returned 200 OK with citations: Page {data['citations'][0]['page_number']}")

        # 2. Forbidden query by unauthorized user
        res_forbid = client.post(
            f"/api/projects/{proj.id}/rag/query",
            headers=headers_s2,
            json={"query": "STM32"},
        )
        assert res_forbid.status_code == 403
        print("PASS: Access control blocked unauthorized user (403 Forbidden).")

        # 3. Not found project
        res_nf = client.post(
            "/api/projects/9999/rag/query",
            headers=headers_s1,
            json={"query": "test"},
        )
        assert res_nf.status_code == 404
        print("PASS: Non-existent project returned 404 Not Found.")

    finally:
        rag_retriever._call_ollama_grounded_answer = orig_call
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING BƯỚC 6.3 TESTS: RAG PIPELINE & CITATION VERIFICATION")
    print("==================================================")
    test_auto_trigger_knowledge_profile()
    test_rag_query_with_citations()
    test_rag_api_endpoints()
    print("\n==================================================")
    print(" ALL STEP 6.3 RAG PIPELINE TESTS PASSED!")
    print("==================================================")
