"""Reader PDF berbasis PyMuPDF.

Heading ditentukan secara deterministik dengan urutan prioritas:
1. outline/bookmark PDF (`toc`) bila ada;
2. pola teks (BAB, penomoran 1.2, bagian awal/akhir) yang didukung ciri visual (tebal/lebih besar);
3. ukuran font jauh di atas ukuran font isi (`font`).

Header/footer berulang dan nomor halaman di margin dibuang dari teks isi, tetapi nomor
halaman tercetak dicatat sebagai label halaman. Nomor halaman fisik PDF selalu tersedia.
"""

import re
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import version

import pymupdf

from app.core.config import get_settings
from app.reader.model import Block, BlockType, NormalizedDocument, PageInfo, WarningCode
from app.reader.patterns import RE_BAB, classify_heading, is_page_number_line

ENGINE_VERSION = f"pdf-reader/1.0 pymupdf/{version('pymupdf')}"

MARGIN_RATIO = 0.08
BOLD_FLAG = 1 << 4


class PdfReadError(Exception):
    def __init__(self, message: str, code: str = "PDF_UNREADABLE") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _RawBlock:
    page: int
    text: str
    size: float
    bold_ratio: float
    lines: int
    y0: float
    y1: float
    page_height: float

    @property
    def in_margin(self) -> bool:
        return self.y1 <= self.page_height * MARGIN_RATIO or self.y0 >= self.page_height * (1 - MARGIN_RATIO)


def read_pdf(data: bytes) -> NormalizedDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfReadError(f"PDF tidak dapat dibuka: {exc.__class__.__name__}") from exc

    with doc:
        if doc.needs_pass:
            raise PdfReadError("PDF terenkripsi dengan kata sandi. Unggah PDF tanpa kata sandi.", code="ENCRYPTED")
        if doc.page_count == 0:
            raise PdfReadError("PDF tidak memiliki halaman.", code="EMPTY_DOCUMENT")

        out = NormalizedDocument(source_format="pdf", engine_version=ENGINE_VERSION, page_numbers_reliable=True)
        out.metadata = {k: v for k, v in (doc.metadata or {}).items() if v and k != "encryption"}
        out.metadata["page_count"] = doc.page_count
        out.page_count, out.page_count_source = doc.page_count, "pdf"

        settings = get_settings()
        raw: list[_RawBlock] = []
        for page in doc:
            pno = page.number + 1
            page_blocks = _page_blocks(page, pno)
            chars = sum(len(b.text) for b in page_blocks)
            has_images = bool(page.get_images(full=False))
            label = page.get_label() or None
            out.pages.append(
                PageInfo(
                    page_number=pno,
                    char_count=chars,
                    label=label,
                    has_images=has_images,
                    is_scanned=has_images and chars < settings.scanned_page_char_threshold,
                )
            )
            raw.extend(page_blocks)

        toc = doc.get_toc(simple=True)

    raw = _drop_running_headers(raw, out)
    body_size = _body_font_size(raw)
    toc_index = _toc_index(toc)
    heading_sizes = sorted({round(b.size * 2) / 2 for b in raw if _looks_like_font_heading(b, body_size)}, reverse=True)

    counts = Counter()
    for b in raw:
        level, detection = _heading_level(b, body_size, toc_index, heading_sizes)
        if level is not None:
            counts[detection] += 1
            out.blocks.append(
                Block(type=BlockType.HEADING, text=b.text, level=level, page_number=b.page, detection=detection,
                      locator={"font_size": round(b.size, 1)})
            )
        else:
            out.blocks.append(Block(type=_body_type(b.text), text=b.text, page_number=b.page))

    scanned = [p.page_number for p in out.pages if p.is_scanned]
    if scanned:
        out.warn(
            WarningCode.SCANNED_PAGES,
            f"{len(scanned)} halaman tampak hasil pindai tanpa teks yang dapat diekstrak.",
            pages=scanned[:200],
        )
        out.warn(
            WarningCode.OCR_NOT_AVAILABLE,
            "OCR belum tersedia (FR-14, P1). Unggah DOCX atau PDF berbasis teks.",
        )
    if counts["font"]:
        out.warn(
            WarningCode.HEADINGS_FROM_FONT,
            "Sebagian heading dikenali dari ukuran font karena PDF tidak memiliki outline/bookmark.",
            severity="info",
            count=counts["font"],
        )
    if counts["pattern"]:
        out.warn(
            WarningCode.HEADINGS_FROM_PATTERN,
            "Sebagian heading dikenali dari pola teks.",
            severity="info",
            count=counts["pattern"],
        )
    return out


