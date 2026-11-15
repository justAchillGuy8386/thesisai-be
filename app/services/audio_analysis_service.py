import os
import logging
from typing import Dict, Any, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class AudioAnalysisService:
    """
    Audio signal analysis service using librosa to extract objective presentation metrics:
    - Speaking rate (Words Per Minute - WPM).
    - Natural fluency and hesitation pauses (> 1.5s).
    - Voiced speech ratio vs background silence.
    
    Ethics-by-Design:
    Strictly measures physical acoustic properties (timing, pauses, word rate).
    Does NOT infer subjective traits like confidence, honesty, or psychological emotions.
    """

    def analyze_speech(
        self,
        audio_path: str,
        transcript: str = "",
    ) -> Dict[str, Any]:
        """
        Analyze audio recording and compute objective academic delivery metrics.
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Tệp âm thanh '{audio_path}' không tồn tại.")

        try:
            import librosa

            # Load audio file (downsample to 16kHz mono for speech efficiency)
            y, sr = librosa.load(audio_path, sr=16000, mono=True)
            total_duration = round(float(librosa.get_duration(y=y, sr=sr)), 2)

            if total_duration < 0.5:
                return self._empty_analysis(total_duration)

            # 1. Voice Activity Detection (VAD) using split on 25dB threshold
            intervals = librosa.effects.split(y, top_db=25)
            
            voiced_duration = 0.0
            pauses: List[float] = []

            if len(intervals) > 0:
                voiced_duration = float(sum((end - start) / sr for start, end in intervals))
                
                # Measure pause lengths between successive speech chunks
                for i in range(len(intervals) - 1):
                    pause_sec = float((intervals[i + 1][0] - intervals[i][1]) / sr)
                    if pause_sec >= 0.3:  # Only count distinct pauses >= 300ms
                        pauses.append(round(pause_sec, 2))

            voiced_duration = round(min(voiced_duration, total_duration), 2)
            silence_duration = round(max(0.0, total_duration - voiced_duration), 2)
            silence_ratio = round(silence_duration / total_duration, 2) if total_duration > 0 else 0.0

            # Count hesitation / long pauses (>= 1.2 seconds)
            hesitation_pauses = [p for p in pauses if p >= 1.2]
            hesitation_count = len(hesitation_pauses)

            # 2. Words Per Minute (WPM)
            words = [w.strip() for w in transcript.split() if w.strip()]
            word_count = len(words)

            # Calculate WPM over voiced duration (or total duration if voiced is unavailable)
            effective_duration_minutes = (voiced_duration if voiced_duration > 3.0 else total_duration) / 60.0
            if effective_duration_minutes > 0 and word_count > 0:
                raw_wpm = word_count / effective_duration_minutes
                wpm = round(raw_wpm, 1)
            else:
                wpm = 0.0

            # 3. Academic Pace Assessment (100 - 140 WPM standard for Vietnamese thesis defense)
            if wpm == 0:
                pace_assessment = "Chưa phát hiện từ ngữ rõ ràng"
            elif wpm < 90:
                pace_assessment = "Tốc độ nói chậm, nhiều khoảng lặng"
            elif wpm <= 145:
                pace_assessment = "Tốc độ chuẩn học thuật, rõ ràng, dễ theo dõi"
            elif wpm <= 175:
                pace_assessment = "Tốc độ nói hơi nhanh, nên tiết chế để hội đồng nghe kịp"
            else:
                pace_assessment = "Tốc độ nói quá nhanh, cần ngắt nghỉ rõ ràng hơn"

            # 4. Objective Fluency Index (0 - 10 scale)
            fluency_index = self._calculate_fluency_index(
                total_duration=total_duration,
                silence_ratio=silence_ratio,
                hesitation_count=hesitation_count,
                wpm=wpm,
            )

            return {
                "total_duration_seconds": total_duration,
                "voiced_duration_seconds": voiced_duration,
                "silence_duration_seconds": silence_duration,
                "silence_ratio": silence_ratio,
                "total_words": word_count,
                "speaking_rate_wpm": wpm,
                "pace_assessment": pace_assessment,
                "hesitation_pauses_count": hesitation_count,
                "average_pause_seconds": round(float(np.mean(pauses)), 2) if pauses else 0.0,
                "fluency_score": fluency_index,
                "ethical_disclaimer": "Chỉ số được đo đạc khách quan theo tín hiệu vật lý âm thanh (tốc độ, độ dừng); không phán đoán cảm xúc hay sự tự tin.",
            }

        except Exception as e:
            logger.error(f"Error analyzing audio for '{audio_path}': {e}", exc_info=True)
            return self._empty_analysis(0.0, error=str(e))

    def _calculate_fluency_index(
        self,
        total_duration: float,
        silence_ratio: float,
        hesitation_count: int,
        wpm: float,
    ) -> float:
        """Calculate an objective delivery score from 0.0 to 10.0 based on physical rhythm."""
        if total_duration < 3.0 or wpm == 0:
            return 5.0

        score = 8.5  # Base healthy delivery score

        # Adjust for pace
        if 100 <= wpm <= 140:
            score += 1.5
        elif 90 <= wpm <= 155:
            score += 0.5
        elif wpm < 70 or wpm > 180:
            score -= 1.5

        # Penalize excessive hesitations (> 3 pauses over 1.5s per minute)
        duration_min = max(0.5, total_duration / 60.0)
        hesitations_per_min = hesitation_count / duration_min
        if hesitations_per_min > 4:
            score -= 2.0
        elif hesitations_per_min > 2:
            score -= 1.0

        # Penalize excessive dead silence (> 40% of presentation)
        if silence_ratio > 0.45:
            score -= 1.5

        return round(float(max(1.0, min(10.0, score))), 1)

    def _empty_analysis(self, duration: float, error: Optional[str] = None) -> Dict[str, Any]:
        return {
            "total_duration_seconds": duration,
            "voiced_duration_seconds": 0.0,
            "silence_duration_seconds": duration,
            "silence_ratio": 1.0,
            "total_words": 0,
            "speaking_rate_wpm": 0.0,
            "pace_assessment": "Chưa có dữ liệu phân tích âm thanh",
            "hesitation_pauses_count": 0,
            "average_pause_seconds": 0.0,
            "fluency_score": 5.0,
            "error": error,
            "ethical_disclaimer": "Chỉ số được đo đạc khách quan theo tín hiệu vật lý âm thanh (tốc độ, độ dừng); không phán đoán cảm xúc hay sự tự tin.",
        }


# Global singleton instance
audio_analysis_service = AudioAnalysisService()
