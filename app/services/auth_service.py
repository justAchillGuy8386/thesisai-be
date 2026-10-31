from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse, UserResponse
from app.repositories.user_repo import user_repo
from app.core.security import hash_password, verify_password, create_access_token


class AuthService:
    """Business logic for User Authentication & Registration."""

    def register_user(self, db: Session, payload: UserRegisterRequest) -> User:
        # Check if email is already registered
        existing_user = user_repo.get_by_email(db, payload.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email đã được sử dụng. Vui lòng đăng nhập hoặc chọn email khác.",
            )

        # Hash password and persist user
        pw_hash = hash_password(payload.password)
        new_user = user_repo.create(
            db=db,
            name=payload.name,
            email=payload.email,
            password_hash=pw_hash,
            role=payload.role,
        )
        return new_user

    def authenticate_user(self, db: Session, payload: UserLoginRequest) -> TokenResponse:
        user = user_repo.get_by_email(db, payload.email)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email hoặc mật khẩu không chính xác.",
            )

        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email hoặc mật khẩu không chính xác.",
            )

        # Generate JWT access token with user claims
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
        }
        access_token = create_access_token(data=token_data)

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )


auth_service = AuthService()
