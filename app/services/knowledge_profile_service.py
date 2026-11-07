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
from app.schemas.knowledge_profile import (
    KnowledgeProfileData,
    AnticipatedQuestion,
    KnowledgeProfileResponse,
)
from app.repositories.project_repo import project_repo
from app.repositories.chunk_repo import chunk_repo
from app.repositories.document_repo import document_repo
from app.repositories.knowledge_profile_repo import knowledge_profile_repo

logger = logging.getLogger(__name__)


def build_system_prompt(major: str = "Tất cả các ngành đào tạo Đại học") -> str:
    """Generate universal academic system prompt adapted to student's major."""
    return f"""Bạn là Hội đồng Chấm Đồ Án / Khóa Luận Tốt Nghiệp Đại học chuyên ngành {major}.
Nhiệm vụ của bạn là đọc và phân tích toàn diện các đoạn trích từ tài liệu đồ án / khóa luận của sinh viên (thuộc bất kỳ khối ngành nào: Kinh tế - Quản trị, Kỹ thuật - Công nghệ, Xây dựng - Kiến trúc, Y Dược, Khoa học Tự nhiên hay Xã hội & Nhân văn) và tổng hợp thành một "Hồ sơ Tri thức Đồ án" có cấu trúc học thuật chuẩn mực để phục vụ các phiên hỏi đáp phản biện.

YÊU CẦU ĐẦU RA BẮT BUỘC:
Trả về DUY NHẤT một chuỗi JSON hợp lệ (không kèm markdown ```json hay bất kỳ văn bản giải thích ngoài), có cấu trúc sau:
{{
  "summary": "Tóm tắt ngắn gọn đề tài (bối cảnh thực tiễn, vấn đề/bài toán nghiên cứu cần giải quyết, phương pháp/giải pháp thực hiện và kết quả/đóng góp chính đạt được) trong 3-5 câu.",
  "objectives": ["Mục tiêu nghiên cứu/thực nghiệm 1", "Mục tiêu 2", "Mục tiêu 3"],
  "methodology_and_tech": [
    "Phương pháp luận nghiên cứu (ví dụ: định lượng, định tính, thực nghiệm phòng lab, mô hình hóa, hoặc kiến trúc giải pháp...)",
    "Công cụ / Phần mềm / Thiết bị / Tiêu chuẩn chuyên ngành áp dụng (ví dụ: SPSS, STATA, AutoCAD, tiêu chuẩn TCVN/ISO, hoặc công nghệ phần mềm...)",
    "Khung dữ liệu / Mẫu khảo sát / Cơ sở lý thuyết nền tảng"
  ],
  "contributions": ["Giá trị đóng góp học thuật hoặc tính ứng dụng thực tiễn của đề tài 1", "Đóng góp 2"],
  "defense_weaknesses": [
    "Điểm yếu về phương pháp luận / Cỡ mẫu khảo sát / Phạm vi thử nghiệm",
    "Giới hạn dữ liệu hoặc các giả định chưa được kiểm chứng đầy đủ",
    "Thách thức thực thi hoặc tính khả thi khi nhân rộng mô hình"
  ],
  "anticipated_questions": [
    {{
      "role": "CHỦ TỊCH HỘI ĐỒNG",
      "question": "Câu hỏi bao quát về tính cấp thiết, giá trị ứng dụng thực tiễn, hiệu quả kinh tế - xã hội hoặc hướng phát triển tiếp theo của đề tài?",
      "reason": "Đánh giá tầm nhìn tổng thể, ý nghĩa thực tiễn và khả năng đóng góp của đề tài đối với ngành.",
      "suggested_answer_hint": "Gợi ý sinh viên tập trung vào bài toán cốt lõi, giá trị thực tế mang lại cho đơn vị/xã hội và hướng hoàn thiện trong tương lai."
    }},
    {{
      "role": "GIẢNG VIÊN PHẢN BIỆN",
      "question": "Câu hỏi chất vấn sâu về cơ sở lý thuyết, độ tin cậy của phương pháp nghiên cứu, giới hạn mô hình hoặc so sánh với các hướng tiếp cận khác?",
      "reason": "Chất vấn tính chặt chẽ về mặt khoa học, phương pháp luận và tính xác thực của các kết luận rút ra.",
      "suggested_answer_hint": "Gợi ý sinh viên bảo vệ lập luận khoa học, dẫn chứng tài liệu tham khảo uy tín và thẳng thắn thừa nhận giới hạn phạm vi nghiên cứu."
    }},
    {{
      "role": "ỦY VIÊN HỘI ĐỒNG",
      "question": "Câu hỏi chi tiết về quy trình thu thập số liệu, công thức tính toán, các ca ngoại lệ hoặc tính khả thi khi triển khai thực tế?",
      "reason": "Kiểm tra mức độ trực tiếp tham gia làm đề tài của sinh viên và kỹ năng thực hành, xử lý số liệu chuyên môn.",
      "suggested_answer_hint": "Gợi ý sinh viên trả lời dựa trên số liệu cụ thể trong báo cáo, quy trình thực nghiệm và các biện pháp kiểm soát sai số/rủi ro."
    }}
  ]
}}
"""


