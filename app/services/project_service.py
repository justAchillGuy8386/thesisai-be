from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.project import ThesisProject
from app.models.user import User
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectResponse,
    LecturerSimpleResponse,
)
from app.repositories.project_repo import project_repo
from app.repositories.user_repo import user_repo


VALID_STATUSES = {"PLANNING", "IN_PROGRESS", "READY_FOR_DEFENSE", "COMPLETED"}


class ProjectService:
    """Business logic for Thesis Project management."""

    def to_project_response(self, project: ThesisProject) -> ProjectResponse:
        """Convert ORM ThesisProject to API ProjectResponse schema."""
        student_name = project.student.name if project.student else None
        student_email = project.student.email if project.student else None
        supervisor_name = project.supervisor.name if project.supervisor else None
        documents_count = len(project.documents) if project.documents is not None else 0

        return ProjectResponse(
            id=project.id,
            student_id=project.student_id,
            student_name=student_name,
            student_email=student_email,
            supervisor_id=project.supervisor_id,
            supervisor_name=supervisor_name,
            title=project.title,
            topic=project.topic,
            description=project.description,
            status=project.status,
            academic_year=project.academic_year,
            documents_count=documents_count,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    def create_project(
        self,
        db: Session,
        student_id: int,
        payload: ProjectCreateRequest,
    ) -> ProjectResponse:
        """Create a new thesis project for a student."""
        # Verify supervisor if specified
        if payload.supervisor_id is not None:
            supervisor = user_repo.get_by_id(db, payload.supervisor_id)
            if not supervisor or supervisor.role != "lecturer" or not supervisor.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Giảng viên hướng dẫn không tồn tại hoặc tài khoản chưa kích hoạt.",
                )

        new_project = project_repo.create(
            db=db,
            student_id=student_id,
            title=payload.title,
            topic=payload.topic,
            description=payload.description,
            academic_year=payload.academic_year,
            supervisor_id=payload.supervisor_id,
            status="PLANNING",
        )
        return self.to_project_response(new_project)

    def get_student_active_project(
        self,
        db: Session,
        student_id: int,
    ) -> Optional[ProjectResponse]:
        """Fetch the most recent project of a student."""
        project = project_repo.get_latest_by_student_id(db, student_id)
        if not project:
            return None
        return self.to_project_response(project)

    def get_project_by_id(
        self,
        db: Session,
        project_id: int,
        current_user: User,
    ) -> ProjectResponse:
        """Fetch project details with access permission check."""
        project = project_repo.get_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
            )

        # Access control
        is_owner = project.student_id == current_user.id
        is_supervisor = project.supervisor_id == current_user.id
        is_admin = current_user.role == "admin"

        if not (is_owner or is_supervisor or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền truy cập đề tài đồ án này.",
            )

        return self.to_project_response(project)

    def update_project(
        self,
        db: Session,
        project_id: int,
        payload: ProjectUpdateRequest,
        current_user: User,
    ) -> ProjectResponse:
        """Update project details or status with ownership check."""
        project = project_repo.get_by_id(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đề tài đồ án tốt nghiệp.",
            )

        # Only the owning student or supervisor or admin can edit
        is_owner = project.student_id == current_user.id
        is_supervisor = project.supervisor_id == current_user.id
        is_admin = current_user.role == "admin"

        if not (is_owner or is_supervisor or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền chỉnh sửa đề tài đồ án này.",
            )

        # Validate status if provided
        if payload.status is not None and payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Trạng thái '{payload.status}' không hợp lệ. Cho phép: {', '.join(VALID_STATUSES)}",
            )

        # Verify supervisor if updating supervisor_id
        if payload.supervisor_id is not None:
            supervisor = user_repo.get_by_id(db, payload.supervisor_id)
            if not supervisor or supervisor.role != "lecturer" or not supervisor.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Giảng viên hướng dẫn không tồn tại hoặc tài khoản chưa kích hoạt.",
                )

        update_dict = payload.model_dump(exclude_unset=True)
        updated_project = project_repo.update(db, project, update_dict)
        return self.to_project_response(updated_project)

    def get_available_lecturers(self, db: Session) -> List[LecturerSimpleResponse]:
        """Get list of active lecturers for advisor selection."""
        lecturers = project_repo.get_lecturers(db)
        return [LecturerSimpleResponse.model_validate(lec) for lec in lecturers]


project_service = ProjectService()

