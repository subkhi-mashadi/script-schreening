export const ROLE_LABELS: Record<string, string> = {
  publisher_admin: 'Pengelola penerbitan',
  system_admin: 'Admin sistem',
  rule_admin: 'Admin aturan/editorial',
  editor: 'Editor/verifikator',
  manager: 'Manajer/editor-in-chief',
  intake_operator: 'Operator penerimaan',
  auditor: 'Auditor',
}

export const EXTRACTION_LABELS: Record<string, string> = {
  PENDING: 'Menunggu dibaca',
  PROCESSING: 'Sedang dibaca',
  EXTRACTED: 'Terbaca utuh',
  INCOMPLETE: 'Terbaca sebagian',
  FAILED: 'Gagal dibaca',
}

export const INTAKE_LABELS: Record<string, string> = {
  RECEIVED: 'Diterima',
  IN_REVIEW: 'Dalam pemeriksaan',
  REVISION_REQUESTED: 'Revisi diminta',
  ACCEPTED: 'Diteruskan',
  REJECTED: 'Ditolak',
  CLOSED: 'Ditutup',
}

export const FIELD_LABELS: Record<string, string> = {
  working_title: 'Judul kerja',
  manuscript_type: 'Jenis naskah',
  language_code: 'Bahasa',
  authors: 'Penulis',
  submitted_at: 'Tanggal masuk',
}

export const BLOCK_LABELS: Record<string, string> = {
  heading: 'Heading',
  paragraph: 'Paragraf',
  list_item: 'Butir daftar',
  table: 'Tabel',
  quote: 'Kutipan',
  footnote: 'Catatan kaki',
  caption: 'Keterangan',
}

export const QUALITY_REASON_LABELS: Record<string, string> = {
  LOW_TEXT: 'Teks terekstrak terlalu sedikit',
  SCANNED_PAGES: 'Terlalu banyak halaman hasil pindai',
  LOW_QUALITY_SCORE: 'Skor kualitas ekstraksi di bawah ambang',
}

export const EVENT_LABELS: Record<string, string> = {
  'auth.login': 'Login',
  'auth.logout': 'Logout',
  'auth.login_failed': 'Login gagal',
  'auth.login_throttled': 'Login dibatasi',
  'access.denied': 'Akses ditolak',
  'user.created': 'Pengguna dibuat',
  'user.updated': 'Pengguna diubah',
  'manuscript.created': 'Naskah dibuat',
  'manuscript.updated': 'Metadata naskah diubah',
  'version.uploaded': 'Versi diunggah',
  'version.upload_rejected': 'Unggahan ditolak',
  'version.downloaded': 'Berkas diunduh',
  'version.integrity_failed': 'Integritas berkas gagal',
  'extraction.completed': 'Pembacaan selesai',
  'extraction.failed': 'Gagal dibaca',
  'extraction.requeued': 'Pembacaan diulang',
  'audit.searched': 'Audit dicari',
  'screening.queued': 'Screening dijadwalkan',
  'screening.completed': 'Screening selesai',
  'screening.failed': 'Screening gagal',
  'rule.updated': 'Aturan diubah',
  'rule.verification_changed': 'Verifikasi aturan diubah',
  'rule_set.created': 'Draft rule set dibuat',
  'rule_set.simulated': 'Rule set disimulasikan',
  'rule_set.published': 'Rule set diterbitkan',
  'rule_set.deleted': 'Draft rule set dihapus',
  'rubric.created': 'Draft rubrik dibuat',
  'rubric.updated': 'Rubrik diubah',
  'rubric.published': 'Rubrik diterbitkan',
  'rubric.deleted': 'Draft rubrik dihapus',
  'finding.reviewed': 'Temuan diverifikasi',
  'compliance.evidence_recorded': 'Bukti manual dicatat',
  'screening.recalculated': 'Skor dihitung ulang',
  'screening.decided': 'Keputusan ditetapkan',
  'report.exported': 'Laporan diunduh',
}

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('id-ID', withTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' })
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

const RTF = new Intl.RelativeTimeFormat('id-ID', { numeric: 'auto' })

/** "5 menit lalu", "kemarin"; di atas 7 hari memakai tanggal. */
export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 60) return 'baru saja'
  if (abs < 3600) return RTF.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return RTF.format(Math.round(diff / 3600), 'hour')
  if (abs < 7 * 86400) return RTF.format(Math.round(diff / 86400), 'day')
  return fmtDate(iso, false)
}

