"""Model dokumen ternormalisasi (PRD §13.3).

Seluruh reader (DOCX/PDF/TXT) menghasilkan struktur yang sama, sehingga mesin aturan
pada fase berikutnya hanya membaca satu format. Offset karakter (`char_start`/`char_end`)
menunjuk ke `NormalizedDocument.full_text`, yaitu teks blok yang digabung dengan
`BLOCK_SEPARATOR`.
"""

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# Duplikat ringan dari patterns.RE_BAB agar model tidak bergantung pada modul pola.
RE_CHAPTER = re.compile(r"^(?:BAB|Bab)\s+([IVXLCDM]+|\d+)\b[\s.:\-–—]*(.*)$")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

BLOCK_SEPARATOR = "\n\n"
PATH_SEPARATOR = " > "


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    QUOTE = "quote"
    FOOTNOTE = "footnote"
    CAPTION = "caption"


class WarningCode(StrEnum):
    SCANNED_PAGES = "SCANNED_PAGES"
    OCR_NOT_AVAILABLE = "OCR_NOT_AVAILABLE"
    LOW_TEXT = "LOW_TEXT"
    REPLACEMENT_CHARS = "REPLACEMENT_CHARS"
    CONTROL_CHARS = "CONTROL_CHARS"
    NO_HEADINGS = "NO_HEADINGS"
    PAGE_NUMBERS_ESTIMATED = "PAGE_NUMBERS_ESTIMATED"
    PAGE_NUMBERS_UNAVAILABLE = "PAGE_NUMBERS_UNAVAILABLE"
    HEADINGS_FROM_PATTERN = "HEADINGS_FROM_PATTERN"
    HEADINGS_FROM_FONT = "HEADINGS_FROM_FONT"
    RUNNING_HEADERS_REMOVED = "RUNNING_HEADERS_REMOVED"
    ENCODING_FALLBACK = "ENCODING_FALLBACK"
    UNSUPPORTED_ELEMENTS = "UNSUPPORTED_ELEMENTS"
    TRACKED_CHANGES = "TRACKED_CHANGES"
    ENCRYPTED = "ENCRYPTED"


@dataclass
class ExtractionWarning:
    code: str
    message: str
    severity: str = "warning"  # info | warning | error
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Block:
    type: str
    text: str
    level: int | None = None  # level heading (1 = bab)
    page_number: int | None = None
    style: str | None = None
    # Sumber deteksi heading: style | outline | toc | pattern | font
    detection: str | None = None
    locator: dict[str, Any] = field(default_factory=dict)
    # Diisi oleh `finalize`.
    block_id: str = ""
    index: int = 0
    section_path: str | None = None
    parent_index: int | None = None
    char_start: int = 0
    char_end: int = 0


@dataclass
class PageInfo:
    page_number: int
    char_count: int
    label: str | None = None  # nomor halaman tercetak bila terdeteksi
    has_images: bool = False
    is_scanned: bool = False


@dataclass
class NormalizedDocument:
    source_format: str
    engine_version: str
    blocks: list[Block] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[ExtractionWarning] = field(default_factory=list)
    page_numbers_reliable: bool = False
    # Jumlah halaman dan sumbernya: pdf | word_app_properties | page_breaks
    page_count: int | None = None
    page_count_source: str | None = None
    full_text: str = ""

    def warn(self, code: str, message: str, severity: str = "warning", **details: Any) -> None:
        self.warnings.append(ExtractionWarning(code=code, message=message, severity=severity, details=details))

    def finalize(self) -> "NormalizedDocument":
        """Beri ID, section path, parent heading, dan offset karakter secara deterministik."""
        self.blocks = [b for b in self.blocks if b.text.strip()]
        heading_stack: list[tuple[int, int, str]] = []  # (level, index, text)
        parts: list[str] = []
        cursor = 0
        for i, b in enumerate(self.blocks):
            # Heading sering memakai baris baru manual ("BAB 1⏎JUDUL"); satukan menjadi satu baris.
            b.text = " ".join(b.text.split()) if b.type == BlockType.HEADING else b.text.strip()
            b.index = i
            b.block_id = f"b{i + 1:06d}"
            if b.type == BlockType.HEADING:
                level = b.level or 1
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                b.parent_index = heading_stack[-1][1] if heading_stack else None
                heading_stack.append((level, i, _short(b.text)))
            else:
                b.parent_index = heading_stack[-1][1] if heading_stack else None
            b.section_path = PATH_SEPARATOR.join(h[2] for h in heading_stack) or None
            if parts:
                cursor += len(BLOCK_SEPARATOR)
            b.char_start = cursor
            b.char_end = cursor + len(b.text)
            cursor = b.char_end
            parts.append(b.text)
        self.full_text = BLOCK_SEPARATOR.join(parts)
        return self

    def chapters(self) -> list[dict[str, Any]]:
        """Heading yang berpola "BAB n" — dasar hitungan bab dan halaman awal tiap bab."""
        result = []
        for b in self.blocks:
            if b.type != BlockType.HEADING or not (m := RE_CHAPTER.match(b.text)):
                continue
            result.append(
                {
                    "block_id": b.block_id,
                    "number": chapter_number(m.group(1)),
                    "label": m.group(1),
                    "title": _short(m.group(2), 200) or None,
                    "page_number": b.page_number,
                    "page_estimate": b.locator.get("page_estimate"),
                    "section_path": b.section_path,
                }
            )
        return result

    def to_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for b in self.blocks:
            counts[b.type] = counts.get(b.type, 0) + 1
        return {
            "source_format": self.source_format,
            "engine_version": self.engine_version,
            "char_count": len(self.full_text),
            "word_count": len(self.full_text.split()),
            "block_count": len(self.blocks),
            "block_counts": counts,
            "page_count": self.page_count or (len(self.pages) or None),
            "page_count_source": self.page_count_source or ("pdf" if self.pages else None),
            "page_numbers_reliable": self.page_numbers_reliable,
            "chapters": self.chapters(),
            "toc_entries": [
                {"block_id": b.block_id, "title": b.locator["toc_title"], "page_label": b.locator["toc_page"]}
                for b in self.blocks
                if "toc_page" in b.locator
            ][:500],
            "scanned_pages": [p.page_number for p in self.pages if p.is_scanned],
            "headings": [
                {
                    "block_id": b.block_id,
                    "level": b.level,
                    "text": _short(b.text, 200),
                    "page_number": b.page_number,
                    "section_path": b.section_path,
                }
                for b in self.blocks
                if b.type == BlockType.HEADING
            ][:500],
            "metadata": self.metadata,
            "warnings": [asdict(w) for w in self.warnings],
        }


def chapter_number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    total, prev = 0, 0
    for ch in reversed(token.upper()):
        v = ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
