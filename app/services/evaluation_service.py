import json
import logging
import re
import time
from typing import Optional, Dict, Any, List
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.answer import Answer
from app.models.question import Question
from app.models.evaluation import AnswerEvaluation
from app.repositories.answer_repo import answer_repo
from app.repositories.question_repo import question_repo
from app.repositories.session_repo import session_repo
from app.repositories.project_repo import project_repo
from app.repositories.chunk_repo import chunk_repo
from app.repositories.evaluation_repo import evaluation_repo

logger = logging.getLogger(__name__)


class EvaluationService:
    """
    Dịch vụ chấm điểm và phản hồi đa chiều (Multi-dimensional Rubric Evaluation Engine):
    - Đánh giá Nội dung học thuật (Content Score - 80% trọng số) qua mô hình LLM cục bộ (Qwen2.5:7b).
    - Đánh giá Phong thái trình bày (Delivery Score - 20% trọng số) từ các chỉ số âm thanh thực tế (WPM, quãng ngập ngừng).
    - Cung cấp nhận xét mang tính xây dựng: Điểm mạnh, Thiếu sót, Hướng khắc phục, và Câu trả lời mẫu chuẩn.
    - Cơ chế Dự phòng quy tắc (Heuristic Fallback) đảm bảo hệ thống không bị crash nếu LLM quá tải.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 90.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout_seconds

    def evaluate_answer(
        self,
        db: Session,
        answer_id: int,
    ) -> AnswerEvaluation:
        """
        Thực thi quy trình đánh giá toàn diện cho câu trả lời của sinh viên.
        """
        start_time = time.time()
        logger.info(f"Bắt đầu quy trình đánh giá LLM Rubric cho Answer #{answer_id}...")

        answer = answer_repo.get_by_id(db, answer_id)
        if not answer:
            raise ValueError(f"Không tìm thấy câu trả lời #{answer_id}")

        question = question_repo.get_by_id(db, answer.question_id)
        if not question:
            raise ValueError(f"Không tìm thấy câu hỏi #{answer.question_id}")

        session_obj = session_repo.get_by_id(db, question.session_id)
        project = project_repo.get_by_id(db, session_obj.project_id) if session_obj else None

        transcript = (answer.transcript or "").strip()
        speech_metrics = (answer.error_fields or {}).get("speech_metrics", {})

        # 1. Tính toán Delivery Score (Phong thái - 20% trọng số)
        delivery_score, delivery_rubric = self._calculate_delivery_score(speech_metrics)

        # 2. Xử lý trường hợp không có nội dung phát biểu
        if not transcript or len(transcript.split()) < 3:
            logger.warning(f"Answer #{answer_id} không có nội dung phát biểu hợp lệ (transcript rỗng).")
            evaluation = evaluation_repo.create_or_update(
                db=db,
                answer_id=answer.id,
                overall_score=round(delivery_score * 0.2, 1),
                content_score=0.0,
                delivery_score=delivery_score,
                criterion_scores_json={
                    "technical_accuracy": 0.0,
                    "completeness": 0.0,
                    "reasoning_defense": 0.0,
                    "speech_pace": delivery_rubric.get("speech_pace", 0.0),
                    "fluency": delivery_rubric.get("fluency", 0.0),
                },
                feedback_json={
                    "strengths": [],
                    "weaknesses": ["Không phát hiện thấy phát biểu hoặc câu trả lời quá ngắn trong bản ghi âm."],
                    "suggestions": ["Hãy đảm bảo micro hoạt động tốt và trả lời rõ ràng, tự tin trước câu hỏi."],
                    "model_answer": question.expected_answer_outline,
                },
                evidence_json={"cited_chunk_ids": question.source_chunk_ids, "matched_keywords": []},
                model_metadata_json={
                    "model": self.model,
                    "evaluation_latency_seconds": round(time.time() - start_time, 2),
                    "disclaimer": "Đánh giá được tạo tự động bởi AI nhằm mục đích rèn luyện phản xạ bảo vệ đồ án tốt nghiệp.",
                },
            )
            return evaluation

        # 3. Thu thập tài liệu căn cứ (Provenance Chunks)
        source_chunks_text = []
        if question.source_chunk_ids:
            for cid in question.source_chunk_ids:
                chk = chunk_repo.get_by_id(db, cid)
                if chk and chk.text:
                    source_chunks_text.append(f"[Trang {chk.page_number}]: {chk.text[:300]}...")

        # 4. Gọi LLM để đánh giá Content Score (80% trọng số)
        llm_result = self._evaluate_with_llm(
            question=question,
            transcript=transcript,
            source_chunks=source_chunks_text,
            project_title=project.title if project else "Đồ án tốt nghiệp",
        )

        # 5. Tổng hợp điểm số Rubric
        tech_score = float(llm_result.get("technical_accuracy", 6.5))
        comp_score = float(llm_result.get("completeness", 6.0))
        reason_score = float(llm_result.get("reasoning_defense", 6.0))

        # Content score = 40% accuracy + 35% completeness + 25% reasoning
        content_score = round(tech_score * 0.40 + comp_score * 0.35 + reason_score * 0.25, 1)
        content_score = max(0.0, min(10.0, content_score))

        # Overall score = 80% content + 20% delivery
        overall_score = round(content_score * 0.80 + delivery_score * 0.20, 1)
        overall_score = max(0.0, min(10.0, overall_score))

        criterion_scores = {
            "technical_accuracy": tech_score,
            "completeness": comp_score,
            "reasoning_defense": reason_score,
            "speech_pace": delivery_rubric.get("speech_pace", 7.5),
            "fluency": delivery_rubric.get("fluency", 7.5),
        }

        feedback = {
            "strengths": llm_result.get("strengths", []),
            "weaknesses": llm_result.get("weaknesses", []),
            "suggestions": llm_result.get("suggestions", []),
            "model_answer": llm_result.get("model_answer", question.expected_answer_outline),
        }

        evidence = {
            "cited_chunk_ids": question.source_chunk_ids,
            "matched_keywords": self._extract_matching_keywords(transcript, question.expected_answer_outline),
        }

        latency = round(time.time() - start_time, 2)
        model_metadata = {
            "model": self.model,
            "evaluation_latency_seconds": latency,
            "is_fallback": llm_result.get("is_fallback", False),
            "disclaimer": "Đánh giá được tạo tự động bởi AI nhằm mục đích rèn luyện phản xạ bảo vệ đồ án tốt nghiệp, không thay thế nhận xét trực tiếp của Hội đồng Chuyên môn.",
        }

        # 6. Lưu vào cơ sở dữ liệu
        evaluation = evaluation_repo.create_or_update(
            db=db,
            answer_id=answer.id,
            overall_score=overall_score,
            content_score=content_score,
            delivery_score=delivery_score,
            criterion_scores_json=criterion_scores,
            feedback_json=feedback,
            evidence_json=evidence,
            model_metadata_json=model_metadata,
        )

        logger.info(
            f"Đã hoàn thành đánh giá Answer #{answer_id} trong {latency}s: "
            f"Overall={overall_score}/10 (Content={content_score}, Delivery={delivery_score})"
        )
        return evaluation

    def _calculate_delivery_score(self, speech_metrics: Dict[str, Any]) -> tuple[float, Dict[str, float]]:
        """
        Tính điểm phong thái trình bày (Delivery Score) từ các chỉ số đo lường vật lý.
        """
        if not speech_metrics:
            return 7.5, {"speech_pace": 7.5, "fluency": 7.5}

        wpm = speech_metrics.get("speaking_rate_wpm", 140.0)
        fluency_base = speech_metrics.get("fluency_score", 7.5)

        # Đánh giá tốc độ nói (chuẩn thuyết trình bảo vệ đồ án là 120-160 WPM)
        if 120 <= wpm <= 160:
            pace_score = 9.5
        elif 100 <= wpm < 120 or 160 < wpm <= 180:
            pace_score = 8.0
        elif 80 <= wpm < 100 or 180 < wpm <= 210:
            pace_score = 6.5
        else:
            pace_score = 5.0

        fluency_score = max(1.0, min(10.0, float(fluency_base)))
        delivery_score = round(pace_score * 0.5 + fluency_score * 0.5, 1)

        return delivery_score, {"speech_pace": pace_score, "fluency": fluency_score}

    def _evaluate_with_llm(
        self,
        question: Question,
        transcript: str,
        source_chunks: List[str],
        project_title: str,
    ) -> Dict[str, Any]:
        """
        Gửi prompt đến Qwen2.5:7b qua Ollama để chấm điểm chuyên môn và sinh nhận xét.
        Tự động kích hoạt Heuristic Fallback nếu LLM không phản hồi hoặc sinh lỗi.
        """
        system_prompt = (
            "Bạn là Giám khảo Phản biện của Hội đồng Chấm Đồ Án Tốt Nghiệp Đại học chuyên ngành Công nghệ Thông tin. "
            "Nhiệm vụ của bạn là đánh giá công tâm, khắt khe nhưng mang tính xây dựng đối với câu trả lời của sinh viên.\n\n"
            "Tiêu chí đánh giá nội dung (thang điểm 0.0 - 10.0):\n"
            "1. technical_accuracy (Độ chính xác kỹ thuật - 40% trọng số): Tính chính xác của các khái niệm, công nghệ, kiến trúc đã trình bày.\n"
            "2. completeness (Độ đầy đủ - 35% trọng số): Mức độ bao quát và trả lời đúng trọng tâm câu hỏi so với đáp án mong đợi.\n"
            "3. reasoning_defense (Lập luận bảo vệ & phản biện - 25% trọng số): Phân tích ưu/nhược điểm (trade-offs), lập luận logic, tự tin bảo vệ giải pháp.\n\n"
            "Định dạng phản hồi BẮT BUỘC: Bạn CHỈ ĐƯỢC XUẤT RA MỘT KHỐI JSON DUY NHẤT (không có lời mở đầu hay kết luận), tuân thủ định dạng sau:\n"
            "{\n"
            '  "technical_accuracy": 7.5,\n'
            '  "completeness": 7.0,\n'
            '  "reasoning_defense": 8.0,\n'
            '  "strengths": ["Nêu điểm mạnh 1", "Nêu điểm mạnh 2"],\n'
            '  "weaknesses": ["Nêu điểm còn thiếu sót hoặc nhầm lẫn 1"],\n'
            '  "suggestions": ["Gợi ý cải thiện cụ thể khi bảo vệ trước Hội đồng 1"],\n'
            '  "model_answer": "Đoạn văn ngắn gọn (2-4 câu) diễn đạt câu trả lời chuẩn mực mà sinh viên nên tham khảo."\n'
            "}"
        )

        user_content = (
            f"=== ĐỀ TÀI ĐỒ ÁN ===\n{project_title}\n\n"
            f"=== CÂU HỎI PHẢN BIỆN (Mức độ: {question.difficulty.upper()} | Chủ đề: {question.topic_competency}) ===\n"
            f"{question.question_text}\n\n"
            f"=== ĐỀ CƯƠNG ĐÁP ÁN MONG ĐỢI TỪ TÀI LIỆU ===\n"
            f"{question.expected_answer_outline}\n\n"
        )

        if source_chunks:
            user_content += f"=== TRÍCH DẪN LUẬN VĂN CĂN CỨ ===\n" + "\n".join(source_chunks) + "\n\n"

        user_content += (
            f"=== BẢN GHI LỜI NÓI CỦA SINH VIÊN (TRANSCRIPT) ===\n"
            f"{transcript}\n\n"
            f"Hãy đóng vai trò giám khảo, chấm điểm chi tiết và xuất JSON đánh giá."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 1200,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                res_json = resp.json()
                raw_text = res_json.get("message", {}).get("content", "").strip()

            parsed = self._extract_json(raw_text)
            if parsed and "technical_accuracy" in parsed:
                parsed["is_fallback"] = False
                return parsed
            else:
                logger.warning(f"LLM không trả về JSON hợp lệ: {raw_text[:200]}. Sử dụng Heuristic Fallback.")
        except Exception as e:
            logger.warning(f"Không thể kết nối hoặc nhận phản hồi từ Ollama ({e}). Sử dụng Heuristic Fallback.")

        # Fallback khi LLM gặp sự cố
        return self._heuristic_fallback_evaluation(question, transcript)

    def _heuristic_fallback_evaluation(self, question: Question, transcript: str) -> Dict[str, Any]:
        """
        Quy tắc chấm điểm dự phòng dựa trên phân tích từ vựng và độ tương đồng ngữ nghĩa
        để bảo đảm hệ thống luôn hoạt động ổn định 100%.
        """
        words = transcript.lower().split()
        word_count = len(words)

        matched_kws = self._extract_matching_keywords(transcript, question.expected_answer_outline)
        kw_ratio = min(1.0, len(matched_kws) / max(3, len(question.expected_answer_outline.split()) // 5))

        # Ước lượng điểm
        if word_count < 20:
            tech = 5.0 + kw_ratio * 2.0
            comp = 4.5 + kw_ratio * 2.0
            reason = 4.5
            weakness = "Câu trả lời quá vắn tắt, chưa làm rõ các luận điểm kỹ thuật then chốt."
        elif word_count < 60:
            tech = 6.5 + kw_ratio * 2.0
            comp = 6.0 + kw_ratio * 2.5
            reason = 6.0
            weakness = "Cần mở rộng phân tích các giải pháp thay thế và lý do lựa chọn kiến trúc."
        else:
            tech = 7.5 + kw_ratio * 2.0
            comp = 7.5 + kw_ratio * 2.0
            reason = 7.0 + kw_ratio * 2.0
            weakness = "Cần cô đọng các thuật ngữ kỹ thuật chính xác hơn để trả lời dứt khoát."

        tech = min(9.5, max(4.0, tech))
        comp = min(9.5, max(4.0, comp))
        reason = min(9.5, max(4.0, reason))

        return {
            "technical_accuracy": round(tech, 1),
            "completeness": round(comp, 1),
            "reasoning_defense": round(reason, 1),
            "strengths": [
                "Sinh viên nắm được hướng tiếp cận chính của câu hỏi.",
                f"Đã đề cập đến các từ khóa chuyên môn quan trọng ({', '.join(matched_kws[:3]) if matched_kws else 'thuật ngữ nền tảng'}).",
            ],
            "weaknesses": [weakness],
            "suggestions": [
                "Nên trả lời trực diện vào luận điểm trước, sau đó dẫn chứng số liệu hoặc cơ chế thực thi cụ thể.",
                "Cần chuẩn bị phương án so sánh trade-off với các giải pháp công nghệ phổ biến khác.",
            ],
            "model_answer": question.expected_answer_outline,
            "is_fallback": True,
        }

    def _extract_matching_keywords(self, transcript: str, outline: str) -> List[str]:
        """Trích xuất các từ khóa học thuật/kỹ thuật chung giữa câu trả lời và đề cương."""
        stopwords = {
            "và", "là", "của", "trong", "để", "với", "các", "những", "cho", "về",
            "được", "có", "này", "đó", "một", "theo", "khi", "như", "em", "thầy",
            "cô", "xin", "dạ", "ạ", "thì", "mà", "sẽ", "tại", "từ", "ra", "vào"
        }
        words_tr = set(re.findall(r"\b[a-zA-ZÀ-ỹ0-9_]{3,}\b", transcript.lower()))
        words_out = set(re.findall(r"\b[a-zA-ZÀ-ỹ0-9_]{3,}\b", outline.lower()))

        matched = [w for w in (words_tr & words_out) if w not in stopwords]
        return sorted(matched)[:8]

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Bóc tách JSON an toàn từ nội dung sinh ra của LLM."""
        if not text:
            return None

        # 1. Tìm khối ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Tìm khối {...} lớn nhất
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = text[first_brace : last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        return None


evaluation_service = EvaluationService()

