"""
Comprehensive Unit & Integration Tests for Bước 6.1:
Vector Embedding Service & Scoped RAG Retrieval (Phase 6, Step 6.1).
Validates:
1. EmbeddingService dimension (1024), batching, and normalization.
2. Chunk vector persistence in database.
3. RagRetriever semantic search with Cosine distance.
4. Strict Project Boundary Isolation (project_id filter).
5. Anti-Stale Guard (is_active = True filter).
6. Citation formatting for Council LLM prompts.
"""
import sys
import os
import math

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import User
from app.models.project import ThesisProject
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.schemas.document import ChunkItem
from app.services.embedding_service import embedding_service
from app.repositories.chunk_repo import chunk_repo
from app.services.rag_retriever import rag_retriever, RetrievedChunk

# Setup in-memory SQLite DB
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

User.__table__.create(bind=test_engine)
ThesisProject.__table__.create(bind=test_engine)
Document.__table__.create(bind=test_engine)
DocumentChunk.__table__.create(bind=test_engine)


def test_embedding_service_unit():
    print("\n--- 1. Unit Test: EmbeddingService (1024-dim & Normalization) ---")
    
    # 1. Test single embedding
    text = "Kiến trúc hệ thống đặt món ăn trực tuyến với công nghệ FastAPI và Next.js"
    emb = embedding_service.embed_text(text)
    
    assert isinstance(emb, list), "Embedding should be a list of floats"
    assert len(emb) == 1024, f"Expected 1024 dimensions, got {len(emb)}"
    
    # Verify L2 normalization: sum of squares ≈ 1.0
    norm = math.sqrt(sum(x * x for x in emb))
    assert abs(norm - 1.0) < 0.05, f"Vector should be unit normalized, got norm={norm}"
    print(f"PASS: embed_text produced {len(emb)}-dimensional normalized vector (norm={norm:.4f}).")

    # 2. Test batch embedding
    texts = [
        "Chương 1: Tổng quan đề tài",
        "Chương 2: Cơ sở lý thuyết",
        "Chương 3: Thiết kế hệ thống",
    ]
    batch_embs = embedding_service.embed_batch(texts, batch_size=2)
    assert len(batch_embs) == len(texts), f"Expected {len(texts)} embeddings, got {len(batch_embs)}"
    for e in batch_embs:
        assert len(e) == 1024, "All batch items must have 1024 dimensions"
    print(f"PASS: embed_batch successfully processed {len(batch_embs)} texts in batches.")

    # 3. Test empty input
    assert embedding_service.embed_batch([]) == [], "Empty input should return empty list"
    print("PASS: Empty input handled correctly.")


