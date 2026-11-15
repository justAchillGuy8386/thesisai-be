import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.answer import Answer
from app.repositories.answer_repo import answer_repo
from app.services.stt_service import stt_service
from app.services.audio_analysis_service import audio_analysis_service

logger = logging.getLogger(__name__)


class AnswerProcessingPipeline:
    """
    Asynchronous background pipeline for student defense answer recordings:
    1. Speech-to-Text (STT) via faster-whisper.
    2. Objective physical acoustic delivery analysis (WPM, pauses) via librosa.
    3. Prepares context for Step 8.3 LLM Rubric Evaluation.
    """

    def process_answer(self, answer_id: int, db_session: Optional[Session] = None):
        """
        Background task worker executing STT and speech analytics.
        Uses provided session or opens a fresh database session.
        """
        logger.info(f"Starting asynchronous processing pipeline for Answer #{answer_id}...")

        is_internal_session = False
        db = db_session
        if db is None:
            db = SessionLocal()
            is_internal_session = True

        try:
            answer = answer_repo.get_by_id(db, answer_id)
            if not answer:
                logger.error(f"Answer #{answer_id} not found. Aborting processing pipeline.")
                return

            if answer.audio_status != "active" or not answer.audio_path:
                logger.warning(f"Answer #{answer_id} audio is not active or file path is missing.")
                return

            # Step 1: Mark as transcribing
            answer_repo.update_processing_status(db, answer, status="transcribing")
            logger.info(f"Answer #{answer_id} status updated to 'transcribing'.")

            # Step 2: Speech-to-Text (STT)
            stt_result = stt_service.transcribe_audio(
                audio_path=answer.audio_path,
                language="vi",
            )
            full_transcript = stt_result.get("full_text", "").strip()
            segments = stt_result.get("segments", [])
            audio_duration = stt_result.get("duration", answer.duration_seconds)

            answer.transcript = full_transcript
            answer.transcript_segments = segments
            if not answer.duration_seconds and audio_duration:
                answer.duration_seconds = audio_duration
            db.commit()
            db.refresh(answer)
            logger.info(f"Answer #{answer_id} STT complete: {len(full_transcript.split())} words transcribed.")

            # Step 3: Audio Signal & Delivery Analysis
            speech_metrics = audio_analysis_service.analyze_speech(
                audio_path=answer.audio_path,
                transcript=full_transcript,
            )

            # Store metrics in error_fields container temporarily for Step 8.3 integration
            existing_fields = answer.error_fields or {}
            existing_fields["speech_metrics"] = speech_metrics
            answer.error_fields = existing_fields

            # Step 4: Advance status to 'evaluating' (ready for Step 8.3 LLM Grading)
            answer_repo.update_processing_status(db, answer, status="evaluating", error_fields=existing_fields)
            logger.info(f"Answer #{answer_id} pipeline complete. Status transitioned to 'evaluating' (WPM: {speech_metrics.get('speaking_rate_wpm')}).")

        except Exception as e:
            logger.error(f"Error in processing pipeline for Answer #{answer_id}: {e}", exc_info=True)
            if answer:
                try:
                    answer_repo.update_processing_status(
                        db,
                        answer,
                        status="failed",
                        error_fields={"error": str(e)},
                    )
                except Exception as db_err:
                    logger.error(f"Failed to record failure status in DB: {db_err}")
        finally:
            if is_internal_session:
                db.close()


# Global pipeline instance
answer_processing_pipeline = AnswerProcessingPipeline()