def _page_blocks(page: "pymupdf.Page", pno: int) -> list[_RawBlock]:
    height = page.rect.height or 1
    result: list[_RawBlock] = []
    data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
    for blk in data.get("blocks", []):
        if blk.get("type") != 0:
            continue
        line_texts: list[str] = []
        size_chars: Counter = Counter()
        bold_chars = 0
        total_chars = 0
        for line in blk.get("lines", []):
            spans = line.get("spans", [])
            lt = "".join(s.get("text", "") for s in spans)
            if not lt.strip():
                continue
            line_texts.append(" ".join(lt.split()))
            for s in spans:
                n = len(s.get("text", "").strip())
                if not n:
                    continue
                total_chars += n
                size_chars[round(s.get("size", 0), 1)] += n
                if s.get("flags", 0) & BOLD_FLAG or "bold" in s.get("font", "").lower():
                    bold_chars += n
        if not line_texts:
            continue
        text = _join_lines(line_texts)
        size = size_chars.most_common(1)[0][0] if size_chars else 0.0
        x0, y0, x1, y1 = blk["bbox"]
        result.append(
            _RawBlock(page=pno, text=text, size=size, bold_ratio=bold_chars / max(1, total_chars),
                      lines=len(line_texts), y0=y0, y1=y1, page_height=height)
        )
    return result


def _join_lines(lines: list[str]) -> str:
    """Gabung baris dalam satu blok. Tanda hubung di akhir baris dipertahankan
    (bahasa Indonesia memakai kata ulang seperti `buku-buku`), tanpa spasi tambahan."""
    out = lines[0]
    for ln in lines[1:]:
        out = out + ln if out.endswith("-") else out + " " + ln
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text.lower())).strip()


def _drop_running_headers(raw: list[_RawBlock], out: NormalizedDocument) -> list[_RawBlock]:
    pages = max((b.page for b in raw), default=0)
    margin_keys = Counter(_norm(b.text) for b in raw if b.in_margin)
    threshold = max(3, int(pages * 0.3))
    running = {k for k, c in margin_keys.items() if c >= threshold}
    kept: list[_RawBlock] = []
    removed = 0
    for b in raw:
        if b.in_margin and (is_page_number_line(b.text) or _norm(b.text) in running):
            removed += 1
            if is_page_number_line(b.text):
                info = out.pages[b.page - 1]
                info.label = info.label or b.text.strip(" -")
            continue
        kept.append(b)
    if removed:
        out.warn(
            WarningCode.RUNNING_HEADERS_REMOVED,
            "Header/footer berulang dan nomor halaman di margin dikeluarkan dari teks isi.",
            severity="info",
            count=removed,
        )
    return kept


def _body_font_size(raw: list[_RawBlock]) -> float:
    weights: Counter = Counter()
    for b in raw:
        weights[round(b.size * 2) / 2] += len(b.text)
    return weights.most_common(1)[0][0] if weights else 0.0


def _toc_index(toc: list) -> dict[int, list[tuple[int, str]]]:
    idx: dict[int, list[tuple[int, str]]] = {}
    for lvl, title, page in toc:
        if page > 0 and title.strip():
            idx.setdefault(page, []).append((lvl, _norm(title)))
    return idx


def _looks_like_font_heading(b: _RawBlock, body_size: float) -> bool:
    text = b.text.strip()
    return (
        body_size > 0
        and b.size >= body_size * 1.2
        and b.lines <= 3
        and len(text) <= 150
        and not text.endswith((".", ",", ";"))
        and not is_page_number_line(text)
    )


def _heading_level(b: _RawBlock, body_size: float, toc_index, heading_sizes: list[float]) -> tuple[int | None, str | None]:
    text = b.text.strip()
    norm = _norm(text)
    for lvl, title in toc_index.get(b.page, []):
        if norm == title or (len(title) >= 4 and (norm.startswith(title) or title.startswith(norm)) and len(text) <= 200):
            return lvl, "toc"
    if toc_index:
        # Outline tersedia: hanya heading yang tercantum di outline yang dipakai, kecuali pola BAB.
        if RE_BAB.match(text) and b.lines <= 3:
            return 1, "pattern"
        return None, None
    pattern_level = classify_heading(text) if b.lines <= 3 else None
    if pattern_level is not None and (b.bold_ratio >= 0.6 or b.size >= body_size * 1.1 or RE_BAB.match(text)):
        return pattern_level, "pattern"
    if _looks_like_font_heading(b, body_size):
        rank = heading_sizes.index(round(b.size * 2) / 2) + 1 if heading_sizes else 1
        return min(rank, 4), "font"
    return None, None


RE_LIST_ITEM = re.compile(r"^(?:[•‣◦⁃∙•·\-–*]|\(?\d{1,3}[.)]|\(?[a-z][.)])\s+\S")


def _body_type(text: str) -> str:
    return BlockType.LIST_ITEM if RE_LIST_ITEM.match(text) else BlockType.PARAGRAPH
