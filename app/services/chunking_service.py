import re
from typing import List, Optional
from app.services.document_extractor import ExtractedPage
from app.schemas.document import ChunkItem


class ChunkingService:
    """
    Splits extracted document pages into semantic chunks with overlap.
    Guarantees that page_number, section_title, and order are preserved.
    """

    def __init__(
        self,
        target_chunk_size: int = 700,  # ~150 - 200 words
        overlap_size: int = 100,        # overlap window
        min_chunk_size: int = 50,       # filter out tiny fragments
    ):
        self.target_chunk_size = target_chunk_size
        self.overlap_size = overlap_size
        self.min_chunk_size = min_chunk_size

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences or paragraphs preserving punctuation."""
        # Split on paragraph breaks first, then sentence endings
        raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        units: List[str] = []

        for p in raw_paragraphs:
            # Split paragraph into sentences
            sentences = re.split(r"(?<=[.!?。])\s+", p)
            for s in sentences:
                s_clean = s.strip()
                if s_clean:
                    units.append(s_clean)

        return units

    def chunk_extracted_pages(
        self,
        pages: List[ExtractedPage],
    ) -> List[ChunkItem]:
        """
        Process a list of ExtractedPage objects and generate sequential ChunkItems.
        Chunks respect page/slide boundaries to preserve 100% citation provenance.
        """
        all_chunks: List[ChunkItem] = []
        global_chunk_index = 0
        current_section = None

        for page in pages:
            if page.section_title:
                current_section = page.section_title

            text = page.text.strip()
            if not text:
                continue

            # If page text is within target chunk size, make it a single chunk
            if len(text) <= self.target_chunk_size:
                all_chunks.append(
                    ChunkItem(
                        chunk_index=global_chunk_index,
                        section_title=current_section,
                        page_number=page.page_number,
                        text=text,
                    )
                )
                global_chunk_index += 1
                continue

            # For longer pages, chunk by sentences with overlap
            units = self._split_into_sentences(text)
            current_chunk_parts: List[str] = []
            current_length = 0

            for unit in units:
                unit_len = len(unit)

                if current_length + unit_len > self.target_chunk_size and current_chunk_parts:
                    # Flush current chunk
                    chunk_text = " ".join(current_chunk_parts).strip()
                    if len(chunk_text) >= self.min_chunk_size:
                        all_chunks.append(
                            ChunkItem(
                                chunk_index=global_chunk_index,
                                section_title=current_section,
                                page_number=page.page_number,
                                text=chunk_text,
                            )
                        )
                        global_chunk_index += 1

                    # Create overlap from the end of current chunk
                    overlap_parts: List[str] = []
                    overlap_len = 0
                    for prev_unit in reversed(current_chunk_parts):
                        if overlap_len + len(prev_unit) <= self.overlap_size:
                            overlap_parts.insert(0, prev_unit)
                            overlap_len += len(prev_unit)
                        else:
                            break

                    current_chunk_parts = overlap_parts + [unit]
                    current_length = sum(len(p) for p in current_chunk_parts)
                else:
                    current_chunk_parts.append(unit)
                    current_length += unit_len

            # Flush final chunk of the page
            if current_chunk_parts:
                final_text = " ".join(current_chunk_parts).strip()
                if len(final_text) >= self.min_chunk_size:
                    all_chunks.append(
                        ChunkItem(
                            chunk_index=global_chunk_index,
                            section_title=current_section,
                            page_number=page.page_number,
                            text=final_text,
                        )
                    )
                    global_chunk_index += 1

        return all_chunks


chunking_service = ChunkingService()
