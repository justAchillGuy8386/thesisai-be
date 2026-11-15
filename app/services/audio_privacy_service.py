import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.answer import Answer

logger = logging.getLogger(__name__)


class AudioPrivacyService:
    """
    Dịch vụ quản lý vòng đời tệp âm thanh theo chuẩn Privacy-by-Design:
    - Tự động tiêu hủy các tệp ghi âm giọng nói vượt quá thời gian lưu giữ (AUDIO_RETENTION_HOURS - 24 giờ).
    - Hỗ trợ tiêu hủy tức thì (on-demand) theo yêu cầu của sinh viên.
    - Bảo toàn 100% nội dung transcript văn bản và kết quả đánh giá LLM để sinh viên tra cứu vĩnh viễn.
    """

    def purge_expired_audio_recordings(
        self,
        db: Session,
        retention_hours: Optional[int] = None,
    ) -> int:
        """
        Quét và xóa triệt để các tệp ghi âm đã hết hạn trên máy chủ cục bộ.
        """
        hours = retention_hours if retention_hours is not None else settings.AUDIO_RETENTION_HOURS
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        expired_answers = (
            db.query(Answer)
            .filter(
                Answer.audio_status == "active",
                Answer.audio_path.isnot(None),
                Answer.created_at <= cutoff_time,
            )
            .all()
        )

        purged_count = 0
        for ans in expired_answers:
            try:
                if ans.audio_path and os.path.exists(ans.audio_path):
                    file_path = Path(ans.audio_path)
                    file_path.unlink(missing_ok=True)
                    # Cleanup parent folder if empty
                    parent_dir = file_path.parent
                    if parent_dir.exists() and not any(parent_dir.iterdir()):
                        parent_dir.rmdir()

                ans.audio_path = None
                ans.audio_status = "purged"
                ans.audio_purged_at = datetime.utcnow()
                purged_count += 1
            except Exception as e:
                logger.error(f"Lỗi khi tiêu hủy file âm thanh của Answer #{ans.id}: {e}")

        if purged_count > 0:
            db.commit()
            logger.info(f"Chính sách Privacy-by-Design: Đã tiêu hủy thành công {purged_count} tệp ghi âm hết hạn (> {hours}h).")

        return purged_count

    def purge_single_answer_audio(self, db: Session, answer: Answer) -> bool:
        """
        Tiêu hủy ngay lập tức tệp âm thanh của một câu trả lời cụ thể.
        """
        if answer.audio_status == "purged":
            return True

        try:
            if answer.audio_path and os.path.exists(answer.audio_path):
                file_path = Path(answer.audio_path)
                file_path.unlink(missing_ok=True)
                parent_dir = file_path.parent
                if parent_dir.exists() and not any(parent_dir.iterdir()):
                    parent_dir.rmdir()

            answer.audio_path = None
            answer.audio_status = "purged"
            answer.audio_purged_at = datetime.utcnow()
            db.commit()
            db.refresh(answer)
            logger.info(f"Privacy-by-Design: Đã tiêu hủy tệp âm thanh của Answer #{answer.id} theo yêu cầu.")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi tiêu hủy file âm thanh Answer #{answer.id}: {e}")
            db.rollback()
            return False


audio_privacy_service = AudioPrivacyService()

