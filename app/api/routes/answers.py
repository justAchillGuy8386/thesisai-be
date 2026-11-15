import os
import shutil
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.answer import AnswerSubmitResponse, AnswerDetailResponse
from app.repositories.session_repo import session_repo
from app.repositories.question_repo import question_repo
from app.repositories.project_repo import project_repo
from app.repositories.answer_repo import answer_repo

router = APIRouter(tags=["answers"])

ALLOWED_AUDIO_MIMES = {
    "audio/webm",
    "video/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
}


@router.post(
    "/sessions/{session_id}/questions/{question_id}/answer",
    response_model=AnswerSubmitResponse,
    status_code=status.HTTP_200_OK,
    summary="Nộp file ghi âm câu trả lời của sinh viên (phản hồi ngay < 500ms)",
)
def submit_question_audio_answer(
    session_id: int,
    question_id: int,
    file: UploadFile = File(..., description="File audio ghi âm (WebM/WAV)"),
    duration_seconds: Optional[float] = Form(None, description="Thời lượng ghi âm thực tế (giây)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnswerSubmitResponse:
    """
    Tiếp nhận file ghi âm câu trả lời của sinh viên cho một câu hỏi cụ thể,
    lưu file an toàn trên ổ đĩa cục bộ, tạo/cập nhật record Answer với trạng thái 'queued',
    và phản hồi HTTP 200 ngay lập tức mà không bắt sinh viên chờ đợi STT hay LLM.
    """
    # 1. Verify session exists
    session_obj = session_repo.get_by_id(db, session_id)
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Phiên luyện tập #{session_id} không tồn tại.",
        )

    # 2. Verify project ownership
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
            detail="Bạn không có quyền nộp câu trả lời cho phiên luyện tập này.",
        )

    # 3. Verify question belongs to session
    question = question_repo.get_by_id(db, question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Câu hỏi #{question_id} không thuộc phiên luyện tập #{session_id}.",
        )

    # 4. Validate audio file type and size
    raw_mime = (file.content_type or "audio/webm").split(";")[0].strip().lower()
    if raw_mime not in ALLOWED_AUDIO_MIMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Định dạng âm thanh '{file.content_type}' không được hỗ trợ. Vui lòng ghi âm chuẩn WebM hoặc WAV.",
        )

    # Determine extension
    ext = ".webm"
    if "wav" in raw_mime:
        ext = ".wav"
    elif "ogg" in raw_mime:
        ext = ".ogg"
    elif "mp4" in raw_mime:
        ext = ".mp4"

    # 5. Prepare storage directory (Privacy-by-Design)
    target_dir = Path(settings.STORAGE_DIR) / "audio_recordings" / f"session_{session_id}"
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"q_{question_id}_{uuid.uuid4().hex[:10]}{ext}"
    filepath = target_dir / filename

    try:
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể lưu trữ tệp âm thanh trên máy chủ: {str(e)}",
        )

    # Minimum size verification (at least 100 bytes to prevent empty audio blobs)
    file_size = filepath.stat().st_size
    if file_size < 100:
        if filepath.exists():
            filepath.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp âm thanh quá ngắn hoặc không chứa dữ liệu ghi âm hợp lệ.",
        )

    # 6. Save or update Answer record in database
    answer = answer_repo.create_or_update(
        db=db,
        question_id=question_id,
        audio_path=str(filepath),
        audio_mime_type=raw_mime,
        duration_seconds=duration_seconds,
    )

    return AnswerSubmitResponse(
        id=answer.id,
        question_id=answer.question_id,
        audio_path=answer.audio_path,
        audio_mime_type=answer.audio_mime_type,
        duration_seconds=answer.duration_seconds,
        processing_status=answer.processing_status,
        audio_status=answer.audio_status,
        created_at=answer.created_at,
        message="Đã tiếp nhận file ghi âm thành công. Tác vụ xử lý ngầm đang xếp hàng.",
    )


@router.get(
    "/sessions/{session_id}/questions/{question_id}/answer",
    response_model=AnswerDetailResponse,
    summary="Lấy chi tiết và trạng thái xử lý câu trả lời của một câu hỏi",
)
def get_question_answer_detail(
    session_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnswerDetailResponse:
    """
    Truy vấn trạng thái xử lý (queued, transcribing, evaluating, completed)
    và nội dung văn bản transcript của câu trả lời.
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
    is_supervisor = project.supervisor_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_owner or is_supervisor or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xem câu trả lời của phiên này.",
        )

    answer = answer_repo.get_by_question_id(db, question_id)
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Câu hỏi #{question_id} chưa có câu trả lời nào được nộp.",
        )

    audio_url = None
    if answer.audio_status == "active" and answer.audio_path and os.path.exists(answer.audio_path):
        audio_url = f"{settings.API_V1_STR}/answers/{answer.id}/audio"

    return AnswerDetailResponse(
        id=answer.id,
        question_id=answer.question_id,
        audio_mime_type=answer.audio_mime_type,
        duration_seconds=answer.duration_seconds,
        transcript=answer.transcript,
        transcript_segments=answer.transcript_segments,
        processing_status=answer.processing_status,
        audio_status=answer.audio_status,
        audio_url=audio_url,
        error_fields=answer.error_fields,
        created_at=answer.created_at,
        updated_at=answer.updated_at,
    )


@router.get(
    "/answers/{answer_id}/audio",
    summary="Phát lại tệp âm thanh ghi âm câu trả lời (Audio Streaming)",
)
def stream_answer_audio(
    answer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phục vụ file âm thanh để trình duyệt nghe lại (phục vụ sinh viên và giảng viên phản biện).
    """
    answer = answer_repo.get_by_id(db, answer_id)
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy bản ghi âm câu trả lời.",
        )

    if answer.audio_status != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Tệp âm thanh này đã được tự động thu hồi/tiêu hủy theo chính sách bảo mật dữ liệu riêng tư (Privacy-by-Design).",
        )

    if not answer.audio_path or not os.path.exists(answer.audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh vật lý không tồn tại trên ổ lưu trữ máy chủ.",
        )

    # Permission check via question -> session -> project
    question = question_repo.get_by_id(db, answer.question_id)
    if question:
        session_obj = session_repo.get_by_id(db, question.session_id)
        if session_obj:
            project = project_repo.get_by_id(db, session_obj.project_id)
            if project:
                is_owner = project.student_id == current_user.id
                is_supervisor = project.supervisor_id == current_user.id
                is_admin = current_user.role == "admin"
                if not (is_owner or is_supervisor or is_admin):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Bạn không có quyền nghe bản ghi âm này.",
                    )

    return FileResponse(
        path=answer.audio_path,
        media_type=answer.audio_mime_type,
        filename=Path(answer.audio_path).name,
    )

