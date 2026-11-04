from typing import Optional, List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user, require_student
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectResponse,
    LecturerSimpleResponse,
)
from app.services.project_service import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Khởi tạo đề tài đồ án tốt nghiệp mới",
)
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_student: User = Depends(require_student),
) -> ProjectResponse:
    """
    Sinh viên khởi tạo đề tài đồ án tốt nghiệp mới.
    Mặc định trạng thái đề tài là 'PLANNING' (Lập kế hoạch).
    """
    return project_service.create_project(
        db=db,
        student_id=current_student.id,
        payload=payload,
    )


@router.get(
    "/my-project",
    response_model=Optional[ProjectResponse],
    summary="Lấy đề tài đồ án hiện tại của sinh viên",
)
def get_my_project(
    db: Session = Depends(get_db),
    current_student: User = Depends(require_student),
) -> Optional[ProjectResponse]:
    """
    Lấy đề tài đồ án tốt nghiệp mới nhất/đang hoạt động của sinh viên đang đăng nhập.
    Trả về null nếu sinh viên chưa tạo đề tài nào.
    """
    return project_service.get_student_active_project(
        db=db,
        student_id=current_student.id,
    )


@router.get(
    "/lecturers",
    response_model=List[LecturerSimpleResponse],
    summary="Lấy danh sách Giảng viên hướng dẫn khả dụng",
)
def list_lecturers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[LecturerSimpleResponse]:
    """
    Lấy danh sách các tài khoản Giảng viên đang hoạt động để sinh viên chọn Giảng viên hướng dẫn.
    """
    return project_service.get_available_lecturers(db=db)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Lấy thông tin chi tiết một đề tài đồ án",
)
def get_project_detail(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """
    Lấy chi tiết đề tài đồ án theo ID.
    Chỉ sinh viên sở hữu hoặc giảng viên được phân công mới có quyền xem.
    """
    return project_service.get_project_by_id(
        db=db,
        project_id=project_id,
        current_user=current_user,
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Cập nhật thông tin hoặc trạng thái đề tài đồ án",
)
def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """
    Cập nhật tên, mô tả, niên khóa hoặc trạng thái của đề tài đồ án.
    Trạng thái hỗ trợ: PLANNING, IN_PROGRESS, READY_FOR_DEFENSE, COMPLETED.
    """
    return project_service.update_project(
        db=db,
        project_id=project_id,
        payload=payload,
        current_user=current_user,
    )

