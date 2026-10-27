"""Validasi unggahan berdasarkan isi berkas, bukan hanya ekstensi (PRD §17.3)."""

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from app.core.config import get_settings

ALLOWED = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "txt": "text/plain",
}


@dataclass
class ValidatedFile:
    source_format: str
    mime_type: str
    extension: str


class FileRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def safe_filename(name: str | None) -> str:
    base = PurePath((name or "").replace("\\", "/")).name.strip()
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*')
    return base[:255] or "berkas"


def validate_upload(filename: str, data: bytes) -> ValidatedFile:
    s = get_settings()
    if not data:
        raise FileRejected("EMPTY_FILE", "Berkas kosong.")
    if len(data) > s.max_upload_bytes:
        raise FileRejected("FILE_TOO_LARGE", f"Ukuran berkas melebihi batas {s.max_upload_mb} MB.")

    ext = PurePath(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise FileRejected("UNSUPPORTED_EXTENSION", "Hanya berkas DOCX, PDF, atau TXT yang diterima.")

    detected = _sniff(data)
    if detected != ext:
        raise FileRejected(
            "CONTENT_MISMATCH",
            f"Isi berkas tidak sesuai ekstensi .{ext}"
            + (f" (terdeteksi sebagai {detected.upper()})." if detected else "."),
        )
    if ext == "docx":
        _check_docx_archive(data)
    return ValidatedFile(source_format=ext, mime_type=ALLOWED[ext], extension=ext)


def _sniff(data: bytes) -> str | None:
    head = data[:1024]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            return None
        if "[Content_Types].xml" in names and "word/document.xml" in names:
            return "docx"
        return "zip"
    if head.startswith((b"\xd0\xcf\x11\xe0",)):
        return "doc"
    if _looks_like_text(data):
        return "txt"
    return None


def _looks_like_text(data: bytes) -> bool:
    sample = data[:65536]
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # Toleransi karakter multibyte yang terpotong di akhir sampel.
        if exc.start >= len(sample) - 4:
            return True
    # Teks 8-bit (mis. Windows-1252): tolak bila banyak byte kontrol.
    control = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return control / max(1, len(sample)) < 0.01


def _check_docx_archive(data: bytes) -> None:
    s = get_settings()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > s.max_docx_entries:
            raise FileRejected("ARCHIVE_TOO_MANY_ENTRIES", "Struktur DOCX tidak wajar (terlalu banyak entri).")
        total = 0
        for info in infos:
            name = info.filename
            if name.startswith("/") or ".." in PurePath(name).parts:
                raise FileRejected("ARCHIVE_UNSAFE_PATH", "DOCX berisi path yang tidak aman.")
            if info.flag_bits & 0x1:
                raise FileRejected("ARCHIVE_ENCRYPTED", "DOCX terenkripsi tidak didukung.")
            total += info.file_size
            if info.compress_size and info.file_size / info.compress_size > s.max_docx_compression_ratio and info.file_size > 1_000_000:
                raise FileRejected("ARCHIVE_SUSPICIOUS_RATIO", "DOCX memiliki rasio kompresi mencurigakan.")
        if total > s.max_docx_uncompressed_mb * 1024 * 1024:
            raise FileRejected("ARCHIVE_TOO_LARGE", "Isi DOCX setelah dibuka melebihi batas.")
        if any(i.filename.lower().endswith("vbaproject.bin") for i in infos):
            raise FileRejected("MACRO_NOT_ALLOWED", "DOCX berisi makro; simpan ulang sebagai .docx tanpa makro.")