class KnowledgeProfileService:
    """Service to synthesize and extract thesis knowledge profile using local LLM."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout_seconds

    def generate_profile(
        self,
        db: Session,
        project_id: int,
    ) -> ProjectKnowledgeProfile:
        """
        Synchronously (or background task) synthesizes knowledge profile for a project.
        """
        project = project_repo.get_by_id(db, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found.")

        # 1. Fetch active chunks
        active_chunks = chunk_repo.get_active_chunks_by_project(db, project_id)
        if not active_chunks:
            # Fallback to document repo or error
            docs = document_repo.get_by_project_id(db, project_id)
            if not docs:
                raise ValueError("Đề tài chưa có tài liệu nào được tải lên.")
            active_doc_id = docs[0].id
        else:
            active_doc_id = active_chunks[0].document_id

        # 2. Mark profile as generating
        profile = knowledge_profile_repo.create_or_update(
            db=db,
            project_id=project_id,
            profile_json={},
            source_document_ids=[active_doc_id],
            status="generating",
        )

        try:
            # 3. Call local LLM or fallback synthesis
            data = self._synthesize_with_llm_or_fallback(project, active_chunks)

            # 4. Save profile as ready
            profile = knowledge_profile_repo.create_or_update(
                db=db,
                project_id=project_id,
                profile_json=data.model_dump(),
                source_document_ids=[active_doc_id],
                status="ready",
            )
            logger.info(f"Knowledge Profile for project {project_id} successfully generated.")
            return profile

        except Exception as e:
            logger.error(f"Error generating knowledge profile for project {project_id}: {e}", exc_info=True)
            knowledge_profile_repo.update_status(db, profile, status="failed")
            raise

    def get_project_profile(
        self,
        db: Session,
        project_id: int,
    ) -> Optional[KnowledgeProfileResponse]:
        """Fetch knowledge profile response model."""
        profile = knowledge_profile_repo.get_by_project_id(db, project_id)
        if not profile:
            return None

        profile_data = None
        if profile.profile_json and profile.status == "ready":
            try:
                profile_data = KnowledgeProfileData(**profile.profile_json)
            except Exception as e:
                logger.warning(f"Error parsing profile JSON: {e}")

        return KnowledgeProfileResponse(
            id=profile.id,
            project_id=profile.project_id,
            version=profile.version,
            status=profile.status,
            profile_data=profile_data,
            source_document_ids=profile.source_document_ids,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def _synthesize_with_llm_or_fallback(
        self,
        project: ThesisProject,
        chunks: List[DocumentChunk],
    ) -> KnowledgeProfileData:
        """Call Ollama LLM to generate structured profile, fallback if unreachable."""
        llm_result = self._call_ollama_llm(project, chunks)
        if llm_result:
            return llm_result

        logger.info(f"Ollama LLM ({self.model}) currently unavailable. Using intelligent heuristic synthesis.")
        return self._heuristic_synthesis(project, chunks)

    def _call_ollama_llm(
        self,
        project: ThesisProject,
        chunks: List[DocumentChunk],
    ) -> Optional[KnowledgeProfileData]:
        """Call local Ollama /api/chat with strict JSON output adapted to student's major."""
        try:
            # Select 6-8 representative chunks across document for fast CPU inference
            step = max(1, len(chunks) // 6) if chunks else 1
            sampled = chunks[::step][:6] if chunks else []
            chunk_context = "\n\n".join(
                [f"[Trang {c.page_number or '?'}] {c.text[:250]}" for c in sampled]
            )

            major_str = project.topic or "Tất cả các ngành đào tạo Đại học"
            system_prompt = build_system_prompt(major_str)

            user_prompt = f"""ĐỀ TÀI: {project.title}
CHUYÊN NGÀNH: {major_str}
MÔ TẢ: {project.description or ''}

CÁC TRÍCH ĐOẠN TỪ BÁO CÁO:
{chunk_context}

Hãy đọc kỹ và tạo Hồ sơ Tri thức Đồ án chuẩn JSON theo đúng định dạng học thuật được hướng dẫn."""

            with httpx.Client(timeout=90.0) as client:
                res = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "format": "json",
                        "stream": False,
                        "options": {
                            "temperature": 0.2,
                            "num_predict": 700,
                        },
                    },
                )
                if res.status_code == 200:
                    payload = res.json()
                    content = payload.get("message", {}).get("content", "")
                    clean_json = re.sub(r"^```json\s*", "", content.strip())
                    clean_json = re.sub(r"\s*```$", "", clean_json)
                    parsed = json.loads(clean_json)
                    return KnowledgeProfileData(**parsed)

        except Exception as e:
            logger.debug(f"Ollama chat call failed or timed out: {e}")
            return None

        return None

    def _heuristic_synthesis(
        self,
        project: ThesisProject,
        chunks: List[DocumentChunk],
    ) -> KnowledgeProfileData:
        """
        Universal academic thesis analyzer when LLM is offline or busy.
        Intelligently adapts to ANY academic discipline (Economics, Engineering, Medical, Social, IT...).
        """
        title = project.title or "Đồ án tốt nghiệp"
        major = project.topic or "Khoa học Ứng dụng"
        joined_text = " ".join([c.text for c in chunks[:35]]).lower()

        # Domain detection keywords
        is_it = any(w in joined_text for w in ["phần mềm", "website", "lập trình", "database", "api", "laravel", "python", "mysql", "react", "ứng dụng"]) or "tin học" in major.lower() or "phần mềm" in major.lower()
        is_business = any(w in joined_text for w in ["doanh thu", "chiến lược", "marketing", "khách hàng", "tài chính", "kế toán", "kinh doanh", "thị trường", "sản phẩm"]) or "kinh tế" in major.lower() or "quản trị" in major.lower()
        is_civil = any(w in joined_text for w in ["kết cấu", "bê tông", "móng", "thi công", "công trình", "bản vẽ", "tải trọng", "cốt thép"]) or "xây dựng" in major.lower() or "kiến trúc" in major.lower()
        is_medical = any(w in joined_text for w in ["bệnh nhân", "lâm sàng", "chẩn đoán", "điều trị", "dược", "y tế", "thuốc", "bệnh viện"]) or "y" in major.lower() or "dược" in major.lower()

        if is_it:
            tech_patterns = ["Laravel", "FastAPI", "React", "Next.js", "Vue", "Node.js", "Python", "PHP", "MySQL", "PostgreSQL", "Docker", "RESTful API", "VNPay", "MoMo", "ZaloPay", "JWT", "Bcrypt", "Redis"]
            found_tools = [tech for tech in tech_patterns if re.search(rf"\b{tech}\b", joined_text, re.IGNORECASE)]
            tools_summary = ", ".join(found_tools[:5]) if found_tools else "Công nghệ phần mềm hiện đại, Kiến trúc phân tầng và RESTful API"

            summary = (
                f"Đề tài '{title}' (Chuyên ngành: {major}) tập trung nghiên cứu và xây dựng giải pháp ứng dụng công nghệ phần mềm "
                f"nhằm giải quyết bài toán thực tế đặt ra. Hệ thống ứng dụng nền tảng {tools_summary}, "
                f"đáp ứng đầy đủ các yêu cầu nghiệp vụ, tính toàn vẹn dữ liệu và tiêu chuẩn an toàn thông tin."
            )
            objectives = [
                f"Khảo sát thực trạng bài toán và phân tích yêu cầu nghiệp vụ của đề tài '{title}'.",
                f"Thiết kế kiến trúc hệ thống và cơ sở dữ liệu quan hệ chuẩn hóa trên {tools_summary}.",
                "Xây dựng và tích hợp các module chức năng cốt lõi cùng cơ chế xác thực, phân quyền an toàn.",
                "Tiến hành kiểm thử phần mềm (API Testing, Unit Testing) và đánh giá tính khả thi trong môi trường thực nghiệm.",
            ]
            methodology_and_tech = [
                f"Kiến trúc phần mềm: Mô hình MVC / Clean Architecture kết hợp {tools_summary}.",
                "Cơ sở dữ liệu: Thiết kế lược đồ chuẩn hóa, ràng buộc khóa ngoại và toàn vẹn giao dịch ACID.",
                "Bảo mật: Xác thực người dùng, kiểm soát phiên làm việc và mã hóa dữ liệu nhạy cảm.",
            ]
            defense_weaknesses = [
                "Khả năng mở rộng (Scalability): Chưa kiểm thử chịu tải đồng thời (Load Testing) ở quy mô hàng chục nghìn người dùng.",
                "Bảo mật chuyên sâu: Cần bổ sung cơ chế Rate Limiting chống tấn công DoS và kiểm toán bảo mật nâng cao.",
                "Xử lý bất đồng bộ: Các tác vụ nặng (như gửi email, đối soát thanh toán) nên chuyển sang Message Queue.",
            ]
            anticipated_questions = [
                AnticipatedQuestion(
                    role="CHỦ TỊCH HỘI ĐỒNG",
                    question=f"Đề tài '{title}' có điểm gì mới hoặc cải tiến nổi bật so với các giải pháp hiện có trên thị trường?",
                    reason="Đánh giá tính mới, tính thực tiễn và giá trị thực tế mà đề tài mang lại cho ngành.",
                    suggested_answer_hint="Nêu bật bài toán chuyên biệt mà đề tài giải quyết, trải nghiệm người dùng tối ưu và chi phí triển khai hợp lý.",
                ),
                AnticipatedQuestion(
                    role="GIẢNG VIÊN PHẢN BIỆN",
                    question=f"Căn cứ khoa học nào để bạn lựa chọn nền tảng kiến trúc này? Giới hạn lớn nhất của giải pháp là gì?",
                    reason="Chất vấn cơ sở lựa chọn công nghệ và mức độ am hiểu của sinh viên về giới hạn nghiên cứu.",
                    suggested_answer_hint="Trình bày ưu điểm về tính ổn định, tốc độ phát triển; đồng thời thẳng thắn nêu rõ giới hạn tài nguyên và hướng nâng cấp.",
                ),
                AnticipatedQuestion(
                    role="ỦY VIÊN HỘI ĐỒNG",
                    question="Bạn xử lý tính nhất quán dữ liệu và các ca lỗi ngoại lệ (Edge Cases) trong quy trình nghiệp vụ như thế nào?",
                    reason="Kiểm tra kỹ năng xử lý dữ liệu chuyên sâu và mức độ hoàn thiện sản phẩm thực tế.",
                    suggested_answer_hint="Mô tả cơ chế kiểm tra tính hợp lệ dữ liệu, bắt lỗi ngoại lệ tập trung và thiết lập Database Transaction.",
                ),
            ]

        elif is_business:
            summary = (
                f"Đề tài '{title}' (Chuyên ngành: {major}) tập trung phân tích thực trạng hoạt động và các nhân tố ảnh hưởng "
                f"đến hiệu quả kinh doanh, từ đó đề xuất các giải pháp chiến lược nhằm tối ưu hóa quy trình quản trị, gia tăng doanh thu và nâng cao năng lực cạnh tranh."
            )
            objectives = [
                f"Hệ thống hóa cơ sở lý luận và các mô hình quản trị/kinh tế liên quan đến đề tài '{title}'.",
                "Phân tích thực trạng hoạt động, khảo sát hành vi khách hàng và các nguồn lực nội tại của đơn vị nghiên cứu.",
                "Xác định các điểm nghẽn và nhân tố rủi ro tác động đến hiệu quả thực thi chiến lược.",
                "Đề xuất hệ thống giải pháp và lộ trình triển khai khả thi kèm dự toán chi phí - hiệu quả.",
            ]
            methodology_and_tech = [
                "Phương pháp nghiên cứu: Kết hợp phân tích định tính (phỏng vấn chuyên gia) và định lượng (khảo sát mẫu).",
                "Công cụ xử lý dữ liệu: Ứng dụng phần mềm thống kê (SPSS/Excel) để phân tích tương quan và hồi quy.",
                "Khung lý thuyết: Mô hình 4P/7P Marketing, ma trận SWOT, mô hình 5 áp lực cạnh tranh của Michael Porter.",
            ]
            defense_weaknesses = [
                "Quy mô mẫu khảo sát: Cỡ mẫu có thể chưa bao quát toàn bộ các phân khúc khách hàng trên diện rộng.",
                "Yếu tố thị trường biến động: Các giải pháp tài chính/kinh doanh phụ thuộc nhiều vào tình hình kinh tế vĩ mô.",
                "Tính khả thi về ngân sách: Cần bổ sung phân tích độ nhạy (Sensitivity Analysis) đối với các kịch bản doanh thu sụt giảm.",
            ]
            anticipated_questions = [
                AnticipatedQuestion(
                    role="CHỦ TỊCH HỘI ĐỒNG",
                    question=f"Các giải pháp mà đề tài '{title}' đề xuất có thực sự giải quyết được bài toán cấp bách nhất của doanh nghiệp hiện nay không?",
                    reason="Đánh giá tính cấp thiết và hiệu quả ứng dụng thực tiễn của các khuyến nghị quản trị.",
                    suggested_answer_hint="Nhấn mạnh vào tính khả thi, thời gian hoàn vốn và các chỉ số đo lường hiệu quả (KPI, ROI) rõ ràng.",
                ),
                AnticipatedQuestion(
                    role="GIẢNG VIÊN PHẢN BIỆN",
                    question="Cơ sở nào để khẳng định các biến số khảo sát của bạn có độ tin cậy và giá trị khoa học (Cronbach's Alpha, EFA)?",
                    reason="Chất vấn tính chặt chẽ của phương pháp định lượng và độ tin cậy của bảng hỏi khảo sát.",
                    suggested_answer_hint="Dẫn chứng các chỉ số kiểm định hệ số tin cậy đạt chuẩn và quy trình sàng lọc mẫu hợp lệ.",
                ),
                AnticipatedQuestion(
                    role="ỦY VIÊN HỘI ĐỒNG",
                    question="Nếu ngân sách triển khai thực tế bị cắt giảm 30%, bạn sẽ ưu tiên thực hiện giải pháp nào trước và vì sao?",
                    reason="Kiểm tra khả năng tư duy quản trị linh hoạt và mức độ am hiểu thứ tự ưu tiên của các giải pháp.",
                    suggested_answer_hint="Phân loại các giải pháp theo ma trận Tác động - Chi phí (Impact-Effort) để chọn giải pháp mang lại giá trị cao nhất trước.",
                ),
            ]

        elif is_civil:
            summary = (
                f"Đề tài '{title}' (Chuyên ngành: {major}) tập trung thiết kế kết cấu, tính toán tải trọng và lập biện pháp thi công "
                f"cho công trình xây dựng. Đồ án tuân thủ nghiêm ngặt các quy chuẩn, tiêu chuẩn xây dựng hiện hành (TCVN), đảm bảo tính an toàn chịu lực, độ bền vững và hiệu quả kinh tế."
            )
            objectives = [
                f"Thu thập số liệu địa chất, khí hậu và công năng sử dụng phục vụ thiết kế công trình '{title}'.",
                "Thiết lập sơ đồ tính toán, xác định tổ hợp tải trọng tác động (tĩnh tải, hoạt tải, gió, động đất).",
                "Tính toán, bố trí cốt thép và kiểm tra điều kiện bền, điều kiện sử dụng (độ võng, vết nứt) cho các cấu kiện.",
                "Lập phương án tổ chức thi công, tiến độ thực hiện và biện pháp đảm bảo an toàn lao động.",
            ]
            methodology_and_tech = [
                "Phương pháp tính toán: Phương pháp phần tử hữu hạn (FEM) mô phỏng tương tác kết cấu - nền móng.",
                "Công cụ phần mềm chuyên ngành: Etabs, SAP2000, SAFE và phần mềm đồ họa kỹ thuật AutoCAD/Revit.",
                "Hệ thống quy chuẩn áp dụng: Tiêu chuẩn thiết kế kết cấu bê tông cốt thép TCVN 5574, tải trọng và tác động TCVN 2737.",
            ]
            defense_weaknesses = [
                "Tương tác nền móng: Mô hình đất nền có thể sử dụng hệ số nền đơn giản hóa, chưa phản ánh đầy đủ tính phi tuyến phức tạp.",
                "Tối ưu hóa kinh tế: Tỷ lượng thép ở một số vị trí dầm/cột có thể còn dư an toàn, cần tối ưu thêm để tiết kiệm chi phí.",
                "Rủi ro thi công thực tế: Cần dự báo thêm các biện pháp ứng phó khi thời tiết xấu hoặc địa chất có túi bùn bất thường.",
            ]
            anticipated_questions = [
                AnticipatedQuestion(
                    role="CHỦ TỊCH HỘI ĐỒNG",
                    question=f"Giải pháp kết cấu và phương án thi công của đồ án '{title}' có ưu điểm nổi bật gì về tiến độ và chi phí so với phương án truyền thống?",
                    reason="Đánh giá tổng thể hiệu quả kinh tế - kỹ thuật của phương án thiết kế được chọn.",
                    suggested_answer_hint="So sánh chỉ tiêu kinh tế - kỹ thuật (khối lượng bê tông, hàm lượng thép/m2 sàn) và thời gian thi công.",
                ),
                AnticipatedQuestion(
                    role="GIẢNG VIÊN PHẢN BIỆN",
                    question="Tại sao bạn lại chọn sơ đồ tính toán này và giả định liên kết ngàm tại chân cột có hoàn toàn phù hợp với thực tế địa chất?",
                    reason="Chất vấn cơ sở khoa học của mô hình hóa kết cấu và sự phù hợp của các giả thiết tính toán.",
                    suggested_answer_hint="Giải thích căn cứ vào độ cứng của đài cọc/móng khối lớn để biện minh cho giả thiết ngàm chặt chân cột.",
                ),
                AnticipatedQuestion(
                    role="ỦY VIÊN HỘI ĐỒNG",
                    question="Bạn kiểm tra điều kiện chọc thủng của đài móng và khống chế vết nứt bề mặt cấu kiện như thế nào?",
                    reason="Kiểm tra chi tiết tính toán kỹ thuật và sự nắm vững các công thức trong tiêu chuẩn TCVN.",
                    suggested_answer_hint="Dẫn chứng công thức kiểm tra ứng suất nén/cắt và bề rộng khe nứt giới hạn theo TCVN 5574.",
                ),
            ]

        else:
            # Universal Academic Research Template
            summary = (
                f"Đề tài '{title}' (Chuyên ngành: {major}) tập trung nghiên cứu giải quyết bài toán thực tiễn đặt ra trong lĩnh vực {major}. "
                f"Thông qua việc kết hợp cơ sở lý thuyết chuẩn mực và phương pháp khảo sát/thực nghiệm thực tế, đề tài đã đề xuất các giải pháp khả thi, "
                f"góp phần hoàn thiện mô hình và nâng cao hiệu quả ứng dụng chuyên môn."
            )
            objectives = [
                f"Hệ thống hóa cơ sở lý thuyết và các nghiên cứu tiền nhiệm liên quan đến đề tài '{title}'.",
                f"Khảo sát, thu thập dữ liệu và đánh giá thực trạng nghiên cứu trong lĩnh vực {major}.",
                "Phân tích các nhân tố cốt lõi, phát hiện các điểm nghẽn và giới hạn hiện hữu.",
                "Đề xuất hệ thống giải pháp ứng dụng và khuyến nghị nâng cao hiệu quả thực tiễn.",
            ]
            methodology_and_tech = [
                "Phương pháp nghiên cứu: Kết hợp phân tích lý thuyết, khảo sát thực nghiệm và đối chiếu dữ liệu thực tế.",
                "Công cụ & Kỹ thuật chuyên môn: Ứng dụng các quy chuẩn chuyên ngành và phần mềm xử lý dữ liệu phù hợp.",
                "Quy trình kiểm soát: Thu thập mẫu và thẩm định thông tin theo các tiêu chuẩn học thuật hiện hành.",
            ]
            defense_weaknesses = [
                "Phạm vi và quy mô khảo sát: Cỡ mẫu hoặc dữ liệu nghiên cứu còn giới hạn trong một phạm vi nhất định.",
                "Điều kiện biến động thực tế: Các yếu tố ngoại cảnh có thể tác động đến tính ổn định của mô hình giải pháp.",
                "Đánh giá dài hạn: Cần thêm thời gian theo dõi thực tế để kiểm chứng toàn diện hiệu quả lâu dài.",
            ]
            anticipated_questions = [
                AnticipatedQuestion(
                    role="CHỦ TỊCH HỘI ĐỒNG",
                    question=f"Đề tài '{title}' có ý nghĩa thực tiễn và giá trị ứng dụng cụ thể như thế nào đối với ngành {major}?",
                    reason="Đánh giá tầm nhìn tổng thể, tính cấp thiết và ý nghĩa thực tiễn của đề tài.",
                    suggested_answer_hint="Nhấn mạnh vào bài toán thực tiễn cốt lõi mà đề tài giải quyết và lợi ích cụ thể cho đơn vị/cộng đồng.",
                ),
                AnticipatedQuestion(
                    role="GIẢNG VIÊN PHẢN BIỆN",
                    question="Căn cứ khoa học nào để bạn lựa chọn phương pháp nghiên cứu này và giới hạn lớn nhất của đề tài là gì?",
                    reason="Chất vấn tính chặt chẽ của phương pháp luận và mức độ am hiểu của sinh viên về giới hạn nghiên cứu.",
                    suggested_answer_hint="Trình bày tính phù hợp của phương pháp so với mục tiêu đặt ra và thẳng thắn nêu rõ giới hạn nghiên cứu.",
                ),
                AnticipatedQuestion(
                    role="ỦY VIÊN HỘI ĐỒNG",
                    question="Quy trình thu thập và xử lý số liệu của bạn được thực hiện như thế nào để đảm bảo tính khách quan và tin cậy?",
                    reason="Kiểm tra kỹ năng thực hành, xử lý số liệu và mức độ trực tiếp tham gia thực hiện đề tài của sinh viên.",
                    suggested_answer_hint="Mô tả các bước thu thập dữ liệu, cách loại bỏ số liệu ngoại lai và các biện pháp kiểm soát sai số.",
                ),
            ]

        return KnowledgeProfileData(
            summary=summary,
            objectives=objectives,
            methodology_and_tech=methodology_and_tech,
            contributions=[
                f"Đóng góp giải pháp khoa học và quy trình thực hiện cụ thể cho đề tài '{title}'.",
                "Cung cấp tài liệu tham khảo có giá trị học thuật và thực tiễn cho các nghiên cứu tiếp theo.",
            ],
            defense_weaknesses=defense_weaknesses,
            anticipated_questions=anticipated_questions,
        )


knowledge_profile_service = KnowledgeProfileService()

