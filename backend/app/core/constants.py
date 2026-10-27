"""Nilai referensi yang dapat dikonfigurasi. Fase berikutnya memindahkan ini ke tabel konfigurasi."""

MANUSCRIPT_TYPES: dict[str, str] = {
    "buku_anak": "Buku anak",
    "buku_ilmiah": "Buku ilmiah",
    "buku_ajar": "Buku ajar",
    "referensi": "Buku referensi",
    "monograf": "Monograf",
    "nonfiksi_umum": "Buku umum/nonfiksi",
    "biografi": "Biografi/memoar",
    "fiksi": "Fiksi",
    "terjemahan": "Terjemahan",
    "kompilasi": "Kompilasi/bunga rampai",
    "prosiding": "Prosiding",
    "lainnya": "Lainnya",
}

LANGUAGES: dict[str, str] = {"id": "Bahasa Indonesia", "en": "English", "ar": "Arabic", "jv": "Basa Jawa", "su": "Basa Sunda"}

INTAKE_STATUSES = ("RECEIVED", "IN_REVIEW", "REVISION_REQUESTED", "ACCEPTED", "REJECTED", "CLOSED")

# Metadata penerimaan wajib (FR-02). Yang kosong ditandai, tidak diisi asumsi.
REQUIRED_INTAKE_FIELDS = ("working_title", "manuscript_type", "language_code", "authors", "submitted_at")

EXTRACTION_STATUS_LABELS = {
    "PENDING": "Menunggu dibaca",
    "PROCESSING": "Sedang dibaca",
    "EXTRACTED": "Terbaca utuh",
    "INCOMPLETE": "Terbaca sebagian",
    "FAILED": "Gagal dibaca",
}

# Batas penggunaan hasil sistem; ditampilkan di UI dan laporan (FR-11).
DISCLAIMER = (
    "Hasil sistem bukan jaminan penerimaan ISBN. Aturan resmi yang belum diverifikasi pemilik proses "
    "menghasilkan status 'perlu verifikasi'. Skor editorial hanya mengukur indikator yang dapat diperiksa "
    "secara otomatis, bukan mutu isi, kebaruan, atau kedalaman argumen."
)

# Rencana peredaran buku (Pasal 2 ayat (2) Perpusnas 11/2025; Juknis Layanan ISBN 4.5).
DISTRIBUTION_OPTIONS = {
    "dijual_umum": "Dijual untuk masyarakat umum (toko, marketplace, website)",
    "gratis_umum": "Gratis, dapat diakses masyarakat umum",
    "terbatas": "Cetak terbatas / untuk kalangan tertentu",
}
