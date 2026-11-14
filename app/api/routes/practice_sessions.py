from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.session import (
    PracticeSessionCreateRequest,
    PracticeSessionListItemResponse,
    PracticeSessionDetailResponse,
    UpdateSessionStatusRequest,
)
from app.schemas.question import QuestionResponse
from app.repositories.project_repo import project_repo
from app.repositories.chunk_repo import chunk_repo
from app.repositories.knowledge_profile_repo import knowledge_profile_repo
from app.repositories.session_repo import session_repo
from app.repositories.question_repo import question_repo
from app.services.question_generator import question_generator_service

router = APIRouter(tags=["practice-sessions"])


@router.post(
    "/projects/{project_id}/practice/sessions",
    response_model=PracticeSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Khởi tạo phiên luyện tập bảo vệ mới và tự động sinh bộ câu hỏi",
)
def create_practice_session(
    project_id: int,
    request: PracticeSessionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PracticeSessionDetailResponse:
    """
    Tạo một phiên luyện tập bảo vệ (PracticeSession) mới, tự động kích hoạt
    Question Generator để sinh bộ 12-15 câu hỏi bám sát tài liệu đồ án
    kèm dàn ý kỳ vọng và trích dẫn căn cứ.
    """
    project = project_repo.get_by_id(db, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
        )

    # Permission check: Only project owner or admin
    is_owner = project.student_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền tạo phiên luyện tập cho đề tài này.",
        )

    # Verify project has indexed document chunks
    active_chunks = chunk_repo.get_active_chunks_by_project(db, project_id)
    if not active_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Đề tài chưa có tài liệu nào được xử lý hoàn tất để luyện tập.",
        )

    # Retrieve knowledge profile version
    profile = knowledge_profile_repo.get_by_project_id(db, project_id)
    profile_version = profile.version if profile else 1

    # 1. Generate questions
    generated_set = question_generator_service.generate_questions_for_project(
        db=db,
        project_id=project_id,
        target_count=request.target_questions,
    )

    # 2. Create PracticeSession record
    session_obj = session_repo.create(
        db=db,
        project_id=project_id,
        mode=request.mode,
        knowledge_profile_version=profile_version,
    )

    # 3. Bulk insert questions
    db_questions = question_repo.bulk_create(
        db=db,
        session_id=session_obj.id,
        items=generated_set.questions,
    )

    question_responses = [
        QuestionResponse(
            id=q.id,
            session_id=q.session_id,
            order_index=q.order_index,
            question_text=q.question_text,
            difficulty=q.difficulty,
            topic_competency=q.topic_competency,
            expected_answer_outline=q.expected_answer_outline,
            source_chunk_ids=q.source_chunk_ids or [],
            recommended_seconds=q.recommended_seconds,
            is_answered=(q.answer is not None),
            created_at=q.created_at,
        )
        for q in db_questions
    ]

    return PracticeSessionDetailResponse(
        id=session_obj.id,
        project_id=session_obj.project_id,
        mode=session_obj.mode,
        status=session_obj.status,
        knowledge_profile_version=session_obj.knowledge_profile_version,
        started_at=session_obj.started_at,
        ended_at=session_obj.ended_at,
        questions=question_responses,
    )


@router.get(
    "/projects/{project_id}/practice/sessions",
    response_model=List[PracticeSessionListItemResponse],
    summary="Lấy danh sách các phiên luyện tập của đồ án",
)
def list_project_practice_sessions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[PracticeSessionListItemResponse]:
    """
    Trả về lịch sử các phiên luyện tập của đồ án, sắp xếp mới nhất lên đầu.
    """
    project = project_repo.get_by_id(db, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
        )

    is_owner = project.student_id == current_user.id
    is_supervisor = project.supervisor_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_owner or is_supervisor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xem các phiên luyện tập của đề tài này.",
        )

    sessions = session_repo.list_by_project_id(db, project_id)
    results = []
    for s in sessions:
        total_q = len(s.questions)
        ans_q = sum(1 for q in s.questions if q.answer is not None)
        results.append(
            PracticeSessionListItemResponse(
                id=s.id,
                project_id=s.project_id,
                mode=s.mode,
                status=s.status,
                knowledge_profile_version=s.knowledge_profile_version,
                total_questions=total_q,
                answered_questions=ans_q,
                started_at=s.started_at,
                ended_at=s.ended_at,
            )
        )
    return results


