"""Tampilan dokumen yang dibaca mesin aturan.

Dibangun dari `document_sections` (screening tersimpan) atau langsung dari hasil
ekstraksi (simulasi rule set tanpa menyimpan). Seluruh aturan hanya membaca kelas ini.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentSection, DocumentVersion, Manuscript
from app.reader.model import RE_CHAPTER, NormalizedDocument, chapter_number


@dataclass
class Blk:
    index: int
    block_id: str
    type: str
    text: str
    level: int | None = None
    section_path: str | None = None
    page_number: int | None = None
    page_estimate: int | None = None
    char_start: int = 0
    char_end: int = 0
    locator: dict[str, Any] = field(default_factory=dict)
    section_id: uuid.UUID | None = None

    @property
    def is_heading(self) -> bool:
        return self.type == "heading"

    @property
    def is_toc(self) -> bool:
        return self.locator.get("role") == "toc_entry"

    @property
    def page(self) -> int | None:
        return self.page_number or self.page_estimate


@dataclass
class Chapter:
    heading: Blk
    number: int | None
    label: str
    title: str
    blocks: list[Blk]

    @property
    def words(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks)


@dataclass
class ManuscriptInfo:
    title: str
    manuscript_type: str
    language_code: str
    authors: list[str]
    metadata: dict[str, Any]
    has_submitted_at: bool


def norm(text: str) -> str:
    """Normalisasi untuk pencocokan: huruf kecil, tanpa aksen/tanda baca, spasi tunggal."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\s]", " ", t.lower())
    return " ".join(t.split())


class DocView:
    def __init__(self, blocks: list[Blk], summary: dict[str, Any], manuscript: ManuscriptInfo, extraction_status: str) -> None:
        self.blocks = blocks
        self.summary = summary
        self.manuscript = manuscript
        self.extraction_status = extraction_status
        self.cache: dict[str, Any] = {}  # dipakai bersama antar-aturan dalam satu eksekusi
        self.layout: dict[str, Any] | None = None  # hasil app.reader.layout, hanya untuk tahap cek layout

    # --- konstruksi ---------------------------------------------------------

    @classmethod
    def from_db(cls, db: Session, version: DocumentVersion) -> "DocView":
        rows = db.scalars(
            select(DocumentSection).where(DocumentSection.document_version_id == version.id).order_by(DocumentSection.paragraph_index)
        ).all()
        blocks = [
            Blk(
                index=r.paragraph_index,
                block_id=r.block_id,
                type=r.section_type,
                text=r.text_content,
                level=r.heading_level,
                section_path=r.section_path,
                page_number=r.page_number,
                page_estimate=r.locator_json.get("page_estimate"),
                char_start=r.char_start,
                char_end=r.char_end,
                locator=r.locator_json,
                section_id=r.id,
            )
            for r in rows
        ]
        m: Manuscript = db.get(Manuscript, version.manuscript_id)
        return cls(blocks, version.extraction_summary_json or {}, manuscript_info(m), version.extraction_status)

    @classmethod
    def from_document(cls, doc: NormalizedDocument, manuscript: ManuscriptInfo, extraction_status: str) -> "DocView":
        blocks = [
            Blk(
                index=b.index,
                block_id=b.block_id,
                type=b.type,
                text=b.text,
                level=b.level,
                section_path=b.section_path,
                page_number=b.page_number,
                page_estimate=b.locator.get("page_estimate"),
                char_start=b.char_start,
                char_end=b.char_end,
                locator=b.locator,
            )
            for b in doc.blocks
        ]
        return cls(blocks, doc.to_summary(), manuscript, extraction_status)

    # --- navigasi struktur ---------------------------------------------------

    @cached_property
    def headings(self) -> list[Blk]:
        return [b for b in self.blocks if b.is_heading]

    @cached_property
    def chapters(self) -> list[Chapter]:
        heads = [(b, m) for b in self.headings if (m := RE_CHAPTER.match(b.text))]
        result = []
        for i, (h, m) in enumerate(heads):
            end = heads[i + 1][0].index if i + 1 < len(heads) else self._end_of_chapter(h)
            body = [b for b in self.blocks[h.index + 1 : end]]
            result.append(Chapter(heading=h, number=chapter_number(m.group(1)), label=m.group(1), title=m.group(2).strip(), blocks=body))
        return result

    def _end_of_chapter(self, h: Blk) -> int:
        """Bab terakhir berakhir pada heading level sama/lebih tinggi berikutnya (mis. DAFTAR PUSTAKA)."""
        for b in self.blocks[h.index + 1 :]:
            if b.is_heading and (b.level or 1) <= (h.level or 1):
                return b.index
        return len(self.blocks)

    @cached_property
    def body_start(self) -> int:
        """Indeks blok pertama isi utama: bab pertama, atau heading level-1 pertama setelah daftar isi."""
        if self.chapters:
            return self.chapters[0].heading.index
        toc_seen = False
        for h in self.headings:
            n = norm(h.text)
            if n.startswith("daftar isi"):
                toc_seen = True
                continue
            if toc_seen and (h.level or 1) == 1:
                return h.index
        return max(1, len(self.blocks) // 10)

    @cached_property
    def front_matter(self) -> list[Blk]:
        return self.blocks[: self.body_start]

    def section_of(self, heading: Blk) -> list[Blk]:
        """Blok di bawah heading sampai heading berikutnya dengan level sama/lebih tinggi."""
        out = []
        for b in self.blocks[heading.index + 1 :]:
            if b.is_heading and (b.level or 1) <= (heading.level or 1):
                break
            out.append(b)
        return out

    def find_section(self, aliases: list[str], scope: list[Blk] | None = None, allow_paragraph: bool = True) -> Blk | None:
        """Heading (atau baris pendek mandiri) yang teksnya sama/diawali salah satu alias."""
        targets = [norm(a) for a in aliases]
        for b in scope if scope is not None else self.blocks:
            if b.is_toc:
                continue
            if not b.is_heading and (not allow_paragraph or len(b.text) > 80):
                continue
            n = norm(b.text)
            # Toleransi "BAB I PENDAHULUAN" untuk alias "pendahuluan".
            n_wo_chapter = norm(RE_CHAPTER.sub(r"\2", b.text)) if RE_CHAPTER.match(b.text) else n
            for t in targets:
                if n == t or n.startswith(t + " ") or n_wo_chapter == t or n_wo_chapter.startswith(t + " "):
                    return b
        return None

    @cached_property
    def toc_entries(self) -> list[Blk]:
        entries = [b for b in self.blocks if b.is_toc]
        if entries:
            return entries
        toc = self.find_section(["daftar isi"], allow_paragraph=False)
        return [b for b in self.section_of(toc) if not b.is_heading] if toc else []

    def body_blocks(self, exclude_toc: bool = True) -> list[Blk]:
        return [b for b in self.blocks if not (exclude_toc and b.is_toc)]

    @property
    def page_count(self) -> int | None:
        return self.summary.get("page_count")

    @property
    def pages_reliable(self) -> bool:
        return bool(self.summary.get("page_numbers_reliable"))


def manuscript_info(m: Manuscript) -> ManuscriptInfo:
    return ManuscriptInfo(
        title=m.working_title,
        manuscript_type=m.manuscript_type,
        language_code=m.language_code,
        authors=[a.author_name for a in m.authors],
        metadata=m.metadata_json or {},
        has_submitted_at=m.submitted_at is not None,
    )