def test_chunk_repo_vector_storage():
    print("\n--- 2. Integration Test: Chunk Vector Storage & Persistence ---")
    db = TestingSessionLocal()
    try:
        # Create test project and document
        proj = ThesisProject(
            student_id=1,
            title="Đồ án Web TA-Food",
            topic="Software Engineering",
            status="IN_PROGRESS",
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)

        doc = Document(
            project_id=proj.id,
            original_filename="BaoCao_TAFood.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            storage_path="projects/1/docs/sample.docx",
            file_size=1024,
            content_hash="abc123hash",
            version=1,
            processing_status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Create chunks with embeddings
        chunks_data = [
            ChunkItem(
                chunk_index=0,
                section_title="Chương 1",
                page_number=1,
                text="Hệ thống đặt món ăn TA-Food giải quyết bài toán đặt món nhanh.",
            ),
            ChunkItem(
                chunk_index=1,
                section_title="Chương 2",
                page_number=5,
                text="Tích hợp cổng thanh toán VNPay và quy trình xử lý giao dịch hoàn tiền.",
            ),
        ]
        embeddings = embedding_service.embed_batch([c.text for c in chunks_data])

        inserted = chunk_repo.bulk_create_chunks(
            db=db,
            project_id=proj.id,
            document_id=doc.id,
            chunks=chunks_data,
            embeddings=embeddings,
        )
        assert inserted == 2, f"Expected 2 inserted chunks, got {inserted}"

        stored_chunks = chunk_repo.get_chunks_by_document(db, doc.id)
        assert len(stored_chunks) == 2
        assert stored_chunks[0].embedding is not None, "Stored chunk should retain embedding"
        assert len(stored_chunks[0].embedding) == 1024
        print(f"PASS: {inserted} chunks persisted with 1024-dimension vector embeddings.")
    finally:
        db.close()


def test_rag_retrieval_and_scoping():
    print("\n--- 3. Integration Test: RagRetriever Semantic Retrieval & Scoping ---")
    db = TestingSessionLocal()
    try:
        # Setup Project 1: Food Delivery
        p1 = ThesisProject(student_id=1, title="Food Delivery System", status="in_progress")
        db.add(p1)
        db.commit()
        db.refresh(p1)

        d1 = Document(
            project_id=p1.id,
            original_filename="FoodSystem.pdf",
            mime_type="application/pdf",
            storage_path="path/1.pdf",
            file_size=2048,
            content_hash="hash_p1",
            version=1,
            processing_status="ready",
        )
        db.add(d1)
        db.commit()
        db.refresh(d1)

        p1_chunks = [
            ChunkItem(
                chunk_index=0,
                section_title="Mô hình Khuyến nghị",
                page_number=12,
                text="Hệ thống ứng dụng thuật toán Collaborative Filtering và Ma trận phân rã SVD để gợi ý món ăn theo khẩu vị cá nhân.",
            ),
            ChunkItem(
                chunk_index=1,
                section_title="Bảo mật & Xác thực",
                page_number=20,
                text="Xác thực người dùng dựa trên JSON Web Token (JWT) với khóa RSA 256-bit và thời gian sống access token là 30 phút.",
            ),
            ChunkItem(
                chunk_index=2,
                section_title="Cổng Thanh Toán",
                page_number=35,
                text="Tích hợp API thanh toán trực tuyến qua cổng VNPay Sandbox, xử lý callback IPN và đảm bảo giao dịch idempotency.",
            ),
        ]
        p1_embeddings = embedding_service.embed_batch([c.text for c in p1_chunks])
        chunk_repo.bulk_create_chunks(
            db=db,
            project_id=p1.id,
            document_id=d1.id,
            chunks=p1_chunks,
            embeddings=p1_embeddings,
        )

        # Setup Project 2: Medical AI (To test project boundary isolation)
        p2 = ThesisProject(student_id=2, title="Medical Imaging AI", status="in_progress")
        db.add(p2)
        db.commit()
        db.refresh(p2)

        d2 = Document(
            project_id=p2.id,
            original_filename="MedicalAI.pdf",
            mime_type="application/pdf",
            storage_path="path/2.pdf",
            file_size=2048,
            content_hash="hash_p2",
            version=1,
            processing_status="ready",
        )
        db.add(d2)
        db.commit()
        db.refresh(d2)

        p2_chunks = [
            ChunkItem(
                chunk_index=0,
                section_title="Mô hình Chẩn đoán",
                page_number=50,
                text="Mô hình Deep Learning ResNet-50 phân loại ảnh X-quang phổi và phát hiện tổn thương khối u.",
            )
        ]
        p2_embeddings = embedding_service.embed_batch([c.text for c in p2_chunks])
        chunk_repo.bulk_create_chunks(
            db=db,
            project_id=p2.id,
            document_id=d2.id,
            chunks=p2_chunks,
            embeddings=p2_embeddings,
        )

        # Test A: Semantic query retrieval for Project 1
        query = "Cổng thanh toán VNPay và xử lý callback IPN"
        results = rag_retriever.retrieve(db, project_id=p1.id, query=query, top_k=2, min_similarity=0.0)
        assert len(results) > 0, "Should retrieve at least 1 chunk"
        top_chunk = results[0]
        assert "VNPay" in top_chunk.text, f"Top match should be VNPay payment chunk, got: {top_chunk.text}"
        assert top_chunk.page_number == 35, f"Expected page 35, got {top_chunk.page_number}"
        print(f"PASS: Scoped query matched correct chunk: '{top_chunk.section_title}' (Page {top_chunk.page_number}, Score: {top_chunk.similarity_score:.4f}).")

        # Test B: Strict Project Boundary Isolation Guard
        # Querying Project 1 for "ảnh X-quang phổi" MUST NOT return chunks from Project 2!
        isolation_results = rag_retriever.retrieve(
            db, project_id=p1.id, query="chẩn đoán hình ảnh X-quang phổi ResNet-50", top_k=5, min_similarity=0.0
        )
        for r in isolation_results:
            assert "X-quang" not in r.text, "CRITICAL ERROR: Cross-project data leak detected!"
            assert r.document_id == d1.id, "Retrieved chunk does not belong to Project 1!"
        print("PASS: Project Isolation Guard verified! Zero cross-project data leakage.")

        # Test C: Anti-Stale Guard: Uploading v2 deactivates v1 chunks
        d1_v2 = Document(
            project_id=p1.id,
            original_filename="FoodSystem_v2.pdf",
            mime_type="application/pdf",
            storage_path="path/1_v2.pdf",
            file_size=2048,
            content_hash="hash_p1_v2",
            version=2,
            processing_status="ready",
        )
        db.add(d1_v2)
        db.commit()
        db.refresh(d1_v2)

        v2_chunks = [
            ChunkItem(
                chunk_index=0,
                section_title="Cổng Thanh Toán v2",
                page_number=40,
                text="Phiên bản v2 bổ sung thanh toán qua MoMo và ZaloPay bên cạnh VNPay.",
            )
        ]
        v2_embeddings = embedding_service.embed_batch([c.text for c in v2_chunks])
        chunk_repo.bulk_create_chunks(
            db=db,
            project_id=p1.id,
            document_id=d1_v2.id,
            chunks=v2_chunks,
            embeddings=v2_embeddings,
        )
        # Deactivate old chunks
        chunk_repo.deactivate_older_chunks(db, project_id=p1.id, active_document_id=d1_v2.id)

        # Retrieval should now return only v2 chunks
        post_update_results = rag_retriever.retrieve(
            db, project_id=p1.id, query="phương thức thanh toán ví điện tử", top_k=5, min_similarity=0.0
        )
        assert len(post_update_results) == 1, f"Expected 1 active chunk, got {len(post_update_results)}"
        assert post_update_results[0].document_id == d1_v2.id
        assert "MoMo và ZaloPay" in post_update_results[0].text
        print("PASS: Anti-Stale Guard verified! Only active v2 chunks returned during retrieval.")

        # Test D: Citation format
        citation = post_update_results[0].format_citation()
        assert "[Trang 40 | Mục: Cổng Thanh Toán v2" in citation
        print(f"PASS: Academic citation format verified: {citation}")

        context_prompt = rag_retriever.format_context_for_prompt(post_update_results)
        assert "--- Đoạn trích #1" in context_prompt
        assert "MoMo và ZaloPay" in context_prompt
        print("PASS: Context prompt block formatting verified.")

    finally:
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING BƯỚC 6.1 TESTS: VECTOR EMBEDDING & RAG RETRIEVER")
    print("==================================================")
    test_embedding_service_unit()
    test_chunk_repo_vector_storage()
    test_rag_retrieval_and_scoping()
    print("\n==================================================")
    print(" ALL STEP 6.1 EMBEDDING & RAG TESTS PASSED!")
    print("==================================================")
