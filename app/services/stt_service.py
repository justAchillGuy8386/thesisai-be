import os
import logging
import threading
from typing import Dict, Any, List, Optional
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


class STTService:
    """
    Speech-to-Text service using faster-whisper on local CPU (int8 quantization).
    Transcribes Vietnamese graduation defense audio recordings with word/segment timestamps.
    """

    def __init__(self, model_size: Optional[str] = None):
        self.model_size = model_size or getattr(settings, "WHISPER_MODEL", "large-v3-turbo")
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        """Lazy load faster-whisper model to keep initial server startup instant."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    logger.info(
                        f"Loading faster-whisper model '{self.model_size}' (device=cpu, compute_type=int8, cpu_threads=6)..."
                    )
                    self._model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=6,
                    )
                    logger.info("faster-whisper model loaded successfully.")
        return self._model

    def transcribe_audio(
        self,
        audio_path: str,
        language: str = "vi",
        beam_size: int = 5,
        initial_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transcribe an audio file into text and segment timestamps.
        Returns full text, language metadata, and segmented intervals.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Tệp âm thanh '{audio_path}' không tồn tại.")

        file_size = os.path.getsize(audio_path)
        if file_size < 100:
            raise ValueError("Tệp âm thanh quá ngắn hoặc không có dữ liệu.")

        prompt = (
            initial_prompt
            or "Đây là buổi thuyết trình và trả lời phản biện đồ án hoặc khóa luận tốt nghiệp đại học. Sinh viên giải trình phương pháp nghiên cứu, cơ sở lý thuyết, số liệu phân tích và kết quả thực nghiệm trước Hội đồng chuyên môn."
        )

        try:
            model = self._get_model()
            segments_gen, info = model.transcribe(
                audio_path,
                language=language,
                beam_size=beam_size,
                initial_prompt=prompt,
                condition_on_previous_text=False,  # Prevent hallucination drift after pauses
                vad_filter=True,  # Filter out background noise & non-speech
                vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=250),
            )

            segments: List[Dict[str, Any]] = []
            text_parts: List[str] = []

            for s in segments_gen:
                clean_text = s.text.strip()
                if clean_text:
                    segments.append(
                        {
                            "id": s.id,
                            "start": round(s.start, 2),
                            "end": round(s.end, 2),
                            "text": clean_text,
                            "avg_logprob": round(s.avg_logprob, 3),
                        }
                    )
                    text_parts.append(clean_text)

            full_text = " ".join(text_parts).strip()

            return {
                "full_text": full_text,
                "language": getattr(info, "language", language),
                "language_probability": round(getattr(info, "language_probability", 1.0), 3),
                "duration": round(getattr(info, "duration", 0.0), 2),
                "segments": segments,
            }

        except Exception as e:
            logger.error(f"Error during speech transcription for '{audio_path}': {e}", exc_info=True)
            raise


# Global singleton instance
stt_service = STTService()

