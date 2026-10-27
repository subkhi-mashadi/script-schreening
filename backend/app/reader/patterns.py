"""Pola deterministik untuk mengenali heading bila format sumber tidak membawa style heading."""

import re

# Bagian awal/akhir buku yang lazim; dikenali sebagai heading level 1 bila berdiri sendiri.
FRONT_BACK_MATTER = {
    "halaman judul",
    "halaman pengesahan",
    "halaman persembahan",
    "persembahan",
    "kata pengantar",
    "prakata",
    "pengantar",
    "sambutan",
    "daftar isi",
    "daftar tabel",
    "daftar gambar",
    "daftar lampiran",
    "daftar singkatan",
    "abstrak",
    "abstract",
    "ringkasan",
    "pendahuluan",
    "penutup",
    "epilog",
    "prolog",
    "daftar pustaka",
    "pustaka",
    "referensi",
    "bibliografi",
    "glosarium",
    "indeks",
    "lampiran",
    "biodata penulis",
    "tentang penulis",
    "profil penulis",
}

ROMAN = r"[IVXLCDM]+"
RE_BAB = re.compile(rf"^(BAB|Bab)\s+({ROMAN}|\d+)\b[\s.:\-–—]*(.*)$")
RE_PART = re.compile(rf"^(BAGIAN|Bagian)\s+({ROMAN}|\d+|[A-Z][a-z]+)\b[\s.:\-–—]*(.*)$")
# "1.2 Judul", "1.2.3. Judul" — harus diawali angka dengan minimal satu titik internal.
RE_NUMBERED = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(\S.*)$")
RE_MARKDOWN = re.compile(r"^(#{1,6})\s+(\S.*)$")
RE_PAGE_NUMBER = re.compile(rf"^(?:-\s*)?(?:\d{{1,4}}|{ROMAN.lower()}|{ROMAN})(?:\s*-)?$")

MAX_HEADING_CHARS = 150


def classify_heading(line: str) -> int | None:
    """Kembalikan level heading untuk baris tunggal, atau None bila bukan heading.

    Aturan sengaja konservatif: kalimat panjang atau yang diakhiri titik bukan heading.
    """
    text = " ".join(line.split())
    if not text or len(text) > MAX_HEADING_CHARS:
        return None
    if m := RE_MARKDOWN.match(text):
        return len(m.group(1))
    if RE_PART.match(text):
        return 1
    if RE_BAB.match(text):
        return 1
    if text.lower().rstrip(":") in FRONT_BACK_MATTER:
        return 1
    if m := RE_NUMBERED.match(text):
        if text.endswith((".", ",", ";")) and not text.endswith(".."):
            return None
        depth = m.group(1).count(".") + 1
        return min(depth, 6)
    return None


def strip_markdown_heading(line: str) -> str:
    m = RE_MARKDOWN.match(line.strip())
    return m.group(2) if m else line.strip()


def is_page_number_line(text: str) -> bool:
    return bool(RE_PAGE_NUMBER.match(text.strip()))
