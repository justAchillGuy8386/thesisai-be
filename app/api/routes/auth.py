from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký tài khoản mới (Sinh viên hoặc Giảng viên)",
)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    """
    Tạo tài khoản người dùng mới:
    - Băm mật khẩu an toàn bằng Bcrypt.
    - Kiểm tra email không được trùng lặp.
    - Mặc định vai trò là `student` nếu không chọn `lecturer`.
    """
    user = auth_service.register_user(db=db, payload=payload)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Đăng nhập hệ thống",
)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    """
    Xác thực người dùng và cấp JWT Access Token:
    - Kiểm tra email và mật khẩu.
    - Trả về Bearer JWT token có hạn 7 ngày.
    """
    return auth_service.authenticate_user(db=db, payload=payload)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy thông tin tài khoản đang đăng nhập",
)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Lấy hồ sơ người dùng hiện tại từ Bearer JWT Token.
    """
    return current_user
