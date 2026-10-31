from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.user import User


class UserRepository:
    """Data access repository for User entity."""

    def get_by_id(self, db: Session, user_id: int) -> Optional[User]:
        return db.get(User, user_id)

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email.strip().lower())
        return db.scalars(stmt).first()

    def create(
        self,
        db: Session,
        name: str,
        email: str,
        password_hash: str,
        role: str = "student",
    ) -> User:
        user = User(
            name=name.strip(),
            email=email.strip().lower(),
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


user_repo = UserRepository()
