import json
import logging
import re
from typing import List, Optional, Dict, Any
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.project import ThesisProject
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_profile import ProjectKnowledgeProfile
from app.schemas.question import (
    QuestionDifficulty,
    GeneratedQuestionItem,
    GeneratedQuestionSet,
)
from app.schemas.knowledge_profile import KnowledgeProfileData
from app.repositories.project_repo import project_repo
from app.repositories.chunk_repo import chunk_repo
from app.repositories.knowledge_profile_repo import knowledge_profile_repo
from app.services.knowledge_profile_service import knowledge_profile_service

logger = logging.getLogger(__name__)


class QuestionGeneratorService:
    """
    Service to generate balanced, academic graduation defense practice questions (12-15 questions)
    categorized into Easy, Medium, and Hard tiers, complete with expected answer outlines
    and grounded document chunk provenance.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 300.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout_seconds

    def generate_questions_for_project(
        self,
        db: Session,
        project_id: int,
        target_count: int = 12,
    ) -> GeneratedQuestionSet:
        """
        Generates 12-14 defense questions for a thesis project based on its Knowledge Profile
        and representative document chunks.
        """
        project = project_repo.get_by_id(db, project_id)
        if not project:
            raise ValueError(f"Project #{project_id} không tồn tại.")

        # 1. Fetch active chunks
        active_chunks = chunk_repo.get_active_chunks_by_project(db, project_id)
        if not active_chunks:
            raise ValueError("Đề tài chưa có tài liệu nào được xử lý để sinh bộ câu hỏi.")

        # 2. Get or generate Knowledge Profile
        profile = knowledge_profile_repo.get_by_project_id(db, project_id)
        if not profile or profile.status != "ready" or not profile.profile_json:
            logger.info(f"Knowledge Profile for project {project_id} is not ready. Attempting to generate...")
            try:
                profile = knowledge_profile_service.generate_profile(db, project_id)
            except Exception as e:
                logger.warning(f"Failed to auto-generate Knowledge Profile: {e}")

        profile_data: Optional[KnowledgeProfileData] = None
        if profile and profile.profile_json:
            try:
                profile_data = KnowledgeProfileData(**profile.profile_json)
            except Exception as e:
                logger.warning(f"Error parsing profile JSON for project {project_id}: {e}")

        # 3. Select representative chunks for context & citation grounding
        sample_chunks = self._select_representative_chunks(active_chunks, max_chunks=12)

        # 4. Attempt LLM generation with fallback
        questions: List[GeneratedQuestionItem] = []
        try:
            questions = self._call_ollama_generate_questions(
                project=project,
                profile_data=profile_data,
                chunks=sample_chunks,
                target_count=target_count,
            )
        except Exception as e:
            logger.warning(f"Ollama question generation encountered error: {e}. Falling back to heuristic generator.")

        # 5. Fallback or augment if LLM returned insufficient questions
        if not questions or len(questions) < 6:
            logger.info(f"Using robust heuristic question generator for project #{project_id}.")
            questions = self._build_heuristic_questions(
                project=project,
                profile_data=profile_data,
                chunks=sample_chunks,
                target_count=target_count,
            )

        # 6. Re-index orders contiguously and compile statistics
        for idx, q in enumerate(questions, start=1):
            q.order_index = idx

        easy_cnt = sum(1 for q in questions if q.difficulty == QuestionDifficulty.EASY)
        med_cnt = sum(1 for q in questions if q.difficulty == QuestionDifficulty.MEDIUM)
        hard_cnt = sum(1 for q in questions if q.difficulty == QuestionDifficulty.HARD)

        return GeneratedQuestionSet(
            project_id=project_id,
            questions=questions,
            total_questions=len(questions),
            easy_count=easy_cnt,
            medium_count=med_cnt,
            hard_count=hard_cnt,
        )

    def _select_representative_chunks(
        self,
        chunks: List[DocumentChunk],
        max_chunks: int = 12,
    ) -> List[DocumentChunk]:
        """Select a diverse cross-section of chunks across the thesis chapters."""
        if len(chunks) <= max_chunks:
            return chunks

        # Prioritize key academic sections if available
        key_keywords = [
            "tổng quan", "mục tiêu", "giải pháp", "kiến trúc", "thiết kế",
            "cơ sở dữ liệu", "bảo mật", "quy trình", "nghiệp vụ", "kết quả", "hạn chế"
        ]
        priority_chunks: List[DocumentChunk] = []
        other_chunks: List[DocumentChunk] = []

        for c in chunks:
            text_lower = (c.text or "").lower()
            section_lower = (c.section_title or "").lower()
            if any(k in section_lower or k in text_lower[:100] for k in key_keywords):
                priority_chunks.append(c)
            else:
                other_chunks.append(c)

        selected = priority_chunks[:max_chunks]
        if len(selected) < max_chunks:
            # Step evenly through other chunks
            needed = max_chunks - len(selected)
            step = max(1, len(other_chunks) // needed)
            for i in range(0, len(other_chunks), step):
                if len(selected) >= max_chunks:
                    break
                selected.append(other_chunks[i])

        return selected

    def _call_ollama_generate_questions(
        self,
        project: ThesisProject,
        profile_data: Optional[KnowledgeProfileData],
        chunks: List[DocumentChunk],
        target_count: int = 12,
    ) -> List[GeneratedQuestionItem]:
        """Query local Ollama LLM to produce structured question JSON."""
        system_prompt = (
            "Bạn là Chuyên gia Khảo thí và Giảng viên Thư ký Hội đồng Chấm Đồ Án Tốt Nghiệp Đại Học.\n"
            "Nhiệm vụ của bạn là đọc thông tin đồ án và tài liệu trích dẫn để sinh bộ câu hỏi bảo vệ (~12 câu) "
            "phân tầng độ khó chuẩn mực (Dễ: ~3-4 câu, Trung bình: ~5-6 câu, Khó: ~3-4 câu).\n\n"
            "YÊU CẦU BẮT BUỘC:\n"
            "1. Phân bổ độ khó:\n"
            "   - 'easy': Tổng quan đề tài, bài toán thực tế, lý do chọn đề tài, đối tượng người dùng, phạm vi nghiên cứu.\n"
            "   - 'medium': Thiết kế kiến trúc, công nghệ đã chọn và lý do so sánh, lược đồ CSDL/mô hình dữ liệu, luồng nghiệp vụ chính, thiết kế API.\n"
            "   - 'hard': Khả năng chịu tải và scale, xử lý đồng thời (concurrency/race conditions), bảo mật & xác thực, ngoại lệ & rollback, hạn chế lớn nhất và hướng phát triển.\n"
            "2. Mỗi câu hỏi PHẢI CÓ:\n"
            "   - 'order_index': Thứ tự từ 1 đến N\n"
            "   - 'question_text': Câu hỏi ngắn gọn, sâu sắc, mang phong thái hội đồng phản biện học thuật\n"
            "   - 'difficulty': 'easy' | 'medium' | 'hard'\n"
            "   - 'topic_competency': Tên lĩnh vực chuyên môn (VD: 'Kiến trúc hệ thống', 'Cơ sở dữ liệu', 'Bảo mật', 'Quy trình nghiệp vụ')\n"
            "   - 'expected_answer_outline': Dàn ý gợi ý 2-3 gạch đầu dòng rõ ràng (- Ý 1...\\n- Ý 2...\\n- Ý 3...), chỉ rõ các luận điểm kỹ thuật then chốt sinh viên nên trả lời để đạt điểm tối đa\n"
            "   - 'source_chunk_ids': Mảng các số nguyên chunk_id có liên quan được cung cấp bên dưới\n"
            "   - 'recommended_seconds': 120\n"
            "3. TRẢ VỀ DUY NHẤT 1 ĐỐI TƯỢNG JSON có key 'questions', TUYỆT ĐỐI KHÔNG VIẾT CHỮ NÀO KHÁC NGOÀI JSON.\n"
            "Ví dụ định dạng:\n"
            "{\n"
            '  "questions": [\n'
            '    {\n'
            '      "order_index": 1,\n'
            '      "question_text": "Mục tiêu nghiên cứu chính của đề tài là gì và giải pháp kỹ thuật bạn xây dựng giải quyết bài toán thực tế nào?",\n'
            '      "difficulty": "easy",\n'
            '      "topic_competency": "Tổng quan đề tài",\n'
            '      "expected_answer_outline": "- Nêu rõ bối cảnh thực tế và lý do lựa chọn phát triển hệ thống.\\n- Trình bày 2-3 mục tiêu định lượng cốt lõi mà giải pháp kỹ thuật đã hoàn thành.\\n- Khẳng định giá trị thực tiễn mang lại cho người dùng mục tiêu.",\n'
            '      "source_chunk_ids": [101],\n'
            '      "recommended_seconds": 120\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        # Context builder
        context_parts = [
            f"=== THÔNG TIN ĐỀ TÀI ===",
            f"Tên đề tài: {project.title}",
            f"Chuyên ngành / Lĩnh vực: {project.topic or 'Chưa phân loại'}",
        ]

        if profile_data:
            context_parts.append("\n=== HỒ SƠ TRI THỨC ĐỒ ÁN (ĐÃ TỔNG HỢP) ===")
            context_parts.append(f"Tóm tắt: {profile_data.summary}")
            if profile_data.objectives:
                context_parts.append(f"Mục tiêu: {'; '.join(profile_data.objectives)}")
            if profile_data.methodology_and_tech:
                context_parts.append(f"Kiến trúc & Công nghệ: {'; '.join(profile_data.methodology_and_tech)}")
            if profile_data.defense_weaknesses:
                context_parts.append(f"Điểm yếu tiềm ẩn: {'; '.join(profile_data.defense_weaknesses)}")

        context_parts.append("\n=== CÁC ĐOẠN TRÍCH TÀI LIỆU CĂN CỨ (CHUNKS) ===")
        valid_chunk_ids = []
        for c in chunks:
            valid_chunk_ids.append(c.id)
            preview = (c.text or "").replace("\n", " ")[:200]
            context_parts.append(f"- [Chunk #{c.id} | Trang {c.page_number} | Mục: {c.section_title}]: {preview}...")

        user_content = (
            f"{chr(10).join(context_parts)}\n\n"
            f"Hãy sinh đúng {target_count} câu hỏi phản biện bảo vệ (khoảng 3-4 câu easy, 5-6 câu medium, 3-4 câu hard) "
            f"dưới dạng JSON hợp lệ."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {
                "temperature": 0.8,
                "num_predict": 2200,
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            res_json = resp.json()
            raw_content = res_json.get("message", {}).get("content", "").strip()

        # Parse JSON from content
        parsed_data = self._extract_json(raw_content)
        if not parsed_data or "questions" not in parsed_data:
            logger.warning(f"LLM did not return 'questions' key. Raw output: {raw_content[:200]}")
            return []

        raw_questions = parsed_data.get("questions", [])
        validated_items: List[GeneratedQuestionItem] = []

        for item in raw_questions:
            try:
                diff_str = str(item.get("difficulty", "medium")).lower().strip()
                if "easy" in diff_str or "dễ" in diff_str:
                    difficulty = QuestionDifficulty.EASY
                elif "hard" in diff_str or "khó" in diff_str or "cao" in diff_str:
                    difficulty = QuestionDifficulty.HARD
                else:
                    difficulty = QuestionDifficulty.MEDIUM

                # Sanitize source_chunk_ids
                c_ids = item.get("source_chunk_ids", [])
                clean_chunk_ids = [int(cid) for cid in c_ids if isinstance(cid, (int, str)) and str(cid).isdigit()]
                if not clean_chunk_ids:
                    # Default to closest chunk from provided sample
                    clean_chunk_ids = [chunks[0].id] if chunks else []

                q_item = GeneratedQuestionItem(
                    order_index=int(item.get("order_index", len(validated_items) + 1)),
                    question_text=str(item.get("question_text", "")).strip(),
                    difficulty=difficulty,
                    topic_competency=str(item.get("topic_competency", "Kiến thức chuyên môn")).strip(),
                    expected_answer_outline=str(item.get("expected_answer_outline", "")).strip(),
                    source_chunk_ids=clean_chunk_ids,
                    recommended_seconds=int(item.get("recommended_seconds", 120)),
                )
                if q_item.question_text and len(q_item.question_text) > 10:
                    validated_items.append(q_item)
            except Exception as parse_err:
                logger.warning(f"Error parsing question item: {parse_err}")

        return validated_items

    def _build_heuristic_questions(
        self,
        project: ThesisProject,
        profile_data: Optional[KnowledgeProfileData],
        chunks: List[DocumentChunk],
        target_count: int = 12,
    ) -> List[GeneratedQuestionItem]:
        """
        Guaranteed academic question set derived deterministically from project topic,
        knowledge profile, and grounded chunks.
        """
        title = project.title
        tech_list = profile_data.methodology_and_tech if profile_data and profile_data.methodology_and_tech else []
        tech_str = ", ".join(tech_list[:4]) if tech_list else "các công nghệ đã chọn trong đồ án"
        weakness_list = profile_data.defense_weaknesses if profile_data and profile_data.defense_weaknesses else []
        weakness_str = weakness_list[0] if weakness_list else "khả năng mở rộng và chịu tải cao"

        chunk_ids = [c.id for c in chunks]
        c_p1 = chunk_ids[:2] if len(chunk_ids) >= 2 else chunk_ids
        c_p2 = chunk_ids[2:5] if len(chunk_ids) >= 5 else chunk_ids
        c_p3 = chunk_ids[5:8] if len(chunk_ids) >= 8 else chunk_ids
        c_p4 = chunk_ids[8:] if len(chunk_ids) >= 9 else chunk_ids

        # 12 Grounded Academic Questions
        templates = [
            # --- EASY (3 câu) ---
            {
                "difficulty": QuestionDifficulty.EASY,
                "topic": "Tổng quan & Tính cấp thiết",
                "text": f"Bạn hãy trình bày tóm tắt mục tiêu nghiên cứu và tính cấp thiết thực tiễn của đề tài '{title}'?",
                "outline": (
                    "- Nêu rõ bối cảnh và lý do chọn đề tài (vấn đề thực tế cần giải quyết).\n"
                    "- Nêu 2-3 mục tiêu cốt lõi mà sản phẩm/nghiên cứu hướng tới.\n"
                    "- Khẳng định giá trị thực tiễn mang lại cho đối tượng người dùng mục tiêu."
                ),
                "chunks": c_p1,
            },
            {
                "difficulty": QuestionDifficulty.EASY,
                "topic": "Phạm vi & Đối tượng sử dụng",
                "text": "Phạm vi nghiên cứu của đồ án được giới hạn như thế nào? Những chức năng nào thuộc phạm vi triển khai và chức năng nào nằm ngoài phạm vi nghiên cứu?",
                "outline": (
                    "- Liệt kê rõ ranh giới nghiên cứu (Boundary) của đề tài.\n"
                    "- Nêu rõ các phân hệ/module đã hoàn thành và hoạt động tốt.\n"
                    "- Thẳng thắn chỉ ra các tính năng nâng cao chưa thực hiện do giới hạn thời gian/nguồn lực."
                ),
                "chunks": c_p1,
            },
            {
                "difficulty": QuestionDifficulty.EASY,
                "topic": "Khảo sát hiện trạng & So sánh",
                "text": "Trong quá trình khảo sát thực tế, bạn nhận thấy các giải pháp hiện có trên thị trường có những hạn chế gì dẫn đến việc bạn quyết định xây dựng giải pháp này?",
                "outline": (
                    "- Chỉ ra 1-2 sản phẩm hoặc giải pháp tương tự trên thị trường.\n"
                    "- Phân tích ưu/nhược điểm của các giải pháp đó (chi phí, độ phức tạp, tính đặc thù).\n"
                    "- Nêu rõ điểm khác biệt hoặc cải tiến mà đề tài của bạn mang lại."
                ),
                "chunks": c_p1,
            },

            # --- MEDIUM (6 câu) ---
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Kiến trúc hệ thống & Lựa chọn công nghệ",
                "text": f"Hãy phân tích kiến trúc tổng thể của hệ thống và lý do bạn lựa chọn {tech_str} thay vì các giải pháp công nghệ tương đương khác?",
                "outline": (
                    "- Mô tả mô hình kiến trúc phân tầng (Presentation, Business Logic, Data Access).\n"
                    "- Giải thích cơ sở lựa chọn công nghệ dựa trên: tốc độ phát triển, cộng đồng hỗ trợ, hiệu năng và tính phù hợp với bài toán.\n"
                    "- Nêu được sự đánh đổi (Trade-off) khi chọn công nghệ này."
                ),
                "chunks": c_p2,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Thiết kế Cơ sở dữ liệu",
                "text": "Thiết kế cơ sở dữ liệu quan hệ của hệ thống đã đạt chuẩn hóa bậc mấy (3NF)? Các bảng thực thể quan trọng nhất và quan hệ khóa ngoại giữa chúng được thiết lập ra sao?",
                "outline": (
                    "- Khẳng định mức độ chuẩn hóa CSDL (thường là chuẩn 3NF).\n"
                    "- Nêu tên và vai trò của 3-4 bảng trung tâm (User, Order, Product, Transaction...).\n"
                    "- Giải thích cách thiết lập ràng buộc toàn vẹn khóa ngoại (Foreign Key) và index hỗ trợ tìm kiếm."
                ),
                "chunks": c_p2,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Luồng xử lý nghiệp vụ cốt lõi",
                "text": "Trình bày chi tiết luồng xử lý của một quy trình nghiệp vụ quan trọng nhất trong đồ án từ khi người dùng thao tác đến khi dữ liệu được xác nhận thành công vào cơ sở dữ liệu?",
                "outline": (
                    "- Mô tả từng bước của luồng xử lý theo trình tự thời gian.\n"
                    "- Giải thích cơ chế validation dữ liệu ở cả client và server.\n"
                    "- Nêu rõ điểm kết thúc: cập nhật trạng thái trong database và thông báo phản hồi cho người dùng."
                ),
                "chunks": c_p3,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Thiết kế & Kiểm thử API",
                "text": "Hệ thống thiết kế các giao diện lập trình ứng dụng (API) theo chuẩn nào? Bạn đã tổ chức kiểm thử chức năng và kiểm thử API (Testing) như thế nào?",
                "outline": (
                    "- Trình bày chuẩn RESTful API: các phương thức HTTP (GET, POST, PUT, DELETE) và mã trạng thái (200, 201, 400, 404, 500).\n"
                    "- Trình bày công cụ kiểm thử đã sử dụng (Postman, Swagger, Unit Tests).\n"
                    "- Nêu các ca kiểm thử chính (Happy case và Error case)."
                ),
                "chunks": c_p3,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Xác thực & Phân quyền người dùng",
                "text": "Cơ chế xác thực (Authentication) và phân quyền (Authorization) trong hệ thống được hiện thực hóa như thế nào để ngăn chặn hành vi leo quyền trái phép?",
                "outline": (
                    "- Giải thích cơ chế mã hóa mật khẩu (Bcrypt/Argon2) và quản lý phiên (JWT hoặc Session).\n"
                    "- Nêu cơ chế Middleware kiểm tra vai trò người dùng (Role-based access control - RBAC).\n"
                    "- Giải thích cách bảo vệ dữ liệu tài nguyên: người dùng chỉ được xem/sửa tài nguyên thuộc sở hữu của mình."
                ),
                "chunks": c_p3,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Tích hợp dịch vụ bên thứ ba",
                "text": "Hệ thống có tích hợp các dịch vụ bên thứ ba (như cổng thanh toán, gửi email, lưu trữ đám mây) hay không? Việc xử lý bất đồng bộ hoặc callback (IPN/Webhook) diễn ra như thế nào?",
                "outline": (
                    "- Liệt kê dịch vụ bên thứ ba đã tích hợp (PayOS, VNPay, Mailer...).\n"
                    "- Giải thích luồng callback/webhook xác thực chữ ký (Checksum/Signature).\n"
                    "- Nêu giải pháp tránh trùng lặp giao dịch (Idempotency) khi đối tác gọi lại nhiều lần."
                ),
                "chunks": c_p3,
            },

            # --- HARD (3 câu) ---
            {
                "difficulty": QuestionDifficulty.HARD,
                "topic": "Khả năng chịu tải & Điểm nghẽn hiệu năng",
                "text": f"Hệ thống có khả năng chịu tải đồng thời (Scalability) ở mức độ nào? Điểm yếu được chỉ ra là '{weakness_str}', vậy nếu lượng người dùng tăng đột biến thì điểm nghẽn (bottleneck) đầu tiên sẽ xảy ra ở đâu?",
                "outline": (
                    "- Thừa nhận giới hạn hiện tại của hệ thống (môi trường đơn máy chủ hoặc chưa cấu hình cluster).\n"
                    "- Phân tích điểm nghẽn tiềm tàng: kết nối Database (Connection Pool), I/O ổ đĩa, hoặc tác vụ đồng bộ blocking.\n"
                    "- Đề xuất phương án nâng cấp khi scale: bổ sung Caching (Redis), Load Balancer (Nginx), và chuyển tác vụ nặng sang hàng đợi (Message Queue / Celery / RabbitMQ)."
                ),
                "chunks": c_p4,
            },
            {
                "difficulty": QuestionDifficulty.HARD,
                "topic": "An toàn thông tin & Toàn vẹn dữ liệu",
                "text": "Bạn đã áp dụng các biện pháp nào để bảo vệ hệ thống trước các lỗ hổng bảo mật phổ biến như SQL Injection, CSRF, XSS và nguy cơ tương tranh dữ liệu (Race Condition)?",
                "outline": (
                    "- Nêu giải pháp chống SQL Injection (ORM / Prepared Statements parameterized queries).\n"
                    "- Nêu giải pháp chống CSRF (CSRF Token) và XSS (Sanitize input, escape output, CSP).\n"
                    "- Trình bày cơ chế Database Transaction (ACID) và khóa dữ liệu (Pessimistic/Optimistic lock) khi xử lý số lượng tồn kho hoặc số dư tài khoản."
                ),
                "chunks": c_p4,
            },
            {
                "difficulty": QuestionDifficulty.HARD,
                "topic": "Hạn chế & Hướng phát triển đồ án",
                "text": "Nếu được đánh giá khách quan nhất, hạn chế kỹ thuật lớn nhất mà đồ án của bạn chưa giải quyết triệt để là gì? Nếu có thêm 6 tháng nghiên cứu, bạn sẽ nâng cấp hệ thống theo hướng nào?",
                "outline": (
                    "- Thành thật và tự tin chỉ ra 1 hạn chế kỹ thuật thực sự của đồ án (không giấu giếm khuyết điểm trước hội đồng).\n"
                    "- Giải thích nguyên nhân khách quan và bài học kinh nghiệm rút ra.\n"
                    "- Trình bày lộ trình phát triển rõ ràng với 2-3 tính năng nâng cao (AI tự động hóa, Microservices, CI/CD tự động hóa)."
                ),
                "chunks": c_p4,
            },
        ]

        questions: List[GeneratedQuestionItem] = []
        for i, t in enumerate(templates[:target_count], start=1):
            questions.append(
                GeneratedQuestionItem(
                    order_index=i,
                    question_text=t["text"],
                    difficulty=t["difficulty"],
                    topic_competency=t["topic"],
                    expected_answer_outline=t["outline"],
                    source_chunk_ids=t["chunks"] if t["chunks"] else (chunk_ids[:2] if chunk_ids else []),
                    recommended_seconds=120,
                )
            )

        return questions

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON object from raw LLM output string."""
        if not text:
            return None

        # 1. Clean markdown code fence if present
        cleaned = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = cleaned[start : end + 1]
            else:
                candidate = cleaned

        # 2. Try direct load
        try:
            return json.loads(candidate)
        except Exception:
            pass

        # 3. Clean trailing commas and try again
        try:
            sanitized = re.sub(r",\s*([\]}])", r"\1", candidate)
            return json.loads(sanitized)
        except Exception:
            pass

        # 4. If truncated at the end, attempt emergency balance of brackets
        try:
            if candidate.startswith("{") and not candidate.endswith("}"):
                # Count open brackets and braces
                open_braces = candidate.count("{") - candidate.count("}")
                open_brackets = candidate.count("[") - candidate.count("]")
                balanced = candidate.rstrip(", \n\r\t") + ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
                return json.loads(balanced)
        except Exception:
            pass

        return None


# Global service instance
question_generator_service = QuestionGeneratorService()

