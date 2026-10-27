"""Penilaian kualitas ekstraksi (deterministik).

Skor 0–100 hanya mengukur keterbacaan teks hasil ekstraksi, BUKAN mutu naskah.

    skor = 100
         − 100 × rasio halaman pindaian (PDF)
         − min(40, 2000 × rasio karakter rusak)       # U+FFFD, kontrol, private use
         − 20 bila jumlah karakter < ambang minimum
         − 15 bila tidak ada heading terdeteksi
    dibatasi ke rentang 0–100.

Status:
- EXTRACTED  : skor ≥ ambang, karakter ≥ minimum, rasio halaman pindaian ≤ batas;
- INCOMPLETE : salah satu syarat di atas tidak terpenuhi (screening tidak boleh final).
"""

import unicodedata
from dataclasses import dataclass

from app.core.config import get_settings
from app.reader.model import BlockType, NormalizedDocument, WarningCode


@dataclass
class QualityResult:
    score: float
    status: str  # EXTRACTED | INCOMPLETE
    reasons: list[str]
    metrics: dict


def _bad_char_count(text: str) -> tuple[int, int]:
    replacement = text.count("�")
    control = 0
    for ch in text:
        if ch in "\n\t":
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Co", "Cs"):
            control += 1
    return replacement, control


def assess(doc: NormalizedDocument) -> QualityResult:
    s = get_settings()
    text = doc.full_text
    chars = len(text.strip())
    replacement, control = _bad_char_count(text)
    bad_ratio = (replacement + control) / max(1, chars)
    pages = len(doc.pages)
    scanned = sum(1 for p in doc.pages if p.is_scanned)
    scanned_ratio = scanned / pages if pages else 0.0
    headings = sum(1 for b in doc.blocks if b.type == BlockType.HEADING)

    score = 100.0
    score -= 100.0 * scanned_ratio
    score -= min(40.0, 2000.0 * bad_ratio)
    if chars < s.min_extracted_chars:
        score -= 20.0
    if headings == 0:
        score -= 15.0
    score = round(max(0.0, min(100.0, score)), 2)

    if replacement:
        doc.warn(WarningCode.REPLACEMENT_CHARS, "Terdapat karakter yang tidak dapat didekode (�); kemungkinan masalah font/encoding.", count=replacement)
    if control:
        doc.warn(WarningCode.CONTROL_CHARS, "Terdapat karakter kontrol/tak lazim dalam teks hasil ekstraksi.", count=control)
    if headings == 0:
        doc.warn(WarningCode.NO_HEADINGS, "Tidak ada heading yang terdeteksi; struktur bab mungkin tidak terbaca.")
    if chars < s.min_extracted_chars:
        doc.warn(WarningCode.LOW_TEXT, f"Teks yang terekstrak hanya {chars} karakter (minimum {s.min_extracted_chars}).", severity="error")

    reasons: list[str] = []
    if chars < s.min_extracted_chars:
        reasons.append("LOW_TEXT")
    if scanned_ratio > s.max_scanned_page_ratio:
        reasons.append("SCANNED_PAGES")
    if score < s.min_extraction_quality:
        reasons.append("LOW_QUALITY_SCORE")

    return QualityResult(
        score=score,
        status="INCOMPLETE" if reasons else "EXTRACTED",
        reasons=reasons,
        metrics={
            "chars": chars,
            "bad_char_ratio": round(bad_ratio, 6),
            "replacement_chars": replacement,
            "control_chars": control,
            "pages": pages,
            "scanned_pages": scanned,
            "scanned_ratio": round(scanned_ratio, 4),
            "headings": headings,
            "thresholds": {
                "min_extracted_chars": s.min_extracted_chars,
                "min_extraction_quality": s.min_extraction_quality,
                "max_scanned_page_ratio": s.max_scanned_page_ratio,
            },
        },
    )
