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
            "Bạn là Chuyên gia Khảo thí và Giảng viên Thư ký Hội đồng Chấm Đồ Án / Khóa Luận Tốt Nghiệp Đại Học.\n"
            "Nhiệm vụ của bạn là đọc thông tin đề tài và tài liệu trích dẫn để sinh bộ câu hỏi bảo vệ (~12 câu) "
            "phân tầng độ khó chuẩn mực học thuật (Dễ: ~3-4 câu, Trung bình: ~5-6 câu, Khó: ~3-4 câu).\n\n"
            "YÊU CẦU BẮT BUỘC:\n"
            "1. Phân bổ độ khó (Thang đo tư duy học thuật Bloom):\n"
            "   - 'easy': Bối cảnh thực tiễn, tính cấp thiết, mục tiêu nghiên cứu, đối tượng thụ hưởng và phạm vi/ranh giới nghiên cứu của đề tài.\n"
            "   - 'medium': Cơ sở lý thuyết nền tảng, phương pháp luận/công cụ chuyên môn đã áp dụng, quy trình thực nghiệm/mô hình hóa, phân tích số liệu và kết quả đạt được.\n"
            "   - 'hard': Đánh giá độ tin cậy của phương pháp/mẫu khảo sát, xử lý rủi ro và các tình huống ngoại lệ/biến động thực tế, hạn chế lớn nhất và hướng phát triển tiếp theo.\n"
            "2. Mỗi câu hỏi PHẢI CÓ:\n"
            "   - 'order_index': Thứ tự từ 1 đến N\n"
            "   - 'question_text': Câu hỏi ngắn gọn, sâu sắc, mang phong thái hội đồng phản biện học thuật\n"
            "   - 'difficulty': 'easy' | 'medium' | 'hard'\n"
            "   - 'topic_competency': Tên lĩnh vực / năng lực chuyên môn (VD: 'Tổng quan & Tính cấp thiết', 'Phương pháp nghiên cứu', 'Mô hình giải pháp', 'Phân tích dữ liệu', 'Đánh giá & Hạn chế')\n"
            "   - 'expected_answer_outline': Dàn ý gợi ý 2-3 gạch đầu dòng rõ ràng (- Ý 1...\\n- Ý 2...\\n- Ý 3...), chỉ rõ các luận điểm then chốt sinh viên nên trả lời để đạt điểm tối đa\n"
            "   - 'source_chunk_ids': Mảng các số nguyên chunk_id có liên quan được cung cấp bên dưới\n"
            "   - 'recommended_seconds': 120\n"
            "3. TRẢ VỀ DUY NHẤT 1 ĐỐI TƯỢNG JSON có key 'questions', TUYỆT ĐỐI KHÔNG VIẾT CHỮ NÀO KHÁC NGOÀI JSON.\n"
            "Ví dụ định dạng:\n"
            "{\n"
            '  "questions": [\n'
            '    {\n'
            '      "order_index": 1,\n'
            '      "question_text": "Mục tiêu nghiên cứu chính của đề tài là gì và giải pháp bạn xây dựng giải quyết bài toán thực tế nào?",\n'
            '      "difficulty": "easy",\n'
            '      "topic_competency": "Tổng quan đề tài",\n'
            '      "expected_answer_outline": "- Nêu rõ bối cảnh thực tế và lý do lựa chọn nghiên cứu đề tài.\\n- Trình bày 2-3 mục tiêu cốt lõi mà nghiên cứu/sản phẩm đã hoàn thành.\\n- Khẳng định giá trị thực tiễn mang lại cho đối tượng thụ hưởng.",\n'
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
        major = project.topic or "chuyên ngành"
        method_list = profile_data.methodology_and_tech if profile_data and profile_data.methodology_and_tech else []
        method_str = ", ".join(method_list[:3]) if method_list else "phương pháp luận và công cụ chuyên ngành đã lựa chọn"
        weakness_list = profile_data.defense_weaknesses if profile_data and profile_data.defense_weaknesses else []
        weakness_str = weakness_list[0] if weakness_list else "phạm vi dữ liệu khảo sát và điều kiện kiểm thử thực tế"

        chunk_ids = [c.id for c in chunks]
        c_p1 = chunk_ids[:2] if len(chunk_ids) >= 2 else chunk_ids
        c_p2 = chunk_ids[2:5] if len(chunk_ids) >= 5 else chunk_ids
        c_p3 = chunk_ids[5:8] if len(chunk_ids) >= 8 else chunk_ids
        c_p4 = chunk_ids[8:] if len(chunk_ids) >= 9 else chunk_ids

        # 12 Universal Academic Defense Questions (Applicable to IT, Economics, Construction, Medicine, Social Sciences, etc.)
        templates = [
            # --- EASY (3 câu) ---
            {
                "difficulty": QuestionDifficulty.EASY,
                "topic": "Tổng quan & Tính cấp thiết",
                "text": f"Bạn hãy trình bày tóm tắt mục tiêu nghiên cứu và tính cấp thiết thực tiễn của đề tài '{title}' trong bối cảnh ngành {major}?",
                "outline": (
                    "- Nêu rõ bối cảnh thực tiễn và lý do lựa chọn nghiên cứu đề tài.\n"
                    "- Nêu 2-3 mục tiêu cốt lõi mà đề tài/sản phẩm hướng tới giải quyết.\n"
                    "- Khẳng định giá trị thực tiễn mang lại cho đối tượng thụ hưởng hoặc đơn vị ứng dụng."
                ),
                "chunks": c_p1,
            },
            {
                "difficulty": QuestionDifficulty.EASY,
                "topic": "Phạm vi & Đối tượng nghiên cứu",
                "text": "Phạm vi nghiên cứu của đề tài được giới hạn như thế nào? Những nội dung nào nằm trong phạm vi thực hiện và nội dung nào nằm ngoài phạm vi nghiên cứu?",
                "outline": (
                    "- Xác định rõ ranh giới nghiên cứu (không gian, thời gian, đối tượng khảo sát/thực nghiệm).\n"
                    "- Nêu các phần việc/nội dung trọng tâm đã hoàn thành tốt.\n"
                    "- Thẳng thắn chỉ ra các khía cạnh chưa thực hiện do giới hạn nguồn lực và thời gian."
                ),
                "chunks": c_p1,
            },
            {
                "difficulty": QuestionDifficulty.EASY,
                "topic": "Tổng quan nghiên cứu & So sánh",
                "text": "Trong quá trình khảo sát thực tế, bạn nhận thấy các nghiên cứu hoặc giải pháp hiện có có những ưu nhược điểm gì dẫn đến việc bạn đề xuất hướng tiếp cận này?",
                "outline": (
                    "- Chỉ ra 1-2 mô hình/giải pháp hoặc nghiên cứu tương tự đã có trên thực tế.\n"
                    "- Phân tích ưu/nhược điểm hoặc khoảng trống nghiên cứu của các giải pháp đó.\n"
                    "- Nêu rõ điểm mới, cải tiến hoặc tính phù hợp vượt trội mà đề tài mang lại."
                ),
                "chunks": c_p1,
            },

            # --- MEDIUM (6 câu) ---
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Cơ sở lý thuyết & Phương pháp luận",
                "text": f"Hãy phân tích cơ sở lý thuyết nền tảng và lý do bạn lựa chọn {method_str} để thực hiện đề tài thay vì các hướng tiếp cận khác?",
                "outline": (
                    "- Trình bày khung lý thuyết và phương pháp luận chuyên ngành đã áp dụng.\n"
                    "- Giải thích căn cứ khoa học của việc lựa chọn phương pháp/công cụ này.\n"
                    "- Nêu được sự đánh đổi (Trade-offs) hoặc thách thức khi áp dụng phương pháp này."
                ),
                "chunks": c_p2,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Thu thập & Xử lý số liệu",
                "text": "Quy trình thu thập số liệu, khảo sát mẫu hoặc tiến hành thực nghiệm của đề tài được tổ chức như thế nào để đảm bảo tính khách quan và tin cậy?",
                "outline": (
                    "- Mô tả phương pháp chọn mẫu, quy mô mẫu hoặc điều kiện thực nghiệm.\n"
                    "- Trình bày các bước làm sạch, xử lý và chuẩn hóa dữ liệu/số liệu.\n"
                    "- Nêu biện pháp kiểm soát sai số và độ tin cậy của kết quả thu thập."
                ),
                "chunks": c_p2,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Mô hình hóa & Quy trình giải pháp",
                "text": "Trình bày chi tiết luồng xử lý hoặc quy trình thực hiện một nghiệp vụ/nội dung quan trọng nhất trong đề tài từ khâu tiếp nhận thông tin đến kết quả cuối cùng?",
                "outline": (
                    "- Mô tả từng bước của quy trình theo trình tự logic thời gian.\n"
                    "- Giải thích các quy tắc kiểm tra tính hợp lệ và xử lý tại từng giai đoạn.\n"
                    "- Nêu rõ kết quả đầu ra và cách thức chuyển giao thông tin/dữ liệu."
                ),
                "chunks": c_p3,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Đo lường & Kiểm chứng kết quả",
                "text": "Bạn đã sử dụng các chỉ số, tiêu chí định lượng hoặc công cụ nào để kiểm chứng và đánh giá mức độ hoàn thành mục tiêu nghiên cứu?",
                "outline": (
                    "- Liệt kê các chỉ số đo lường hiệu quả (KPI, độ chính xác, tỷ lệ cải thiện...).\n"
                    "- Trình bày phương pháp so sánh đối chứng trước và sau khi áp dụng giải pháp.\n"
                    "- Đưa ra nhận xét khách quan về kết quả thực nghiệm/khảo sát đạt được."
                ),
                "chunks": c_p3,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Tuân thủ quy chuẩn & Tiêu chuẩn ngành",
                "text": f"Giải pháp hoặc mô hình nghiên cứu của bạn tuân thủ các quy chuẩn, tiêu chuẩn kỹ thuật hoặc nguyên tắc đạo đức chuyên môn nào trong ngành {major}?",
                "outline": (
                    "- Nêu các quy chuẩn/tiêu chuẩn ngành hoặc quy định pháp lý/đạo đức liên quan.\n"
                    "- Giải thích cách đề tài hiện thực hóa việc đáp ứng các tiêu chuẩn đó.\n"
                    "- Phân tích biện pháp bảo vệ tính toàn vẹn, bảo mật hoặc an toàn của dữ liệu/kết quả."
                ),
                "chunks": c_p3,
            },
            {
                "difficulty": QuestionDifficulty.MEDIUM,
                "topic": "Tính khả thi & Điều kiện triển khai",
                "text": "Để đưa giải pháp/mô hình của bạn ứng dụng vào thực tế tại cơ quan, doanh nghiệp hoặc thị trường, cần những điều kiện tiên quyết nào về nguồn lực và hạ tầng?",
                "outline": (
                    "- Đánh giá yêu cầu về nhân sự, kinh phí và trang thiết bị/hạ tầng cần thiết.\n"
                    "- Phân tích tính khả thi về mặt chi phí - hiệu quả hoặc thời gian hoàn vốn/triển khai.\n"
                    "- Đề xuất phương án thích ứng khi triển khai vào môi trường thực tế."
                ),
                "chunks": c_p3,
            },

            # --- HARD (3 câu) ---
            {
                "difficulty": QuestionDifficulty.HARD,
                "topic": "Độ tin cậy & Độ nhạy của mô hình",
                "text": f"Đề tài có giả định những điều kiện lý tưởng nào? Điểm yếu tiềm ẩn là '{weakness_str}', vậy nếu các điều kiện thực tế biến động bất lợi thì tính ổn định của giải pháp sẽ ra sao?",
                "outline": (
                    "- Thừa nhận các giả định nền tảng và giới hạn hiện tại của mô hình/nghiên cứu.\n"
                    "- Phân tích tác động khi các biến số ngoại cảnh hoặc số liệu đầu vào biến động bất thường.\n"
                    "- Đề xuất kịch bản dự phòng và phương án tăng cường độ bền vững của giải pháp."
                ),
                "chunks": c_p4,
            },
            {
                "difficulty": QuestionDifficulty.HARD,
                "topic": "Kiểm soát rủi ro & Xử lý ngoại lệ",
                "text": "Bạn đã dự liệu những rủi ro kỹ thuật, sai số dữ liệu hoặc tình huống ngoại lệ (Edge Cases) nào nghiêm trọng nhất và giải pháp xử lý ứng phó ra sao?",
                "outline": (
                    "- Nêu 1-2 tình huống rủi ro hoặc ca lỗi ngoại lệ có thể làm gián đoạn/sai lệch kết quả.\n"
                    "- Giải thích cơ chế cảnh báo sớm, cô lập sự cố và phục hồi trạng thái ổn định.\n"
                    "- Chứng minh phương án phòng ngừa chủ động đã được tính toán trong đề tài."
                ),
                "chunks": c_p4,
            },
            {
                "difficulty": QuestionDifficulty.HARD,
                "topic": "Hạn chế & Hướng phát triển đồ án",
                "text": "Nếu được đánh giá một cách khắt khe và khách quan nhất, hạn chế lớn nhất mà đề tài của bạn chưa giải quyết triệt để là gì và lộ trình nâng cấp trong 6 tháng tới ra sao?",
                "outline": (
                    "- Thành thật và tự tin chỉ ra 1 hạn chế cốt lõi của nghiên cứu (không giấu khuyết điểm trước Hội đồng).\n"
                    "- Phân tích nguyên nhân khách quan và bài học học thuật rút ra.\n"
                    "- Trình bày lộ trình phát triển rõ ràng với 2-3 nội dung nâng cao cụ thể."
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