/** Inisial untuk avatar: "Natalia Br Barus" → "NB". */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

export const ISBN_LABELS: Record<string, string> = {
  PASS: 'Layak ISBN',
  FAIL: 'Belum layak ISBN',
  NEEDS_VERIFICATION: 'Perlu verifikasi',
  NOT_APPLICABLE: 'Tidak berlaku',
  INCOMPLETE: 'Belum lengkap',
}

export const EDITORIAL_LABELS: Record<string, string> = {
  PASS_RECOMMENDED: 'Direkomendasikan lanjut',
  MINOR_REVISION: 'Revisi ringan',
  MAJOR_REVISION: 'Revisi besar',
  SUBSTANTIAL_REWORK: 'Perlu pengerjaan ulang',
  NEEDS_VERIFICATION: 'Perlu verifikasi',
  NOT_SCORABLE: 'Tidak dapat dinilai',
}

export const RUN_STATUS_LABELS: Record<string, string> = {
  QUEUED: 'Dalam antrean',
  PROCESSING: 'Sedang diperiksa',
  COMPLETED: 'Selesai',
  INCOMPLETE: 'Tidak lengkap',
  FAILED: 'Gagal',
  CANCELLED: 'Dibatalkan',
}

export const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Kritis',
  major: 'Mayor',
  minor: 'Minor',
  info: 'Info',
}

export const COMPLIANCE_LABELS: Record<string, string> = {
  pass: 'Memenuhi',
  fail: 'Tidak memenuhi',
  needs_verification: 'Perlu verifikasi',
  not_applicable: 'Tidak berlaku',
  incomplete: 'Belum lengkap',
}

export const OBSERVED_LABELS: Record<string, string> = {
  pass: 'Ditemukan',
  fail: 'Tidak ditemukan',
  unknown: 'Perlu bukti manual',
  not_applicable: '—',
  error: 'Gagal diperiksa',
}

export const AUTHORITY_LABELS: Record<string, string> = {
  official_regulation: 'Regulasi resmi',
  official_procedure: 'Prosedur resmi',
  publisher_policy: 'Kebijakan penerbit',
  editorial_indicator: 'Indikator editorial',
}

export const CATEGORY_LABELS: Record<string, string> = {
  isbn_admin: 'ISBN & administrasi',
  layout: 'Tata letak',
  technical: 'Teknis',
  structure: 'Struktur',
  repetition: 'Pengulangan',
  language: 'Bahasa',
  citation: 'Sitasi & referensi',
  content_elements: 'Elemen pembahasan',
  metadata: 'Metadata',
}

export const TRACK_LABELS: Record<string, string> = { editorial: 'Editorial', compliance: 'ISBN & administrasi' }

export const VERIFICATION_LABELS: Record<string, string> = { verified: 'Terverifikasi', unverified: 'Belum diverifikasi', rejected: 'Ditolak' }

export const VERIFY_LABELS: Record<string, string> = {
  UNREVIEWED: 'Belum diverifikasi',
  CONFIRMED: 'Benar',
  FALSE_POSITIVE: 'Salah deteksi',
  NEEDS_FURTHER_CHECK: 'Perlu cek lanjutan',
  RESOLVED_IN_NEW_VERSION: 'Selesai di versi baru',
}

export const DECISION_LABELS: Record<string, string> = {
  ACCEPTED_FOR_NEXT_STAGE: 'Diteruskan ke tahap berikutnya',
  REVISION_REQUIRED: 'Revisi diperlukan',
  REJECTED: 'Ditolak',
  PENDING_VERIFICATION: 'Menunggu verifikasi',
  SCREENING_INCOMPLETE: 'Screening tidak lengkap',
}

export const REVIEW_ACTION_LABELS: Record<string, string> = {
  confirm: 'menandai temuan benar',
  false_positive: 'menandai salah deteksi',
  needs_check: 'meminta cek lanjutan',
  reset: 'membatalkan tanda',
  resolved_in_new_version: 'menandai selesai di versi baru',
  manual_evidence: 'mencatat bukti manual',
  decision: 'menetapkan keputusan',
  recalculation: 'menghitung ulang skor',
  note: 'menambahkan catatan',
}
