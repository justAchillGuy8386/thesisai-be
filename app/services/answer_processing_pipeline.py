import logging
import threading
from typing import Optional
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.answer import Answer
from app.models.job import ProcessingJob
from app.repositories.answer_repo import answer_repo
from app.repositories.question_repo import question_repo
from app.repositories.session_repo import session_repo
from app.repositories.project_repo import project_repo
from app.repositories.knowledge_profile_repo import knowledge_profile_repo
from app.services.stt_service import stt_service
from app.services.audio_analysis_service import audio_analysis_service
from app.services.evaluation_service import evaluation_service

logger = logging.getLogger(__name__)


class AnswerProcessingPipeline:
    """
    Asynchronous background pipeline for student defense answer recordings:
    1. Enforces sequential execution (max 1 heavy AI task at a time) via a process-wide
       lock so 16GB RAM systems never suffer OOM when students submit consecutive answers.
    2. Speech-to-Text (STT) via faster-whisper.
    3. Objective physical acoustic delivery analysis (WPM, pauses) via librosa.
    4. Multi-dimensional Rubric Evaluation via local Ollama LLM.
    5. Tracks lifecycle in `processing_jobs` table for auditability & truthful progress.
    """

    def __init__(self):
        self._worker_lock = threading.Lock()

    def _start_job(
        self,
        db: Session,
        session_id: Optional[int],
        answer_id: int,
        job_type: str,
    ) -> Optional[ProcessingJob]:
        if not session_id:
            return None
        try:
            job = ProcessingJob(
                session_id=session_id,
                answer_id=answer_id,
                job_type=job_type,
                status="running",
                attempt_count=1,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            return job
        except Exception as e:
            logger.warning(f"Could not create ProcessingJob ({job_type}) for Answer #{answer_id}: {e}")
            db.rollback()
            return None

    def _finish_job(
        self,
        db: Session,
        job: Optional[ProcessingJob],
        status: str,
        error_code: Optional[str] = None,
    ) -> None:
        if not job:
            return
        try:
            job.status = status
            if error_code:
                job.error_code = error_code[:100]
            db.commit()
        except Exception as e:
            logger.warning(f"Could not update ProcessingJob #{job.id}: {e}")
            db.rollback()

    def _build_dynamic_stt_prompt(self, db: Session, question) -> Optional[str]:
        """
        Build a concise, domain-agnostic Whisper initial_prompt grounded in the
        student's specific thesis title, major, Knowledge Profile methods/tools,
        and current question (kept under ~500 chars to fit Whisper's 224-token window).
        """
        if not question:
            return None
        try:
            session_obj = session_repo.get_by_id(db, question.session_id)
            project = (
                project_repo.get_by_id(db, session_obj.project_id)
                if session_obj
                else None
            )

            parts = []
            if project:
                title = (project.title or "").strip()
                major = (project.topic or "").strip()
                if title and major:
                    parts.append(f"Bảo vệ đồ án '{title}' (chuyên ngành {major}).")
                elif title:
                    parts.append(f"Bảo vệ đồ án '{title}'.")

                profile = knowledge_profile_repo.get_by_project_id(db, project.id)
                if profile and isinstance(profile.profile_json, dict):
                    methods = profile.profile_json.get("methodology_and_tech") or []
                    if methods:
                        methods_snippet = "; ".join(str(m).strip() for m in methods[:3])[:180]
                        parts.append(f"Thuật ngữ & phương pháp: {methods_snippet}.")

            q_topic = (question.topic_competency or "").strip()
            q_text = (question.question_text or "").strip()[:140]
            if q_text:
                prefix = f"Chủ đề {q_topic} — " if q_topic else ""
                parts.append(f"Câu hỏi: {prefix}{q_text}")

            prompt = " ".join(parts).strip()
            return prompt[:500] if prompt else None
        except Exception as e:
            logger.warning(f"Failed to build dynamic STT prompt: {e}")
            return None

    def process_answer(self, answer_id: int, db_session: Optional[Session] = None):
        """
        Background task worker executing STT, acoustic metrics, and LLM Rubric evaluation.
        Waits on `_worker_lock` while keeping answer status truthfully at 'queued'
        until its turn to run.
        """
        logger.info(f"Answer #{answer_id} waiting for sequential AI worker slot...")

        with self._worker_lock:
            logger.info(f"Acquired AI worker slot. Starting processing pipeline for Answer #{answer_id}...")
            self._run_pipeline_steps(answer_id=answer_id, db_session=db_session)

    def _run_pipeline_steps(self, answer_id: int, db_session: Optional[Session] = None):
        is_internal_session = False
        db = db_session
        if db is None:
            db = SessionLocal()
            is_internal_session = True

        answer: Optional[Answer] = None
        active_job: Optional[ProcessingJob] = None

        try:
            answer = answer_repo.get_by_id(db, answer_id)
            if not answer:
                logger.error(f"Answer #{answer_id} not found. Aborting processing pipeline.")
                return

            if answer.audio_status != "active" or not answer.audio_path:
                logger.warning(f"Answer #{answer_id} audio is not active or file path is missing.")
                return

            question = question_repo.get_by_id(db, answer.question_id)
            session_id = question.session_id if question else None

            # Step 1: Mark as transcribing & start STT job
            answer_repo.update_processing_status(db, answer, status="transcribing")
            logger.info(f"Answer #{answer_id} status updated to 'transcribing'.")
            active_job = self._start_job(db, session_id, answer.id, "stt")

            # Step 2: Speech-to-Text (STT) with dynamic thesis-grounded prompt
            dynamic_prompt = self._build_dynamic_stt_prompt(db, question)
            stt_result = stt_service.transcribe_audio(
                audio_path=answer.audio_path,
                language="vi",
                initial_prompt=dynamic_prompt,
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
            self._finish_job(db, active_job, status="succeeded")
            active_job = None
            logger.info(f"Answer #{answer_id} STT complete: {len(full_transcript.split())} words transcribed.")

            # Step 3: Audio Signal & Delivery Analysis
            active_job = self._start_job(db, session_id, answer.id, "audio_metrics")
            speech_metrics = audio_analysis_service.analyze_speech(
                audio_path=answer.audio_path,
                transcript=full_transcript,
            )

            existing_fields = dict(answer.error_fields or {})
            existing_fields.pop("error", None)
            existing_fields["speech_metrics"] = speech_metrics
            answer.error_fields = existing_fields
            self._finish_job(db, active_job, status="succeeded")
            active_job = None

            # Step 4: Advance status to 'evaluating' & start Evaluation job
            answer_repo.update_processing_status(db, answer, status="evaluating", error_fields=existing_fields)
            logger.info(
                f"Answer #{answer_id} status updated to 'evaluating' "
                f"(WPM: {speech_metrics.get('speaking_rate_wpm')}). Executing LLM Rubric Evaluation..."
            )
            active_job = self._start_job(db, session_id, answer.id, "evaluation")

            # Step 5: Execute LLM Rubric Evaluation Engine
            eval_record = evaluation_service.evaluate_answer(db=db, answer_id=answer.id)
            self._finish_job(db, active_job, status="succeeded")
            active_job = None

            # Step 6: Mark answer processing status as 'completed'
            answer_repo.update_processing_status(db, answer, status="completed", error_fields=existing_fields)
            logger.info(
                f"Answer #{answer_id} processing pipeline completed successfully! "
                f"Score: {eval_record.overall_score}/10 (Content: {eval_record.content_score}, Delivery: {eval_record.delivery_score})."
            )

        except Exception as e:
            logger.error(f"Error in processing pipeline for Answer #{answer_id}: {e}", exc_info=True)
            self._finish_job(db, active_job, status="failed", error_code=type(e).__name__)
            if answer:
                try:
                    existing_fields = dict(answer.error_fields or {})
                    existing_fields["error"] = str(e)
                    answer_repo.update_processing_status(
                        db,
                        answer,
                        status="failed",
                        error_fields=existing_fields,
                    )
                except Exception as db_err:
                    logger.error(f"Failed to record failure status in DB: {db_err}")
        finally:
            if is_internal_session:
                db.close()


# Global pipeline instance
answer_processing_pipeline = AnswerProcessingPipeline()

