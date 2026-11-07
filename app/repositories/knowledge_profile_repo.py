import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_profile import ProjectKnowledgeProfile

logger = logging.getLogger(__name__)


class KnowledgeProfileRepository:
    """Data access repository for ProjectKnowledgeProfile entity."""

    def get_by_project_id(
        self,
        db: Session,
        project_id: int,
    ) -> Optional[ProjectKnowledgeProfile]:
        """Fetch current knowledge profile for a project."""
        stmt = (
            select(ProjectKnowledgeProfile)
            .where(ProjectKnowledgeProfile.project_id == project_id)
            .order_by(ProjectKnowledgeProfile.version.desc())
        )
        return db.scalars(stmt).first()

    def get_by_id(
        self,
        db: Session,
        profile_id: int,
    ) -> Optional[ProjectKnowledgeProfile]:
        """Fetch profile by ID."""
        return db.get(ProjectKnowledgeProfile, profile_id)

    def create_or_update(
        self,
        db: Session,
        project_id: int,
        profile_json: Dict[str, Any],
        source_document_ids: List[int],
        status: str = "ready",
        version: int = 1,
    ) -> ProjectKnowledgeProfile:
        """Create a new profile or update existing one for the project."""
        existing = self.get_by_project_id(db, project_id)
        if existing:
            existing.profile_json = profile_json
            existing.source_document_ids = source_document_ids
            existing.status = status
            existing.version = version
            db.commit()
            db.refresh(existing)
            return existing

        new_profile = ProjectKnowledgeProfile(
            project_id=project_id,
            profile_json=profile_json,
            source_document_ids=source_document_ids,
            status=status,
            version=version,
        )
        db.add(new_profile)
        db.commit()
        db.refresh(new_profile)
        return new_profile

    def update_status(
        self,
        db: Session,
        profile: ProjectKnowledgeProfile,
        status: str,
    ) -> ProjectKnowledgeProfile:
        """Update processing status."""
        profile.status = status
        db.commit()
        db.refresh(profile)
        return profile


knowledge_profile_repo = KnowledgeProfileRepository()

