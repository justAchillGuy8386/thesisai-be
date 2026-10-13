from enum import Enum


class UserRole(str, Enum):
    STUDENT = "student"
    LECTURER = "lecturer"
    ADMIN = "admin"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"        # Đã tải lên
    EXTRACTING = "extracting"    # Đang đọc tài liệu
    INDEXING = "indexing"        # Đang chuẩn bị dữ liệu
    READY = "ready"              # Sẵn sàng
    FAILED = "failed"            # Xử lý thất bại


class PracticeMode(str, Enum):
    QUESTION_ANSWER = "question_answer"      # Mode A (Hỏi đáp từng câu)
    FULL_PRESENTATION = "full_presentation"  # Mode B (Thuyết trình slide)


class SessionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"


class AnswerStatus(str, Enum):
    QUEUED = "queued"              # Đang chờ xử lý
    TRANSCRIBING = "transcribing"  # Đang chuyển giọng nói thành văn bản
    EVALUATING = "evaluating"      # Đang đánh giá câu trả lời
    COMPLETED = "completed"        # Hoàn tất
    FAILED = "failed"              # Xử lý thất bại


class JobType(str, Enum):
    STT = "stt"
    EVALUATION = "evaluation"
    AUDIO_METRICS = "audio_metrics"
