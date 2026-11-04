import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractedPage:
    """Represents text extracted from a single page or slide with section metadata."""
    page_number: int
    section_title: Optional[str]
    text: str


class DocumentExtractor:
    """Extracts structured text from PDF, DOCX, and PPTX files."""

    def extract_from_pdf(self, file_path: Path) -> List[ExtractedPage]:
        """Extract text page by page from PDF using pypdf."""
        from pypdf import PdfReader

        pages: List[ExtractedPage] = []
        try:
            reader = PdfReader(str(file_path))
            for idx, page in enumerate(reader.pages, start=1):
                raw_text = page.extract_text() or ""
                clean_text = raw_text.strip()
                if clean_text:
                    # Detect first line as potential section title if short
                    lines = [ln.strip() for ln in clean_text.splitlines() if ln.strip()]
                    section_title = None
                    if lines and len(lines[0]) <= 80 and not lines[0].endswith("."):
                        section_title = lines[0]

                    pages.append(
                        ExtractedPage(
                            page_number=idx,
                            section_title=section_title,
                            text=clean_text,
                        )
                    )
        except Exception as e:
            logger.error(f"Error extracting text from PDF {file_path}: {e}")
            raise ValueError(f"Không thể đọc file PDF: {str(e)}")

        return pages

    def extract_from_docx(self, file_path: Path) -> List[ExtractedPage]:
        """Extract text organized by headings and logical blocks from DOCX."""
        import docx

        pages: List[ExtractedPage] = []
        try:
            doc = docx.Document(str(file_path))
            current_title = "Phần mở đầu"
            current_paragraphs: List[str] = []
            virtual_page = 1

            for p in doc.paragraphs:
                text = p.text.strip()
                if not text:
                    continue

                # Check if paragraph is a Heading or Title
                style_name = p.style.name if p.style else ""
                is_heading = (
                    style_name.startswith("Heading")
                    or style_name.startswith("TieuDe")
                    or "Title" in style_name
                )

                if is_heading:
                    if current_paragraphs:
                        pages.append(
                            ExtractedPage(
                                page_number=virtual_page,
                                section_title=current_title,
                                text="\n\n".join(current_paragraphs),
                            )
                        )
                        virtual_page += 1
                        current_paragraphs = []
                    current_title = text
                else:
                    current_paragraphs.append(text)
                    # Group into approximate pages if length exceeds ~1600 characters
                    if sum(len(x) for x in current_paragraphs) >= 1600:
                        pages.append(
                            ExtractedPage(
                                page_number=virtual_page,
                                section_title=current_title,
                                text="\n\n".join(current_paragraphs),
                            )
                        )
                        virtual_page += 1
                        current_paragraphs = []

            if current_paragraphs:
                pages.append(
                    ExtractedPage(
                        page_number=virtual_page,
                        section_title=current_title,
                        text="\n\n".join(current_paragraphs),
                    )
                )
        except Exception as e:
            logger.error(f"Error extracting text from DOCX {file_path}: {e}")
            raise ValueError(f"Không thể đọc file DOCX: {str(e)}")

        return pages

    def extract_from_pptx(self, file_path: Path) -> List[ExtractedPage]:
        """Extract text slide by slide from PPTX with slide titles."""
        from pptx import Presentation

        slides: List[ExtractedPage] = []
        try:
            prs = Presentation(str(file_path))
            for idx, slide in enumerate(prs.slides, start=1):
                slide_title: Optional[str] = None
                slide_lines: List[str] = []

                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for p in shape.text_frame.paragraphs:
                            line = p.text.strip()
                            if line:
                                is_title_shape = (
                                    shape == slide.shapes.title
                                    or "title" in shape.name.lower()
                                )
                                if is_title_shape and slide_title is None:
                                    slide_title = line
                                else:
                                    slide_lines.append(line)

                # Include slide tables if any
                for shape in slide.shapes:
                    if shape.has_table:
                        for row in shape.table.rows:
                            row_text = " | ".join(
                                cell.text.strip() for cell in row.cells if cell.text.strip()
                            )
                            if row_text:
                                slide_lines.append(row_text)

                combined_text = "\n".join(slide_lines).strip()
                if not combined_text and slide_title:
                    combined_text = slide_title

                if combined_text:
                    slides.append(
                        ExtractedPage(
                            page_number=idx,
                            section_title=slide_title,
                            text=combined_text,
                        )
                    )
        except Exception as e:
            logger.error(f"Error extracting text from PPTX {file_path}: {e}")
            raise ValueError(f"Không thể đọc file PPTX: {str(e)}")

        return slides

    def extract(self, file_path: Path, filename: str) -> List[ExtractedPage]:
        """Dispatch extraction based on file extension."""
        ext = Path(filename).suffix.lower()
        if ext == ".pdf":
            return self.extract_from_pdf(file_path)
        elif ext in [".docx", ".doc"]:
            return self.extract_from_docx(file_path)
        elif ext in [".pptx", ".ppt"]:
            return self.extract_from_pptx(file_path)
        else:
            raise ValueError(f"Định dạng tệp '{ext}' không được hỗ trợ. Chỉ hỗ trợ .pdf, .docx, .pptx.")


document_extractor = DocumentExtractor()

