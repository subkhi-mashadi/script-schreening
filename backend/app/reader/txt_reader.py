"""Reader TXT (terutama untuk pengujian). Paragraf dipisah baris kosong; heading dari pola."""

import re

from app.reader.model import Block, BlockType, NormalizedDocument, WarningCode
from app.reader.patterns import RE_MARKDOWN, classify_heading, strip_markdown_heading

ENGINE_VERSION = "txt-reader/1.0"


class TxtReadError(Exception):
    pass


def decode_text(data: bytes) -> tuple[str, str]:
    encoding = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    try:
        return data.decode(encoding), encoding
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def read_txt(data: bytes) -> NormalizedDocument:
    text, encoding = decode_text(data)
    if "\x00" in text:
        raise TxtReadError("Berkas teks mengandung byte NUL; kemungkinan bukan teks biasa.")
    out = NormalizedDocument(source_format="txt", engine_version=ENGINE_VERSION)
    out.metadata = {"encoding": encoding}
    if encoding == "cp1252":
        out.warn(WarningCode.ENCODING_FALLBACK, "Berkas bukan UTF-8; dibaca sebagai Windows-1252.")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pattern_headings = 0
    for chunk in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
        if not lines:
            continue
        # Heading berdiri sendiri pada baris pertama chunk.
        level = classify_heading(lines[0])
        if level is not None:
            pattern_headings += 1
            out.blocks.append(
                Block(type=BlockType.HEADING, text=strip_markdown_heading(lines[0]), level=level,
                      detection="markdown" if RE_MARKDOWN.match(lines[0]) else "pattern")
            )
            lines = lines[1:]
            if not lines:
                continue
        body = " ".join(lines)
        out.blocks.append(Block(type=BlockType.PARAGRAPH, text=body))
    if pattern_headings:
        out.warn(WarningCode.HEADINGS_FROM_PATTERN, "Heading dikenali dari pola teks.", severity="info", count=pattern_headings)
    out.warn(WarningCode.PAGE_NUMBERS_UNAVAILABLE, "Berkas teks tidak memiliki nomor halaman.", severity="info")
    return out
