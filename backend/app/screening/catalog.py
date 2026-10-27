"""Katalog awal aturan dan rubrik (PRD §10–11).

Semua ambang, bobot, dan daftar kata adalah USULAN kebijakan internal awal. Aturan berlabel
`official_procedure` merujuk halaman Perpusnas dan berstatus `unverified` sampai pemilik proses
memverifikasinya terhadap teks resmi yang berlaku; selama belum diverifikasi, hasilnya
`needs_verification`, bukan pass/fail resmi.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import MANUSCRIPT_TYPES
from app.models import RubricCriterion, RubricVersion, Rule, RuleSet, RuleSetItem

PERPUSNAS_PROSEDUR = ("Prosedur penerbit dan pengajuan ISBN — Perpusnas", "https://isbn.perpusnas.go.id/landing_page/prosedur")
PERPUSNAS_11_2025 = (
    "Peraturan Perpustakaan Nasional No. 11 Tahun 2025 tentang Layanan Angka Standar Buku Internasional",
    "https://www.peraturan.go.id/files/perpusnas-no-11-tahun-2025.pdf",
)
VERIFIED_NOTE = "Diverifikasi terhadap teks Peraturan Perpusnas No. 11 Tahun 2025 (diakses 26-10-2026)."
JUKNIS_ISBN = (
    "Petunjuk Teknis Layanan ISBN, Perpustakaan Nasional RI (27-01-2023)",
    "https://admin-isbn.perpusnas.go.id/files/dokumen_surat/Petunjuk%20Teknis%20Layanan%20ISBN%20-%2020230127.pdf",
)
# Penanda revisi katalog: naikkan saat definisi aturan/rubrik di file ini berubah agar basis data ikut disinkronkan.
CATALOG_REVISION = 4
CATALOG_MARKER = f"[katalog r{CATALOG_REVISION}]"
PERPUSNAS_INFO = ("Informasi ISBN — Perpusnas", "https://isbn.perpusnas.go.id/landing_page/isbn_info")
PERPUSNAS_REGULASI = ("Regulasi ISBN — Perpusnas", "https://isbn.perpusnas.go.id/landing_page/regulasi/6")

SCIENTIFIC = ["buku_ilmiah", "buku_ajar", "referensi", "monograf", "prosiding"]

# Daftar kelola internal bentuk tidak baku → baku (mengacu KBBI). Dapat diperluas lewat versi rule set baru.
NONSTANDARD_WORDS = {
    "aktifitas": "aktivitas", "analisa": "analisis", "apotik": "apotek", "atlit": "atlet", "praktek": "praktik",
    "resiko": "risiko", "sistim": "sistem", "kwalitas": "kualitas", "kwantitas": "kuantitas", "nasehat": "nasihat",
    "ijin": "izin", "jaman": "zaman", "hutang": "utang", "merubah": "mengubah", "silahkan": "silakan", "antri": "antre",
    "cidera": "cedera", "detil": "detail", "diagnosa": "diagnosis", "efektifitas": "efektivitas", "frekwensi": "frekuensi",
    "hipotesa": "hipotesis", "ijasah": "ijazah", "jadual": "jadwal", "karir": "karier", "komplek": "kompleks",
    "lembab": "lembap", "mengkonsumsi": "mengonsumsi", "mempengaruhi": "memengaruhi", "menterjemahkan": "menerjemahkan",
    "obyek": "objek", "subyek": "subjek", "propinsi": "provinsi", "sekedar": "sekadar", "standarisasi": "standardisasi",
    "tehnik": "teknik", "trampil": "terampil", "nafas": "napas", "kongkrit": "konkret", "do'a": "doa", "jum'at": "Jumat",
    "terlanjur": "telanjur", "himbau": "imbau", "himbauan": "imbauan", "ijazah": "ijazah", "kadaluarsa": "kedaluwarsa",
    "kadaluwarsa": "kedaluwarsa", "fikir": "pikir", "berfikir": "berpikir", "pikiran": "pikiran", "rejeki": "rezeki",
    "sholat": "salat", "ramadhan": "Ramadan", "nampak": "tampak", "nampaknya": "tampaknya", "mengenyampingkan": "mengesampingkan",
    "memperhatikan": "memperhatikan", "sentausa": "sentosa", "tapi": "tetapi", "gimana": "bagaimana", "nggak": "tidak",
    "enggak": "tidak", "gak": "tidak", "aja": "saja", "udah": "sudah", "dimana": "di mana", "kemana": "ke mana",
}
# "tapi" dan bentuk cakapan sering wajar dalam dialog fiksi; rule fiksi memakai daftar tanpa bentuk cakapan.
CONVERSATIONAL = {"tapi", "gimana", "nggak", "enggak", "gak", "aja", "udah"}
# Bentuk identik ("ijazah", "pikiran", "memperhatikan") tidak dicek.
NONSTANDARD_WORDS = {k: v for k, v in NONSTANDARD_WORDS.items() if k != v.lower()}

JOINED_PREPOSITIONS = {
    "disana": "di sana", "disini": "di sini", "disitu": "di situ", "dirumah": "di rumah", "disekolah": "di sekolah",
    "dikantor": "di kantor", "diatas": "di atas", "dibawah": "di bawah", "didalam": "di dalam", "diluar": "di luar",
    "didepan": "di depan", "dibelakang": "di belakang", "disamping": "di samping", "diantara": "di antara",
    "disekitar": "di sekitar", "kesana": "ke sana", "kesini": "ke sini", "kesitu": "ke situ", "kerumah": "ke rumah",
    "kesekolah": "ke sekolah", "kekantor": "ke kantor", "kedepan": "ke depan", "kebelakang": "ke belakang",
    "kedalam": "ke dalam", "keatas": "ke atas", "kebawah": "ke bawah", "kepasar": "ke pasar", "keladang": "ke ladang",
    "dipasar": "di pasar", "diladang": "di ladang", "dihalaman": "di halaman", "didapur": "di dapur", "dikebun": "di kebun",
}

TERM_GROUPS = [
    ["e-mail", "email", "surel", "surat elektronik"],
    ["website", "situs web", "laman"],
    ["online", "daring"],
    ["offline", "luring"],
    ["download", "unduh"],
    ["upload", "unggah"],
    ["smartphone", "ponsel pintar", "telepon pintar"],
]

BIODATA = {"label": "Biodata penulis", "aliases": ["biodata penulis", "tentang penulis", "profil penulis", "biografi penulis", "riwayat penulis"],
           "severity": "minor", "action": "Tambahkan biodata singkat penulis di bagian akhir buku."}
SYNOPSIS = {"label": "Sinopsis", "aliases": ["sinopsis", "blurb", "ringkasan cerita", "ringkasan buku"], "severity": "minor",
            "satisfied_by_metadata": "synopsis", "action": "Tambahkan sinopsis (di naskah atau di metadata naskah) untuk sampul belakang."}
INTRO = {"label": "Pendahuluan", "aliases": ["pendahuluan"], "severity": "major", "action": "Tambahkan bab/bagian pendahuluan."}
CLOSING = {"label": "Penutup/simpulan", "aliases": ["penutup", "simpulan", "kesimpulan", "kesimpulan dan saran", "simpulan dan saran"],
           "severity": "major", "action": "Tambahkan bab/bagian penutup atau simpulan."}
GLOSSARY = {"label": "Glosarium", "aliases": ["glosarium", "daftar istilah"], "severity": "minor", "action": "Tambahkan glosarium istilah penting."}
INDEX = {"label": "Indeks", "aliases": ["indeks"], "severity": "minor", "action": "Tambahkan indeks untuk buku ilmiah/ajar/referensi."}


def _rule(code, title, category, track, engine_key, *, severity="minor", authority="editorial_indicator", config=None,
          scoring=None, blocking=False, human=False, types=None, order=100, source=None, description=None, reference=None,
          verified=False) -> dict:
    return {
        **({"verification_status": "verified", "verification_note": VERIFIED_NOTE, "verified_at": datetime(2026, 10, 26, tzinfo=UTC)}
           if verified else {}),
        "rule_code": code, "title": title, "category": category, "track": track, "engine_key": engine_key,
        "severity": severity, "authority_type": authority, "config_json": config or {}, "scoring_effect": scoring or {},
        "blocking": blocking, "requires_human_verification": human, "applies_to_types": types, "execution_order": order,
        "source_title": source[0] if source else None, "source_url": source[1] if source else None,
        "source_reference": reference, "description": description,
    }


def _ded(criterion: str, per: float, cap: float) -> dict:
    return {"criterion_code": criterion, "deduction_per_finding": per, "max_deduction": cap}


RULES: list[dict] = [
    # --- Tahap 1: kelayakan ISBN (Perpusnas 11/2025 Pasal 10 ayat (3)) ----------------
    # Penentu kelayakan (blocking): halaman awal huruf b dan naskah akhir huruf c — dapat diperiksa dari naskah.
    _rule("ISB-001", "Halaman judul tersedia (judul, penulis, penerbit)", "isbn_admin", "compliance", "isbn_title_page",
          severity="major", authority="official_regulation", blocking=True, order=10, source=PERPUSNAS_11_2025, verified=True,
          reference="Pasal 10 ayat (3) huruf b angka 1",
          description="Halaman awal yang diunggah saat pengajuan ISBN harus memuat halaman judul."),
    _rule("ISB-002", "Halaman balik halaman judul tersedia (hak cipta & penerbit)", "isbn_admin", "compliance",
          "isbn_copyright_page", severity="major", authority="official_regulation", blocking=True, order=11, source=PERPUSNAS_11_2025,
          verified=True, reference="Pasal 10 ayat (3) huruf b angka 2; Pasal 13 (ISBN & KDT dicantumkan di halaman ini)"),
    _rule("ISB-003", "Kata pengantar tersedia", "isbn_admin", "compliance", "isbn_section_present",
          severity="major", authority="official_regulation", blocking=True, order=12, source=PERPUSNAS_11_2025, verified=True,
          reference="Pasal 10 ayat (3) huruf b angka 3; Juknis 4.3.3 (karya sastra & komik boleh tanpa kata pengantar)",
          config={"label": "Kata pengantar", "aliases": ["kata pengantar", "prakata", "pengantar penulis", "sekapur sirih", "pengantar"],
                  "action": "Tambahkan kata pengantar/prakata.", "optional_for_fiction": True}),
    _rule("ISB-004", "Daftar isi tersedia", "isbn_admin", "compliance", "isbn_section_present",
          severity="major", authority="official_regulation", blocking=True, order=13, source=PERPUSNAS_11_2025, verified=True,
          reference="Pasal 10 ayat (3) huruf b angka 4; Juknis 4.2.1 butir 7 & 4.3.3 (tidak wajib untuk fiksi)",
          config={"label": "Daftar isi", "aliases": ["daftar isi"], "action": "Tambahkan daftar isi (gunakan fitur Table of Contents).",
                  "optional_for_fiction": True}),
    _rule("ISB-010", "Naskah sudah final (tanpa teks sementara)", "isbn_admin", "compliance", "isbn_final_manuscript",
          severity="major", authority="official_regulation", blocking=True, order=14, source=PERPUSNAS_11_2025, verified=True,
          reference="Pasal 10 ayat (3) huruf c (naskah akhir terbitan)",
          description="Yang diajukan adalah naskah akhir; teks sementara (TODO, [isi di sini], lorem ipsum) menandakan naskah belum final."),
    _rule("ISB-014", "Terbitan untuk masyarakat umum (bukan cetak terbatas)", "isbn_admin", "compliance", "isbn_public_distribution",
          severity="critical", authority="official_regulation", blocking=True, order=15, source=PERPUSNAS_11_2025, verified=True,
          reference="Pasal 2 ayat (2); Juknis Layanan ISBN 4.5, 4.5.1.3 butir 6–9, 4.5.2.3",
          description="Pernyataan cetak terbatas di naskah atau peredaran terbatas → tidak layak. Novel, biografi, buku anak, "
          "antologi harus ditujukan untuk dijual ke masyarakat umum."),
    # Peringatan (tidak menentukan kelayakan).
    _rule("ISB-011", "Jenis terbitan untuk umum", "isbn_admin", "compliance", "isbn_publication_type",
          severity="minor", authority="official_regulation", blocking=False, order=16, source=PERPUSNAS_11_2025, verified=True,
          reference="Pasal 2 ayat (2): disebarluaskan dan dapat diakses secara umum; Juknis 4.5.2",
          description="Indikasi dari halaman awal; skripsi/tesis/laporan internal dalam format asli lazimnya tidak diberi ISBN."),
    _rule("ISB-005", "Data naskah lengkap (judul, penulis, jenis, bahasa)", "isbn_admin", "compliance", "isbn_application_metadata",
          severity="minor", authority="publisher_policy", blocking=False, order=17, verified=True,
          description="Data ini diisi di formulir pengajuan ISBN; lengkapi di metadata naskah."),
    _rule("ISB-009", "Jumlah halaman memenuhi minimum", "isbn_admin", "compliance", "min_pages",
          severity="major", authority="official_procedure", blocking=True, order=15, source=JUKNIS_ISBN, verified=True,
          reference="Juknis 4.2.3 butir 8 & 4.3.2 (buku umum/ilmiah min. 49 halaman); 4.3.1 (buku anak min. 8 halaman)",
          description="Draf DOCX berukuran A4/Letter dinilai ulang setelah ditata ke ukuran buku.",
          config={"min_pages": 49, "by_type": {"buku_anak": 8}, "draft_page_height_cm": 27}),
    # Dokumen pengajuan di luar naskah: ditampilkan sebagai daftar persiapan, tidak menentukan kelayakan naskah.
    _rule("ISB-012", "Surat permohonan ISBN (kop resmi, ditandatangani pimpinan, distempel)", "isbn_admin", "compliance", "human_evidence",
          severity="major", authority="official_regulation", order=20, source=PERPUSNAS_11_2025, verified=True, human=True,
          reference="Pasal 10 ayat (3) huruf a",
          config={"evidence": "Surat permohonan ISBN", "explanation": "Siapkan saat pengajuan; format ada di Lampiran peraturan."}),
    _rule("ISB-006", "Surat pernyataan keaslian karya bermeterai", "isbn_admin", "compliance", "human_evidence",
          severity="major", authority="official_regulation", order=21, source=PERPUSNAS_11_2025, verified=True, human=True,
          reference="Pasal 10 ayat (3) huruf d dan ayat (5)",
          config={"evidence": "Surat pernyataan keaslian karya",
                  "explanation": "Ditandatangani penulis (karya perorangan), penulis pertama (karya bersama), editor (bunga rampai), dst."}),
    _rule("ISB-007", "Surat izin penerjemahan dari pemilik hak cipta", "isbn_admin", "compliance", "human_evidence",
          severity="major", authority="official_regulation", order=22, source=PERPUSNAS_11_2025, verified=True, human=True,
          reference="Pasal 10 ayat (3) huruf e",
          config={"evidence": "Surat izin penerjemahan", "only_if_translation": True}),
    _rule("ISB-013", "Surat pengalihan penerbitan / keterangan karya milik umum (bila berlaku)", "isbn_admin", "compliance", "human_evidence",
          severity="minor", authority="official_regulation", order=23, source=PERPUSNAS_11_2025, verified=True, human=True,
          reference="Pasal 10 ayat (3) huruf f dan g",
          config={"evidence": "Surat pengalihan / keterangan public domain",
                  "explanation": "Hanya untuk karya yang dialihkan dari penerbit lain atau karya milik umum."}),
    _rule("ISB-015", "Link katalog buku di website penerbit (harga & cara memperoleh)", "isbn_admin", "compliance", "human_evidence",
          severity="major", authority="official_procedure", order=25, source=JUKNIS_ISBN, verified=True, human=True,
          reference="Juknis Layanan ISBN bagian 5 (ruas link): wajib, katalog memuat cover, judul, penulis, harga, sinopsis, cara memperoleh",
          config={"evidence": "Link katalog buku di website penerbit",
                  "explanation": "Siapkan halaman katalog judul ini di website penerbit sebelum mengajukan ISBN."}),
    _rule("ISB-008", "Naskah akhir berformat PDF dengan watermark", "isbn_admin", "compliance", "human_evidence",
          severity="major", authority="official_regulation", order=24, source=PERPUSNAS_11_2025, verified=True, human=True,
          reference="Pasal 10 ayat (3) huruf c dan ayat (4)",
          config={"evidence": "Naskah akhir PDF bermarkah tirta (watermark)",
                  "explanation": "Semua dokumen pengajuan diunggah sebagai PDF; naskah akhir diberi watermark."}),
    # --- Teknis & struktur ---------------------------------------------------------
    _rule("TEC-001", "Tidak ada teks placeholder", "technical", "editorial", "placeholder_text",
          severity="major", order=20, scoring=_ded("format_technical", 10, 30)),
    _rule("STR-001", "Bagian wajib sesuai jenis naskah tersedia", "structure", "editorial", "required_sections",
          severity="major", order=30, scoring=_ded("structure_completeness", 15, 60),
          config={"by_type": {
              "fiksi": [SYNOPSIS, BIODATA],
              "buku_anak": [SYNOPSIS],
              "biografi": [SYNOPSIS, BIODATA],
              "prosiding": [BIODATA],
              "buku_ilmiah": [INTRO, CLOSING, BIODATA, INDEX],
              "monograf": [INTRO, CLOSING, BIODATA, INDEX],
              "referensi": [BIODATA, INDEX],
              "buku_ajar": [GLOSSARY, BIODATA, INDEX],
              "nonfiksi_umum": [BIODATA],
              "terjemahan": [BIODATA],
              "kompilasi": [BIODATA],
          }, "default": [BIODATA]}),
    _rule("STR-002", "Nomor bab berurutan dan seragam", "structure", "editorial", "chapter_sequence",
          severity="major", order=31, scoring=_ded("chapter_consistency", 15, 45)),
    _rule("STR-003", "Tingkat judul tidak melompat", "structure", "editorial", "heading_level_jump",
          severity="minor", order=32, scoring=_ded("chapter_consistency", 5, 20)),
    _rule("STR-004", "Daftar isi cocok dengan bab di naskah", "structure", "editorial", "toc_consistency",
          severity="minor", order=33, scoring=_ded("chapter_consistency", 5, 30)),
    _rule("STR-005", "Bab tidak terlalu pendek (indikator)", "structure", "editorial", "short_chapter",
          severity="info", order=34, config={"min_words": 300}, scoring=_ded("structure_completeness", 0, 0)),
    _rule("STR-006", "Judul bab lengkap dan seragam", "structure", "editorial", "chapter_title_style",
          severity="minor", order=35, scoring=_ded("chapter_consistency", 5, 20)),
    # --- Pengulangan -----------------------------------------------------------------
    _rule("DUP-001", "Tidak ada pengulangan isi di dalam naskah", "repetition", "editorial", "duplicate_content",
          severity="major", order=40, scoring=_ded("internal_repetition", 10, 60),
          config={"min_chars": 120, "min_run_blocks": 3, "min_run_chars": 60, "near_threshold": 0.9, "near_min_chars": 250, "max_findings": 50}),
    # --- Bahasa ----------------------------------------------------------------------
    _rule("LAN-001", "Spasi dan tanda baca rapi", "language", "editorial", "typography",
          severity="minor", order=50, scoring=_ded("format_technical", 1, 25), config={"max_findings": 150}),
    _rule("LAN-002", "Kata baku (daftar kelola)", "language", "editorial", "word_list",
          severity="minor", order=51, scoring=_ded("language_terms", 1, 30), types=[t for t in MANUSCRIPT_TYPES if t != "fiksi"],
          config={"dictionary": NONSTANDARD_WORDS, "source": "Daftar kelola internal, mengacu KBBI", "max_findings": 200}),
    _rule("LAN-005", "Kata baku di narasi fiksi (tanpa bentuk cakapan)", "language", "editorial", "word_list",
          severity="minor", order=51, scoring=_ded("language_terms", 1, 30), types=["fiksi"],
          description="Bentuk cakapan (tapi, nggak, udah) wajar dalam dialog dan tidak diperiksa untuk fiksi.",
          config={"dictionary": {k: v for k, v in NONSTANDARD_WORDS.items() if k not in CONVERSATIONAL},
                  "source": "Daftar kelola internal, mengacu KBBI", "max_findings": 200}),
    _rule("LAN-003", "Penulisan kata depan di/ke dipisah", "language", "editorial", "word_list",
          severity="minor", order=52, scoring=_ded("language_terms", 1, 30),
          config={"dictionary": JOINED_PREPOSITIONS, "source": "PUEBI/EYD: kata depan ditulis terpisah", "max_findings": 200}),
    _rule("LAN-004", "Istilah konsisten", "language", "editorial", "term_consistency",
          severity="minor", order=53, scoring=_ded("language_terms", 5, 20), config={"groups": TERM_GROUPS}),
    # --- Sitasi & referensi (buku ilmiah) --------------------------------------------
    _rule("REF-001", "Daftar pustaka tersedia", "citation", "editorial", "references_present",
          severity="major", order=60, types=SCIENTIFIC, scoring=_ded("citations_references", 40, 40)),
    _rule("REF-002", "Setiap sitasi ada di daftar pustaka", "citation", "editorial", "citation_without_reference",
          severity="major", order=61, types=SCIENTIFIC, human=True, scoring=_ded("citations_references", 5, 30)),
    _rule("REF-003", "Setiap entri pustaka disitir", "citation", "editorial", "reference_not_cited",
          severity="minor", order=62, types=SCIENTIFIC, human=True, scoring=_ded("citations_references", 2, 20)),
    _rule("REF-004", "Format daftar pustaka seragam (gaya yang didukung)", "citation", "editorial", "reference_format",
          severity="minor", order=63, types=SCIENTIFIC, scoring=_ded("citations_references", 2, 20)),
    # --- Elemen pembahasan -------------------------------------------------------------
    _rule("ELM-001", "Elemen pembahasan sesuai jenis buku", "content_elements", "editorial", "book_elements",
          severity="minor", order=70, types=SCIENTIFIC, scoring=_ded("discussion_elements", 8, 60),
          config={"by_type": {
              "buku_ajar": {"per_chapter": [
                  {"label": "Tujuan pembelajaran", "aliases": ["tujuan pembelajaran", "capaian pembelajaran", "kompetensi dasar", "tujuan"]},
                  {"label": "Rangkuman", "aliases": ["rangkuman", "ringkasan", "simpulan"]},
                  {"label": "Latihan/evaluasi", "aliases": ["latihan", "soal latihan", "evaluasi", "uji kompetensi", "tugas"]},
              ]},
              "buku_ilmiah": {"book": [INTRO, CLOSING]},
              "monograf": {"book": [INTRO, CLOSING]},
              "referensi": {"book": [GLOSSARY]},
          }}),
    # --- Tahap 2: tata letak fisik -------------------------------------------------------
    _rule("LAY-001", "Ukuran halaman seragam", "layout", "editorial", "layout_page_size",
          severity="major", order=90, scoring=_ded("layout_typography", 15, 30)),
    _rule("LAY-002", "Margin cukup dan konsisten", "layout", "editorial", "layout_margins",
          severity="major", order=91, scoring=_ded("layout_typography", 10, 30), config={"min_margin_cm": 1.5, "max_spread_cm": 0.6}),
    _rule("LAY-003", "Jenis huruf isi seragam", "layout", "editorial", "layout_body_font",
          severity="minor", order=92, scoring=_ded("layout_typography", 5, 15), config={"max_families": 2, "min_share": 0.02}),
    _rule("LAY-004", "Ukuran huruf isi wajar dan seragam", "layout", "editorial", "layout_body_size",
          severity="minor", order=93, scoring=_ded("layout_typography", 8, 24), config={"range_pt": [10, 14], "min_share": 0.05}),
    _rule("LAY-005", "Spasi baris isi seragam", "layout", "editorial", "layout_line_spacing",
          severity="minor", order=94, scoring=_ded("layout_typography", 5, 10)),
    _rule("LAY-006", "Perataan paragraf isi seragam", "layout", "editorial", "layout_alignment",
          severity="minor", order=95, scoring=_ded("layout_typography", 5, 10)),
    _rule("LAY-007", "Nomor halaman tersedia", "layout", "editorial", "layout_page_numbers",
          severity="major", order=96, scoring=_ded("layout_typography", 20, 20)),
    _rule("LAY-008", "Resolusi gambar layak cetak", "layout", "editorial", "layout_image_resolution",
          severity="major", order=97, scoring=_ded("layout_typography", 5, 25), config={"min_dpi": 150, "recommended_dpi": 300}),
    _rule("LAY-009", "Font tertanam di PDF", "layout", "editorial", "layout_fonts_embedded",
          severity="major", order=98, scoring=_ded("layout_typography", 10, 30)),
    _rule("LAY-010", "Tidak ada halaman kosong berlebih", "layout", "editorial", "layout_blank_pages",
          severity="minor", order=99, scoring=_ded("layout_typography", 3, 10)),
    _rule("LAY-011", "Format judul bab seragam", "layout", "editorial", "layout_heading_style",
          severity="minor", order=100, scoring=_ded("layout_typography", 3, 15)),
    # --- Metadata & elemen penerbitan (editorial) ------------------------------------
    _rule("MET-001", "Judul di halaman awal sesuai judul kerja", "metadata", "editorial", "title_page_title",
          severity="minor", order=80, human=True, scoring=_ded("metadata_publication", 15, 15)),
    _rule("MET-002", "Nama penulis tercantum di halaman awal", "metadata", "editorial", "authors_on_title_page",
          severity="minor", order=81, human=True, scoring=_ded("metadata_publication", 10, 30)),
]

CRITERIA = {
    "structure_completeness": ("Kelengkapan struktur", "Bagian wajib tersedia, isi tidak kosong, struktur dasar terbaca."),
    "chapter_consistency": ("Konsistensi bab dan heading", "Penomoran, tingkat heading, dan daftar isi konsisten."),
    "citations_references": ("Sitasi dan referensi", "Pasangan sitasi–daftar pustaka dan format gaya yang didukung."),
    "format_technical": ("Format dan kerapian teknis", "Spasi, tanda baca, placeholder, karakter anomali."),
    "language_terms": ("Bahasa dan konsistensi istilah", "Kata baku menurut daftar kelola, kata depan, konsistensi istilah."),
    "internal_repetition": ("Pengulangan internal", "Duplikasi paragraf/rangkaian paragraf di dalam naskah."),
    "discussion_elements": ("Kelengkapan elemen pembahasan", "Elemen yang didefinisikan khusus untuk jenis buku."),
    "metadata_publication": ("Metadata dan elemen penerbitan", "Kesesuaian judul dan penulis di naskah dengan metadata."),
    "layout_typography": ("Tata letak & tipografi", "Ukuran halaman, margin, huruf, spasi, perataan, nomor halaman, gambar, font PDF."),
}

# Bobot (%) per keluarga rubrik. Total harus 100.
RUBRIC_FAMILIES = {
    "Rubrik buku ilmiah/ajar": (SCIENTIFIC, {
        "layout_typography": 15, "structure_completeness": 10, "chapter_consistency": 10, "citations_references": 15,
        "format_technical": 10, "language_terms": 15, "internal_repetition": 10, "discussion_elements": 10, "metadata_publication": 5,
    }),
    "Rubrik fiksi": (["fiksi", "buku_anak"], {
        "layout_typography": 25, "structure_completeness": 15, "chapter_consistency": 15, "format_technical": 15, "language_terms": 20,
        "internal_repetition": 5, "metadata_publication": 5,
    }),
    "Rubrik umum": (["nonfiksi_umum", "biografi", "terjemahan", "kompilasi", "lainnya"], {
        "layout_typography": 25, "structure_completeness": 15, "chapter_consistency": 15, "format_technical": 10, "language_terms": 20,
        "internal_repetition": 5, "metadata_publication": 10,
    }),
}

THRESHOLDS = {
    "pass": 85,
    "minor_revision": 70,
    "major_revision": 55,
    "exclude_not_applicable": True,
    "note": "Ambang usulan awal; kalibrasi dengan korpus naskah representatif (Fase 5).",
}


def rule_snapshot(r: Rule) -> dict:
    return {
        "rule_id": str(r.id), "rule_code": r.rule_code, "title": r.title, "description": r.description, "category": r.category,
        "track": r.track, "authority_type": r.authority_type, "source_title": r.source_title, "source_url": r.source_url,
        "source_reference": r.source_reference, "verification_status": r.verification_status,
        "verified_at": r.verified_at.isoformat() if r.verified_at else None, "applies_to_types": r.applies_to_types,
        "engine_key": r.engine_key, "config_json": r.config_json, "severity": r.severity, "blocking": r.blocking,
        "requires_human_verification": r.requires_human_verification, "scoring_effect": r.scoring_effect,
        "execution_order": r.execution_order,
    }


def build_rule_set(db: Session, name: str, created_by=None, change_notes: str | None = None) -> RuleSet:
    last = db.scalar(select(RuleSet.version).where(RuleSet.name == name).order_by(RuleSet.version.desc()).limit(1)) or 0
    rs = RuleSet(name=name, version=last + 1, status="draft", created_by=created_by, change_notes=change_notes,
                 description="Snapshot seluruh aturan aktif saat versi dibuat.")
    for r in db.scalars(select(Rule).where(Rule.status == "active").order_by(Rule.execution_order, Rule.rule_code)):
        rs.items.append(RuleSetItem(rule_id=r.id, execution_order=r.execution_order, rule_snapshot_json=rule_snapshot(r)))
    db.add(rs)
    db.flush()
    return rs


def seed_catalog(db: Session) -> dict:
    """Idempoten: menambah aturan yang belum ada, lalu menerbitkan rule set & rubrik v1 bila belum ada."""
    now = datetime.now(UTC)
    existing = set(db.scalars(select(Rule.rule_code)))
    added = 0
    for spec in RULES:
        if spec["rule_code"] in existing:
            continue
        db.add(Rule(**spec, status="active"))
        added += 1
    db.flush()

    published = db.scalar(select(RuleSet).where(RuleSet.status == "published").limit(1))
    if published is None:
        rs = build_rule_set(db, "Rule set standar", change_notes=f"Katalog awal (PRD §10). {CATALOG_MARKER}")
        rs.status, rs.published_at = "published", now
        published = rs

    rubrics = 0
    for family, (types, weights) in RUBRIC_FAMILIES.items():
        for t in types:
            if db.scalar(select(RubricVersion.id).where(RubricVersion.manuscript_type == t, RubricVersion.status == "published").limit(1)):
                continue
            # Dibuat sebagai draft lalu dipublikasikan: trigger menolak kriteria baru di bawah rubrik yang sudah terbit.
            rv = RubricVersion(name=family, version=1, manuscript_type=t, status="draft",
                               min_scoring_coverage=80, score_thresholds_json=THRESHOLDS,
                               change_notes="Rubrik awal (PRD §11.1). Bobot usulan, belum dikalibrasi.")
            for i, (code, w) in enumerate(weights.items()):
                name, desc = CRITERIA[code]
                rv.criteria.append(RubricCriterion(criterion_code=code, name=name, description=desc, weight_percent=w,
                                                   scoring_method_key="deduction", sort_order=i))
            db.add(rv)
            db.flush()
            rv.status, rv.published_at = "published", now
            rubrics += 1
    db.flush()
    revision = apply_catalog_revision(db)
    return {"rules_added": added, "rule_set": f"{published.name} v{published.version}", "rubrics_added": rubrics, "revision": revision}


def apply_catalog_revision(db: Session) -> dict:
    """Sinkronkan aturan & rubrik di basis data dengan definisi katalog terkini (CATALOG_REVISION).

    Bila rule set dengan penanda revisi ini belum ada: perbarui seluruh aturan katalog, terbitkan rule set baru.
    Rubrik terbit yang bobotnya berbeda dengan katalog diganti versi baru. Idempoten; hasil lama tidak berubah.
    """
    now = datetime.now(UTC)
    result: dict = {"rules_updated": [], "rubrics_published": 0}
    marked = db.scalar(select(RuleSet.id).where(RuleSet.change_notes.contains(CATALOG_MARKER)).limit(1))
    if not marked:
        by_code = {r.rule_code: r for r in db.scalars(select(Rule))}
        for spec in RULES:
            r = by_code.get(spec["rule_code"])
            if r is None:
                continue
            for k, v in spec.items():
                setattr(r, k, v)
            if "verification_status" not in spec:
                r.verification_status, r.verification_note, r.verified_at = "unverified", None, None
            result["rules_updated"].append(r.rule_code)
        db.flush()
        rs = build_rule_set(db, "Rule set standar", change_notes=f"Revisi katalog r{CATALOG_REVISION}: klasifikasi jenis terbitan; "
                            f"aturan ISBN sesuai Perpusnas 11/2025 & Juknis Layanan ISBN 2023. {CATALOG_MARKER}")
        for old in db.scalars(select(RuleSet).where(RuleSet.status == "published")):
            old.status = "archived"
        rs.status, rs.published_at = "published", now
        result["rule_set"] = f"v{rs.version}"
    for family, (types, weights) in RUBRIC_FAMILIES.items():
        for t in types:
            cur = db.scalar(select(RubricVersion).where(RubricVersion.manuscript_type == t, RubricVersion.status == "published").limit(1))
            if cur is not None and {c.criterion_code: float(c.weight_percent) for c in cur.criteria} == {k: float(v) for k, v in weights.items()}:
                continue
            last = db.scalar(select(RubricVersion.version).where(RubricVersion.name == family, RubricVersion.manuscript_type == t)
                             .order_by(RubricVersion.version.desc()).limit(1)) or 0
            rv = RubricVersion(name=family, version=last + 1, manuscript_type=t, status="draft", min_scoring_coverage=80,
                               score_thresholds_json=THRESHOLDS, change_notes=f"Sinkron katalog r{CATALOG_REVISION}.")
            for i, (code, w) in enumerate(weights.items()):
                name, desc = CRITERIA[code]
                rv.criteria.append(RubricCriterion(criterion_code=code, name=name, description=desc, weight_percent=w,
                                                   scoring_method_key="deduction", sort_order=i))
            db.add(rv)
            db.flush()
            if cur is not None:
                cur.status = "archived"
            rv.status, rv.published_at = "published", now
            result["rubrics_published"] += 1
    db.flush()
    return result
