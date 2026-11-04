from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload
from app.models.project import ThesisProject
from app.models.user import User


class ProjectRepository:
    """Data access repository for ThesisProject entity."""

    def get_by_id(self, db: Session, project_id: int) -> Optional[ThesisProject]:
        """Fetch project by ID with relationships eager loaded."""
        stmt = (
            select(ThesisProject)
            .options(
                joinedload(ThesisProject.student),
                joinedload(ThesisProject.supervisor),
                selectinload(ThesisProject.documents),
            )
            .where(ThesisProject.id == project_id)
        )
        return db.scalars(stmt).first()

    def get_latest_by_student_id(self, db: Session, student_id: int) -> Optional[ThesisProject]:
        """Fetch the most recent active project of a student."""
        stmt = (
            select(ThesisProject)
            .options(
                joinedload(ThesisProject.student),
                joinedload(ThesisProject.supervisor),
                selectinload(ThesisProject.documents),
            )
            .where(ThesisProject.student_id == student_id)
            .order_by(ThesisProject.created_at.desc())
        )
        return db.scalars(stmt).first()

    def get_all_by_student_id(self, db: Session, student_id: int) -> List[ThesisProject]:
        """Fetch all projects owned by a student."""
        stmt = (
            select(ThesisProject)
            .options(
                joinedload(ThesisProject.student),
                joinedload(ThesisProject.supervisor),
                selectinload(ThesisProject.documents),
            )
            .where(ThesisProject.student_id == student_id)
            .order_by(ThesisProject.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    def get_all_by_supervisor_id(self, db: Session, supervisor_id: int) -> List[ThesisProject]:
        """Fetch all projects supervised by a lecturer."""
        stmt = (
            select(ThesisProject)
            .options(
                joinedload(ThesisProject.student),
                joinedload(ThesisProject.supervisor),
                selectinload(ThesisProject.documents),
            )
            .where(ThesisProject.supervisor_id == supervisor_id)
            .order_by(ThesisProject.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    def create(
        self,
        db: Session,
        student_id: int,
        title: str,
        topic: Optional[str] = None,
        description: Optional[str] = None,
        academic_year: Optional[str] = None,
        supervisor_id: Optional[int] = None,
        status: str = "PLANNING",
    ) -> ThesisProject:
        """Create and persist a new thesis project."""
        project = ThesisProject(
            student_id=student_id,
            title=title.strip(),
            topic=topic.strip() if topic else None,
            description=description.strip() if description else None,
            academic_year=academic_year.strip() if academic_year else None,
            supervisor_id=supervisor_id,
            status=status,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        # Re-fetch with eager loaded relationships
        return self.get_by_id(db, project.id) or project

    def update(
        self,
        db: Session,
        project: ThesisProject,
        update_data: Dict[str, Any],
    ) -> ThesisProject:
        """Update fields of an existing project."""
        for key, value in update_data.items():
            if hasattr(project, key) and value is not None:
                if isinstance(value, str):
                    setattr(project, key, value.strip())
                else:
                    setattr(project, key, value)
        db.commit()
        db.refresh(project)
        return self.get_by_id(db, project.id) or project

    def delete(self, db: Session, project: ThesisProject) -> None:
        """Delete a project and cascade associated entities."""
        db.delete(project)
        db.commit()

    def get_lecturers(self, db: Session) -> List[User]:
        """Fetch list of active lecturers for advisor selection."""
        stmt = (
            select(User)
            .where(User.role == "lecturer", User.is_active == True)
            .order_by(User.name.asc())
        )
        return list(db.scalars(stmt).all())


project_repo = ProjectRepository()

