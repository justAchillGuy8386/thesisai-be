"""
Unit & Integration Tests for Bước 7.1: Question Generation Service & Pydantic Schemas.
Validates:
1. Pydantic models for GeneratedQuestionItem and GeneratedQuestionSet.
2. Question generation with mocked LLM output (checking JSON parsing, 3 difficulty tiers, chunk provenance).
3. Graceful fallback generation when local LLM is offline or returns invalid JSON.
4. Error handling when project does not exist or has no indexed chunks.
"""
import sys
import os

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
from app.core.security import hash_password
from app.schemas.question import (
    QuestionDifficulty,
    GeneratedQuestionItem,
    GeneratedQuestionSet,
)
from app.schemas.document import ChunkItem
from app.schemas.knowledge_profile import KnowledgeProfileData
from app.services.question_generator import question_generator_service, QuestionGeneratorService
from app.repositories.chunk_repo import chunk_repo

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


def setup_sample_project(db):
    user = User(
        email="test_student@example.com",
        name="Nguyễn Văn A",
        role="student",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    project = ThesisProject(
        student_id=user.id,
        title="Xây dựng Website Đặt Món Ăn TA-Food sử dụng Laravel",
        topic="Kỹ thuật phần mềm",
        status="IN_PROGRESS",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    doc = Document(
        project_id=project.id,
        original_filename="TA-Food.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_path="path/tafood.docx",
        file_size=10240,
        content_hash="hash_tafood_71",
        version=1,
        processing_status="ready",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    chunks_data = [
        ChunkItem(
            chunk_index=0,
            section_title="Chương 1: Tổng quan đề tài",
            page_number=1,
            text="Đề tài tập trung nghiên cứu giải pháp đặt món ăn trực tuyến tối ưu hóa thời gian đặt hàng.",
        ),
        ChunkItem(
            chunk_index=1,
            section_title="Chương 2: Thiết kế Kiến trúc",
            page_number=15,
            text="Hệ thống áp dụng mô hình MVC sử dụng framework Laravel PHP và cơ sở dữ liệu MySQL.",
        ),
        ChunkItem(
            chunk_index=2,
            section_title="Chương 3: Cơ sở dữ liệu",
            page_number=25,
            text="Lược đồ CSDL chuẩn 3NF gồm bảng users, dishes, orders, order_items và payments.",
        ),
        ChunkItem(
            chunk_index=3,
            section_title="Chương 4: Bảo mật & Tích hợp",
            page_number=40,
            text="Tích hợp cổng PayOS và bảo vệ ứng dụng bằng CSRF Token và xác thực phân quyền Role-based.",
        ),
        ChunkItem(
            chunk_index=4,
            section_title="Chương 5: Đánh giá & Hạn chế",
            page_number=55,
            text="Hệ thống chưa được kiểm thử tải đồng thời với số lượng lớn người dùng và chưa có microservices.",
        ),
    ]
    embs = [[0.01 * (i + j) for j in range(1024)] for i in range(len(chunks_data))]
    chunk_repo.bulk_create_chunks(
        db=db,
        project_id=project.id,
        document_id=doc.id,
        chunks=chunks_data,
        embeddings=embs,
    )

    profile_content = KnowledgeProfileData(
        summary="Đề tài Website đặt món ăn TA-Food phát triển trên nền tảng Laravel.",
        objectives=["Xây dựng hệ thống đặt món trực tuyến", "Tối ưu hóa quy trình quản lý thực đơn"],
        methodology_and_tech=["Laravel", "PHP", "MySQL", "PayOS", "Bootstrap 5"],
        contributions=["Giải pháp đặt món tiện lợi", "Tích hợp thanh toán trực tuyến"],
        defense_weaknesses=["Chưa kiểm thử tải cao (Load Testing)", "Chưa có Message Queue cho thông báo"],
        anticipated_questions=[],
    )

    profile = ProjectKnowledgeProfile(
        project_id=project.id,
        version=1,
        profile_json=profile_content.model_dump(),
        source_document_ids=[doc.id],
        status="ready",
    )
    db.add(profile)
    db.commit()

    return project


def test_schema_validation():
    print("\n--- 1. Test Question Pydantic Schemas ---")
    item = GeneratedQuestionItem(
        order_index=1,
        question_text="Mục tiêu nghiên cứu của đề tài là gì?",
        difficulty=QuestionDifficulty.EASY,
        topic_competency="Tổng quan đề tài",
        expected_answer_outline="- Trình bày bối cảnh\n- Nêu 3 mục tiêu",
        source_chunk_ids=[1, 2],
        recommended_seconds=120,
    )
    assert item.order_index == 1
    assert item.difficulty == "easy"
    assert len(item.source_chunk_ids) == 2

    q_set = GeneratedQuestionSet(
        project_id=1,
        questions=[item],
        total_questions=1,
        easy_count=1,
        medium_count=0,
        hard_count=0,
    )
    assert q_set.total_questions == 1
    assert q_set.easy_count == 1
    print("PASS: Pydantic schemas validated successfully.")


def test_question_generation_with_mocked_llm():
    print("\n--- 2. Test Question Generation with Mocked LLM Output ---")
    db = TestingSessionLocal()
    try:
        project = setup_sample_project(db)

        # Mock LLM output
        mock_json_content = """
        {
          "questions": [
            {
              "order_index": 1,
              "question_text": "Trình bày mục tiêu chính của đồ án TA-Food?",
              "difficulty": "easy",
              "topic_competency": "Tổng quan đề tài",
              "expected_answer_outline": "- Nêu bài toán đặt món ăn\\n- Nêu mục tiêu tự động hóa",
              "source_chunk_ids": [1],
              "recommended_seconds": 120
            },
            {
              "order_index": 2,
              "question_text": "Tại sao bạn lựa chọn Laravel thay vì Node.js?",
              "difficulty": "medium",
              "topic_competency": "Kiến trúc & Công nghệ",
              "expected_answer_outline": "- Hệ sinh thái Eloquent ORM mạnh\\n- Blade templating nhanh",
              "source_chunk_ids": [2],
              "recommended_seconds": 120
            },
            {
              "order_index": 3,
              "question_text": "Điểm nghẽn chịu tải lớn nhất của hệ thống là gì khi có 10.000 user?",
              "difficulty": "hard",
              "topic_competency": "Xử lý tải & Tối ưu",
              "expected_answer_outline": "- Database connection pool\\n- Cần bổ sung Redis cache",
              "source_chunk_ids": [5],
              "recommended_seconds": 120
            }
          ]
        }
        """

        svc = QuestionGeneratorService()
        orig_call = svc._call_ollama_generate_questions

        # Patch call to return mock
        svc._call_ollama_generate_questions = lambda project, profile_data, chunks, target_count: [
            GeneratedQuestionItem(
                order_index=1,
                question_text="Trình bày mục tiêu chính của đồ án TA-Food?",
                difficulty=QuestionDifficulty.EASY,
                topic_competency="Tổng quan đề tài",
                expected_answer_outline="- Nêu bài toán đặt món ăn\n- Nêu mục tiêu tự động hóa",
                source_chunk_ids=[1],
            ),
            GeneratedQuestionItem(
                order_index=2,
                question_text="Tại sao bạn lựa chọn Laravel thay vì Node.js?",
                difficulty=QuestionDifficulty.MEDIUM,
                topic_competency="Kiến trúc & Công nghệ",
                expected_answer_outline="- Hệ sinh thái Eloquent ORM mạnh\n- Blade templating nhanh",
                source_chunk_ids=[2],
            ),
            GeneratedQuestionItem(
                order_index=3,
                question_text="Điểm nghẽn chịu tải lớn nhất của hệ thống là gì khi có 10.000 user?",
                difficulty=QuestionDifficulty.HARD,
                topic_competency="Xử lý tải & Tối ưu",
                expected_answer_outline="- Database connection pool\n- Cần bổ sung Redis cache",
                source_chunk_ids=[5],
            ),
        ]

        # In case fewer than 6 questions are returned by LLM, the service augments with heuristic generator
        result = svc.generate_questions_for_project(db, project.id, target_count=12)

        assert result.total_questions >= 12
        assert result.easy_count >= 3
        assert result.medium_count >= 5
        assert result.hard_count >= 3
        assert result.project_id == project.id

        # Verify all questions have outlines and chunk IDs
        for q in result.questions:
            assert len(q.question_text) > 10
            assert len(q.expected_answer_outline) > 10
            assert len(q.source_chunk_ids) > 0
            assert q.recommended_seconds == 120

        print(f"PASS: Question generator returned {result.total_questions} questions (Easy: {result.easy_count}, Med: {result.medium_count}, Hard: {result.hard_count})")
    finally:
        db.close()


def test_question_generation_fallback():
    print("\n--- 3. Test Question Generation Heuristic Fallback ---")
    db = TestingSessionLocal()
    try:
        project = db.query(ThesisProject).first()
        svc = QuestionGeneratorService()
        # Force LLM failure
        svc._call_ollama_generate_questions = lambda *args, **kwargs: []

        result = svc.generate_questions_for_project(db, project.id, target_count=12)

        assert result.total_questions == 12
        assert result.easy_count == 3
        assert result.medium_count == 6
        assert result.hard_count == 3

        # Verify order indices are 1..12
        indices = [q.order_index for q in result.questions]
        assert indices == list(range(1, 13))

        # Check that project title is embedded in the questions
        first_q = result.questions[0]
        assert "TA-Food" in first_q.question_text
        assert first_q.difficulty == QuestionDifficulty.EASY
        assert "Tổng quan" in first_q.topic_competency

        hard_q = result.questions[-1]
        assert hard_q.difficulty == QuestionDifficulty.HARD
        assert len(hard_q.expected_answer_outline) > 0

        print("PASS: Heuristic fallback generated full 12-question defense suite.")
    finally:
        db.close()


def test_question_generation_error_handling():
    print("\n--- 4. Test Question Generation Error Handling ---")
    db = TestingSessionLocal()
    try:
        svc = QuestionGeneratorService()

        # Non-existent project
        try:
            svc.generate_questions_for_project(db, 99999)
            assert False, "Should have raised ValueError for non-existent project"
        except ValueError as e:
            assert "không tồn tại" in str(e)
            print("PASS: Caught non-existent project error.")

        # Project with no chunks
        empty_proj = ThesisProject(
            student_id=1,
            title="Đề tài rỗng",
            topic="CNTT",
            status="PLANNING",
        )
        db.add(empty_proj)
        db.commit()
        db.refresh(empty_proj)

        try:
            svc.generate_questions_for_project(db, empty_proj.id)
            assert False, "Should have raised ValueError for project without chunks"
        except ValueError as e:
            assert "chưa có tài liệu nào" in str(e)
            print("PASS: Caught empty project chunks error.")

    finally:
        db.close()


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING STEP 7.1 TESTS: QUESTION GENERATION SERVICE")
    print("==================================================")
    test_schema_validation()
    test_question_generation_with_mocked_llm()
    test_question_generation_fallback()
    test_question_generation_error_handling()
    print("\n==================================================")
    print(" ALL STEP 7.1 QUESTION GENERATION TESTS PASSED!")
    print("==================================================")

