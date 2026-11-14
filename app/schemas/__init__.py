from app.schemas.auth import (
    UserResponse,
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
)
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectResponse,
    LecturerSimpleResponse,
)
from app.schemas.document import (
    DocumentResponse,
    DocumentListResponse,
)
from app.schemas.question import (
    QuestionDifficulty,
    GeneratedQuestionItem,
    GeneratedQuestionSet,
    QuestionResponse,
)

__all__ = [
    "UserResponse",
    "UserRegisterRequest",
    "UserLoginRequest",
    "TokenResponse",
    "ProjectCreateRequest",
    "ProjectUpdateRequest",
    "ProjectResponse",
    "LecturerSimpleResponse",
    "DocumentResponse",
    "DocumentListResponse",
    "QuestionDifficulty",
    "GeneratedQuestionItem",
    "GeneratedQuestionSet",
    "QuestionResponse",
]
