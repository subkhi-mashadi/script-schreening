"""Document Reader: berkas → model dokumen ternormalisasi + penilaian kualitas ekstraksi."""

from dataclasses import dataclass

from app.reader.docx_reader import DocxReadError, read_docx
from app.reader.model import Block, BlockType, NormalizedDocument
from app.reader.patterns import FRONT_BACK_MATTER, RE_BAB
from app.reader.pdf_reader import PdfReadError, read_pdf
from app.reader.quality import QualityResult, assess
from app.reader.txt_reader import TxtReadError, read_txt

READERS = {"docx": read_docx, "pdf": read_pdf, "txt": read_txt}


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ExtractionResult:
    document: NormalizedDocument
    quality: QualityResult


def merge_split_chapter_headings(doc: NormalizedDocument) -> None:
    """Gabungkan pola umum buku Indonesia: "BAB I" lalu judul bab di blok berikutnya.

    Blok berikutnya digabung bila pendek (≤ 120 karakter), tidak diakhiri titik, dan
    berupa heading atau ditulis kapital.
    """
    merged: list[Block] = []
    i = 0
    blocks = doc.blocks
    while i < len(blocks):
        b = blocks[i]
        m = RE_BAB.match(b.text.strip())
        if b.type == BlockType.HEADING and m and not m.group(3).strip() and i + 1 < len(blocks):
            nxt = blocks[i + 1]
            t = nxt.text.strip()
            same_page = nxt.page_number == b.page_number
            if (
                same_page
                and len(t) <= 120
                and not t.endswith(".")
                and nxt.type in (BlockType.HEADING, BlockType.PARAGRAPH)
                and (nxt.type == BlockType.HEADING or t.isupper() or t.lower() in FRONT_BACK_MATTER)
            ):
                b.text = f"{b.text.strip()} {t}"
                b.locator = {**b.locator, "merged_with_next": True}
                merged.append(b)
                i += 2
                continue
        merged.append(b)
        i += 1
    doc.blocks = merged


def extract(source_format: str, data: bytes) -> ExtractionResult:
    reader = READERS.get(source_format)
    if reader is None:
        raise ExtractionError("UNSUPPORTED_FORMAT", f"Format {source_format} tidak didukung.")
    try:
        doc = reader(data)
    except PdfReadError as exc:
        raise ExtractionError(exc.code, str(exc)) from exc
    except (DocxReadError, TxtReadError) as exc:
        raise ExtractionError("UNREADABLE", str(exc)) from exc
    merge_split_chapter_headings(doc)
    doc.finalize()
    quality = assess(doc)
    return ExtractionResult(document=doc, quality=quality)


__all__ = ["ExtractionError", "ExtractionResult", "NormalizedDocument", "extract"]
