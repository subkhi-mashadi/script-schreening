# Sistem Screening Naskah Buku

Aplikasi internal PT Dimensi Antara Pustaka untuk menerima, membaca, memeriksa, dan menilai naskah buku
dengan **aturan deterministik tanpa AI/LLM**. Spesifikasi lengkap: [PRD_Sistem_Screening_Naskah_Buku.md](PRD_Sistem_Screening_Naskah_Buku.md).

## Status fase

| Fase | Cakupan | Status |
|---|---|---|
| 1 | Auth + RBAC, metadata naskah, unggah versi immutable, Document Reader, status ekstraksi, audit log | **Selesai** |
| 2 | Rule registry & rule set berversi, aturan kelengkapan & ISBN/administratif, findings + revision map | **Selesai** |
| 3 | Rubrik berversi, skor editorial otomatis, scorecard | **Selesai** |
| 4 | Verifikasi editor, keputusan final, perbandingan versi, laporan PDF/HTML/CSV | **Selesai** |
| 5 | Kalibrasi korpus, monitoring, backup, hardening | Belum |

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, python-docx + lxml, PyMuPDF.
- **Frontend:** React 19 + TypeScript (Vite), react-router.

## Menjalankan (pengembangan)

Prasyarat: PostgreSQL berjalan lokal, [`uv`](https://docs.astral.sh/uv/), Node 22.

```bash
# Database
createdb screening_naskah
createdb screening_naskah_test     # untuk test

# Backend
cd backend
uv sync
cp .env.example .env               # sesuaikan SN_DATABASE_URL / SN_SECRET_KEY
uv run alembic upgrade head
uv run python -m app.cli seed-catalog      # aturan, rule set v1, rubrik v1 (idempoten)
uv run python -m app.cli create-user --email admin@contoh.co.id --name "Admin" --role system_admin
uv run uvicorn app.main:app --reload --port 8000     # API docs: http://localhost:8000/api/docs

# Frontend (terminal lain)
cd frontend
npm install
npm run dev                        # http://localhost:5173 (proxy /api → :8000)
```

**Cek Naskah** (halaman awal pengguna yang bisa mengunggah): seret berkas → rekaman naskah + versi 1 dibuat otomatis (`POST /api/v1/quick-checks`) → hasil ekstraksi tampil di halaman yang sama. Metadata yang tidak diisi tetap ditandai belum lengkap.

Akun tunggal: peran `publisher_admin` (Pengelola penerbitan) memiliki semua akses — unggah, cek ISBN, cek layout, laporan, aturan. Demo: `pengelola@demo.dap.id`.

Peran lain (opsional): `system_admin`, `rule_admin`, `editor`, `manager`, `intake_operator`, `auditor`.

### Test

```bash
cd backend && uv run pytest        # memakai database screening_naskah_test (skema dibuat ulang tiap sesi)
cd frontend && npm run build && npx oxlint src
```

### Perintah operasional

```bash
uv run python -m app.cli extract-pending           # proses versi yang masih PENDING (mis. setelah restart)
uv run python -m app.cli extract-file naskah.docx  # uji Document Reader tanpa database, cetak ringkasan JSON
uv run python -m app.cli screen-pending            # proses screening yang masih QUEUED
uv run python -m app.cli screen-unscreened         # screening versi terbaru yang belum pernah diperiksa
```

## Keputusan desain Fase 1

**Akses (least privilege).** Izin dicek di backend per endpoint ([permissions.py](backend/app/core/permissions.py)).
Operator melihat naskah yang ia buat; editor melihat naskah yang ditugaskan; manajer & auditor melihat semua;
admin sistem mengelola akun & audit tanpa akses isi naskah; admin aturan belum punya akses naskah (Fase 2).
Naskah di luar cakupan dijawab 404 dan dicatat sebagai `access.denied`.

**Sesi.** Login menghasilkan JWT yang membawa ID sesi (`user_sessions`). Logout, nonaktif akun, ganti peran,
atau ganti kata sandi mencabut sesi. Login gagal dibatasi (5× / 15 menit) berdasarkan audit log.

**Berkas immutable.** Berkas disimpan di direktori privat `backend/storage/` dengan `O_EXCL` + mode read-only;
SHA-256 dicatat dan diverifikasi ulang saat ekstraksi & unduh. Trigger PostgreSQL menolak perubahan kolom
identitas berkas dan penghapusan baris `document_versions`. Unggah ulang selalu membuat versi baru
(berkas identik diberi peringatan `DUPLICATE_OF_VERSION_n`). Header `Idempotency-Key` mencegah versi ganda saat kirim ulang.

**Validasi unggahan** berdasarkan isi (magic bytes), bukan ekstensi: DOCX diperiksa struktur ZIP, rasio kompresi,
path berbahaya, enkripsi, dan makro (`vbaProject.bin`). Batas ukuran dapat dikonfigurasi (`SN_MAX_UPLOAD_MB`).

**Document Reader → model ternormalisasi** ([backend/app/reader/](backend/app/reader/)). Semua format menghasilkan blok
`heading | paragraph | list_item | table | quote | footnote | caption` dengan `block_id`, `section_path`
(`BAB I PENDAHULUAN > 1.1 Latar Belakang`), induk heading, dan offset karakter terhadap teks gabungan.
- DOCX: style Heading/Judul/outline level; fallback pola teks (BAB, `1.2`, bagian awal/akhir) hanya bila paragraf tebal.
  Tracked changes: sisipan dibaca, hapusan dibuang (dengan peringatan). Catatan kaki ditempatkan setelah paragraf pemanggil.
  **Nomor halaman DOCX tidak tersedia** — hanya `page_estimate` dari tata letak terakhir Word, ditandai tidak stabil.
- PDF: outline/bookmark → pola + ciri visual → ukuran font. Header/footer berulang dan nomor halaman margin dibuang dari isi.
  Halaman pindaian terdeteksi; OCR belum ada (P1) sehingga status `INCOMPLETE`.
- "BAB I" + judul di baris berikutnya digabung menjadi satu heading.

**Kualitas ekstraksi** ([quality.py](backend/app/reader/quality.py)) 0–100 mengukur keterbacaan teks, *bukan* mutu naskah.
`INCOMPLETE` bila teks < 500 karakter, halaman pindaian > 20%, atau skor < 60 (semua dapat dikonfigurasi).
Berkas rusak/terenkripsi → `FAILED` dengan error terstruktur (`kind: document|system|integrity`) dan dapat diproses ulang.

**Audit log append-only** (trigger menolak UPDATE/DELETE/TRUNCATE). Isi naskah tidak pernah dicatat. Pencarian audit juga diaudit.

## Keputusan desain Fase 2–3

**Alur.** Setiap unggahan → pembacaan → screening otomatis dengan rule set & rubrik yang sedang terbit
([runner.py](backend/app/screening/runner.py)). Screening ulang membuat run baru; hasil lama tidak berubah.

**Aturan** ([handlers.py](backend/app/screening/handlers.py), katalog di [catalog.py](backend/app/screening/catalog.py)) — 29 aturan deterministik:
- *ISBN/administrasi* (gerbang terpisah): halaman judul, halaman balik judul/hak cipta, kata pengantar, daftar isi, metadata permohonan,
  surat pernyataan & izin terjemahan & distribusi publik (bukti manual), minimum halaman.
- *Editorial*: placeholder, bagian wajib per jenis naskah, urutan & gaya penomoran bab, lompatan heading, kecocokan daftar isi
  (termasuk entri terpecah & halaman), bab sangat pendek (indikator), duplikasi (hash, rangkaian paragraf, Jaccard 3-gram),
  tipografi, kata tidak baku & kata depan di/ke (daftar kelola), konsistensi istilah, sitasi ↔ daftar pustaka & format (buku ilmiah),
  elemen pembahasan (buku ajar/ilmiah), judul & penulis di halaman awal.

**Verifikasi aturan resmi.** Aturan berlabel resmi/kebijakan berstatus *belum diverifikasi*. Selama itu, hasilnya *perlu verifikasi*
(pengamatan "ditemukan/tidak ditemukan" tetap ditampilkan). Admin aturan mengisi rujukan pasal, menandai *terverifikasi*,
lalu menerbitkan rule set baru — baru setelah itu status ISBN bisa *Memenuhi/Tidak memenuhi*.

**Skor** ([scoring.py](backend/app/screening/scoring.py)): s_i = 100 − Σ min(n × potongan, batas); S = Σ w·s / Σ w atas kriteria yang dapat dinilai.
Kriteria tidak berlaku dikeluarkan (bukan nilai penuh); cakupan < 80% → skor tidak diterbitkan; temuan kritis/mayor terbuka membatasi rekomendasi;
FALSE_POSITIVE (Fase 4) dan INFO tidak dihitung. Tidak ada endpoint untuk mengubah skor.

**Versi.** Rule set menyimpan snapshot konfigurasi tiap aturan; rule set & rubrik terbit tidak dapat diubah (trigger database).
Penerbitan rule set wajib didahului simulasi pada berkas contoh tanpa aturan gagal; rubrik wajib berbobot total 100%.

## Alur dua tahap (mode otomatis, `SN_AUTO_MODE=true`)

1. **Kelayakan ISBN — otomatis saat unggah** (`scope=isbn`). Penentu kelayakan = syarat naskah dalam
   **Peraturan Perpusnas No. 11 Tahun 2025 Pasal 10 ayat (3)**: halaman judul, halaman balik judul, kata pengantar,
   daftar isi (huruf b) dan naskah akhir tanpa teks sementara (huruf c). Hasil: *Layak ISBN* / *Belum layak ISBN*.
   Sebelum aturan dijalankan, sistem menentukan **kategori terbitan** sesuai ruas formulir ISBN (Juknis Layanan ISBN
   Perpusnas 2023, bagian 5): jenis terbitan (buku anak, karya sastra, buku ajar, ilmiah, referensi, bunga rampai,
   prosiding, nonfiksi umum), jenis pustaka (fiksi/non fiksi), kelompok pembaca (anak/dewasa/semua umur), lepas/berjilid,
   terjemahan, penelitian/non penelitian, kategori penerbit, media ([classify.py](backend/app/screening/classify.py)).
   Bila jenis naskah belum dipilih manual, jenis hasil deteksi dipakai otomatis. Aturan per kategori mengikuti Juknis:
   fiksi boleh tanpa kata pengantar/daftar isi (4.3.3); minimal 49 halaman buku umum/ilmiah, 8 halaman buku anak
   (draf DOCX A4/Letter dinilai ulang setelah ditata); izin terjemahan hanya bila terdeteksi terjemahan.
   Dokumen di luar naskah (surat permohonan, pernyataan keaslian bermeterai, izin terjemahan, surat pengalihan,
   naskah PDF ber-watermark) ditampilkan sebagai daftar persiapan dan tidak menentukan kelayakan naskah. Peringatan
   (jenis terbitan untuk umum — Pasal 2; kelengkapan data; minimum halaman kebijakan penerbit) juga tidak menentukan.
2. **Cek layout — atas permintaan** (`POST /versions/{id}/layout-check`, `scope=layout`). Tata letak fisik dibaca
   langsung dari berkas ([layout.py](backend/app/reader/layout.py)): ukuran halaman seragam, margin ≥ 1,5 cm dan konsisten,
   huruf & ukuran huruf isi, spasi baris, perataan, nomor halaman, resolusi gambar, font tertanam & halaman kosong (PDF),
   format judul bab — ditambah aturan kerapian teks (struktur, daftar isi, tipografi, duplikasi, kata baku). Skor memakai
   rubrik versi 2 dengan kriteria *Tata letak & tipografi*.

Dalam mode otomatis, verifikasi editor & keputusan manajer (Fase 4) disembunyikan di UI; kode & API tetap ada.

## Keputusan desain Fase 4

**Verifikasi editor** ([review.py](backend/app/screening/review.py)). Editor menandai temuan *benar / salah deteksi
(wajib alasan) / perlu cek lanjutan*, satu per satu atau massal. Editor tidak pernah mengisi skor: setiap tindakan memicu
rekalkulasi dengan rule set & rubrik yang sama, dari hasil mesin tersimpan (`rule_outcomes`). Nilai sebelum/sesudah dicatat
di `review_actions` (tidak bisa diubah) dan audit log. Temuan *salah deteksi* dan *info* tidak memotong skor.

**Bukti manual ISBN.** Item yang butuh dokumen di luar naskah (surat pernyataan, izin terjemahan, distribusi) dicatat editor/manajer
dengan keterangan dokumennya. Status tetap *perlu verifikasi* selama aturan resminya belum diverifikasi.

**Keputusan akhir** (manajer). Sistem memberi rekomendasi dan daftar penghalang. *Diteruskan* ditolak bila: screening tidak lengkap,
syarat wajib ISBN gagal, skor tidak terbit, ada temuan kritis terbuka, temuan kritis/mayor belum diverifikasi, atau masih ada
*cek lanjutan*. *Revisi/Ditolak* wajib beralasan. Keputusan hanya pada screening terbaru; status penerimaan naskah ikut diperbarui.
Setelah *Diteruskan/Ditolak*, verifikasi dikunci sampai keputusan diubah.

**Perbandingan versi** ([compare.py](backend/app/screening/compare.py)). Temuan dicocokkan dengan sidik jari isi (aturan + judul + kutipan,
tanpa nomor halaman/blok). Versi baru menampilkan temuan *sudah diperbaiki / baru / masih ada* dan perubahan skor; temuan terbuka
versi lama yang hilang otomatis ditandai *selesai di versi baru*.

**Laporan** ([report.py](backend/app/services/report.py)): PDF (PyMuPDF Story, nomor halaman di footer), HTML siap cetak, dan CSV
temuan/skor (BOM UTF-8, proteksi formula injection). Isi sesuai FR-11, termasuk disclaimer. Setiap unduhan tercatat di audit.

**Ringkasan audit**: volume harian 30 hari, pelaku teraktif, jenis peristiwa, akses ditolak, verifikasi & keputusan.

## Catatan produksi (belum dikerjakan, Fase 5)

- Role database aplikasi **tidak boleh** menjadi pemilik tabel (pemilik dapat menonaktifkan trigger). Buat role terpisah dengan hak DML saja.
- Ganti `SN_SECRET_KEY`; jalankan di balik HTTPS; arahkan `SN_STORAGE_DIR` ke storage privat terenkripsi.
- Ekstraksi & screening berjalan sebagai background task di proses API dengan klaim atomik di database (QUEUED/PENDING → PROCESSING).
  Untuk produksi, jalankan `extract-pending`/`screen-pending` dari worker terpisah (Supervisor/systemd) agar tidak bergantung pada proses API.
- Ambang skor, bobot, minimum halaman, dan daftar kata adalah usulan awal — kalibrasi dengan korpus naskah nyata (Fase 5).
- Pemindaian malware unggahan belum ada.
