from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class UserResponse(BaseModel):
    """Public user response schema."""
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""
    name: str = Field(..., min_length=2, max_length=100, description="Họ và tên người dùng")
    email: EmailStr = Field(..., description="Địa chỉ email hợp lệ")
    password: str = Field(..., min_length=6, max_length=100, description="Mật khẩu tối thiểu 6 ký tự")
    role: Literal["student", "lecturer"] = Field(
        default="student", description="Vai trò: student (mặc định) hoặc lecturer"
    )


class UserLoginRequest(BaseModel):
    """Payload for user login."""
    email: EmailStr = Field(..., description="Email đăng nhập")
    password: str = Field(..., min_length=1, description="Mật khẩu đăng nhập")


class TokenResponse(BaseModel):
    """JWT Token response payload."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