@router.get(
    "/practice/sessions/{session_id}",
    response_model=PracticeSessionDetailResponse,
    summary="Lấy chi tiết phiên luyện tập cụ thể kèm danh sách câu hỏi",
)
def get_practice_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PracticeSessionDetailResponse:
    """
    Lấy thông tin chi tiết của một phiên luyện tập cụ thể kèm toàn bộ câu hỏi.
    """
    session_obj = session_repo.get_by_id(db, session_id)
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Phiên luyện tập #{session_id} không tồn tại.",
        )

    project = project_repo.get_by_id(db, session_obj.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Đề tài liên quan đến phiên luyện tập không tồn tại.",
        )

    is_owner = project.student_id == current_user.id
    is_supervisor = project.supervisor_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_owner or is_supervisor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập phiên luyện tập này.",
        )

    sorted_questions = sorted(session_obj.questions, key=lambda q: q.order_index)
    question_responses = [
        QuestionResponse(
            id=q.id,
            session_id=q.session_id,
            order_index=q.order_index,
            question_text=q.question_text,
            difficulty=q.difficulty,
            topic_competency=q.topic_competency,
            expected_answer_outline=q.expected_answer_outline,
            source_chunk_ids=q.source_chunk_ids or [],
            recommended_seconds=q.recommended_seconds,
            is_answered=(q.answer is not None),
            created_at=q.created_at,
        )
        for q in sorted_questions
    ]

    return PracticeSessionDetailResponse(
        id=session_obj.id,
        project_id=session_obj.project_id,
        mode=session_obj.mode,
        status=session_obj.status,
        knowledge_profile_version=session_obj.knowledge_profile_version,
        started_at=session_obj.started_at,
        ended_at=session_obj.ended_at,
        questions=question_responses,
    )


@router.patch(
    "/practice/sessions/{session_id}/status",
    response_model=PracticeSessionDetailResponse,
    summary="Cập nhật trạng thái phiên luyện tập (hoàn thành hoặc hủy)",
)
def update_practice_session_status(
    session_id: int,
    request: UpdateSessionStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PracticeSessionDetailResponse:
    """
    Cập nhật trạng thái phiên luyện tập thành 'completed' hoặc 'cancelled'.
    """
    session_obj = session_repo.get_by_id(db, session_id)
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Phiên luyện tập #{session_id} không tồn tại.",
        )

    project = project_repo.get_by_id(db, session_obj.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Đề tài không tồn tại.",
        )

    is_owner = project.student_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền cập nhật trạng thái phiên này.",
        )

    allowed_statuses = ["in_progress", "completed", "cancelled"]
    if request.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trạng thái không hợp lệ. Phải thuộc: {', '.join(allowed_statuses)}",
        )

    updated_session = session_repo.update_status(db, session_obj, status=request.status)

    sorted_questions = sorted(updated_session.questions, key=lambda q: q.order_index)
    question_responses = [
        QuestionResponse(
            id=q.id,
            session_id=q.session_id,
            order_index=q.order_index,
            question_text=q.question_text,
            difficulty=q.difficulty,
            topic_competency=q.topic_competency,
            expected_answer_outline=q.expected_answer_outline,
            source_chunk_ids=q.source_chunk_ids or [],
            recommended_seconds=q.recommended_seconds,
            is_answered=(q.answer is not None),
            created_at=q.created_at,
        )
        for q in sorted_questions
    ]

    return PracticeSessionDetailResponse(
        id=updated_session.id,
        project_id=updated_session.project_id,
        mode=updated_session.mode,
        status=updated_session.status,
        knowledge_profile_version=updated_session.knowledge_profile_version,
        started_at=updated_session.started_at,
        ended_at=updated_session.ended_at,
        questions=question_responses,
    )

