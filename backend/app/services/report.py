"""Laporan hasil screening (FR-11): HTML siap cetak, PDF, dan CSV.

PDF dibuat dari HTML yang sama dengan PyMuPDF `Story` (tanpa dependensi tambahan). Isi naskah
tidak disertakan selain kutipan bukti singkat pada temuan.
"""

import csv
import html
import io
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import DISCLAIMER, MANUSCRIPT_TYPES
from app.models import ComplianceCheck, DocumentVersion, Finding, Manuscript, ReviewAction, ScoreResult, ScreeningRun, User

ISBN = {"PASS": "Memenuhi", "FAIL": "Tidak memenuhi", "NEEDS_VERIFICATION": "Perlu verifikasi", "NOT_APPLICABLE": "Tidak berlaku",
        "INCOMPLETE": "Belum lengkap"}
EDITORIAL = {"PASS_RECOMMENDED": "Direkomendasikan lanjut", "MINOR_REVISION": "Revisi ringan", "MAJOR_REVISION": "Revisi besar",
             "SUBSTANTIAL_REWORK": "Perlu pengerjaan ulang", "NEEDS_VERIFICATION": "Perlu verifikasi", "NOT_SCORABLE": "Tidak dapat dinilai"}
DECISION = {"ACCEPTED_FOR_NEXT_STAGE": "Diteruskan ke tahap berikutnya", "REVISION_REQUIRED": "Revisi diperlukan", "REJECTED": "Ditolak",
            "PENDING_VERIFICATION": "Menunggu verifikasi", "SCREENING_INCOMPLETE": "Screening tidak lengkap"}
COMPLIANCE = {"pass": "Memenuhi", "fail": "Tidak memenuhi", "needs_verification": "Perlu verifikasi", "not_applicable": "Tidak berlaku",
              "incomplete": "Belum lengkap"}
OBSERVED = {"pass": "Ditemukan", "fail": "Tidak ditemukan", "unknown": "Perlu bukti manual", "not_applicable": "-", "error": "Gagal diperiksa"}
SEVERITY = {"critical": "Kritis", "major": "Mayor", "minor": "Minor", "info": "Info"}
VERIFICATION = {"UNREVIEWED": "Belum diverifikasi", "CONFIRMED": "Benar", "FALSE_POSITIVE": "Salah deteksi",
                "NEEDS_FURTHER_CHECK": "Perlu cek lanjutan", "RESOLVED_IN_NEW_VERSION": "Selesai di versi baru"}
ACTIONS = {"confirm": "Menandai benar", "false_positive": "Menandai salah deteksi", "needs_check": "Meminta cek lanjutan", "reset": "Membatalkan tanda",
           "resolved_in_new_version": "Selesai di versi baru", "manual_evidence": "Mencatat bukti manual", "decision": "Keputusan akhir",
           "recalculation": "Rekalkulasi", "note": "Catatan"}
AUTHORITY = {"official_regulation": "Regulasi resmi", "official_procedure": "Prosedur resmi", "publisher_policy": "Kebijakan penerbit",
             "editorial_indicator": "Indikator editorial"}


class ReportData:
    def __init__(self, db: Session, run: ScreeningRun) -> None:
        self.run = run
        self.version = db.get(DocumentVersion, run.document_version_id)
        self.manuscript = db.get(Manuscript, run.manuscript_id)
        self.findings = list(db.scalars(select(Finding).where(Finding.screening_run_id == run.id).order_by(Finding.sort_key, Finding.rule_code)))
        self.compliance = list(db.scalars(select(ComplianceCheck).where(ComplianceCheck.screening_run_id == run.id).order_by(ComplianceCheck.sort_order)))
        self.scores = list(db.scalars(select(ScoreResult).where(ScoreResult.screening_run_id == run.id).order_by(ScoreResult.sort_order)))
        self.actions = list(db.scalars(select(ReviewAction).where(ReviewAction.screening_run_id == run.id).order_by(ReviewAction.created_at)))
        ids = {a.actor_user_id for a in self.actions} | {run.decided_by, run.initiated_by, self.manuscript.assigned_editor_id}
        self.names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_([i for i in ids if i])))}
        self.generated_at = datetime.now(UTC)


def _tz(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(ZoneInfo(get_settings().display_timezone)).strftime("%d-%m-%Y %H:%M WIB")


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _location(f: Finding) -> str:
    parts = []
    if f.section_path:
        parts.append(f.section_path)
    if f.page_number:
        parts.append(f"hal. {f.page_number}")
    elif f.page_estimate:
        parts.append(f"perkiraan hal. {f.page_estimate}")
    if f.paragraph_id:
        parts.append(f"blok {f.paragraph_id}")
    return " | ".join(parts) or "Seluruh naskah"


CSS = """
body { font-family: sans-serif; font-size: 9.5pt; color: #161614; line-height: 1.4; }
h1 { font-size: 16pt; margin: 0 0 2pt 0; }
h2 { font-size: 11.5pt; margin: 14pt 0 5pt 0; border-bottom: 1px solid #cfcec7; padding-bottom: 2pt; }
.org { font-size: 8.5pt; color: #52514e; }
.muted { color: #7d7c76; }
.small { font-size: 8.5pt; }
table { width: 100%; border-collapse: collapse; margin-top: 4pt; }
th { text-align: left; font-size: 8pt; background-color: #f3f3f0; padding: 3pt 4pt; border-bottom: 1px solid #cfcec7; }
td { padding: 3pt 4pt; border-bottom: 1px solid #e4e3dd; vertical-align: top; }
.kv td:first-child { width: 32%; color: #52514e; }
.box { border: 1px solid #e4e3dd; background-color: #f6f6f3; padding: 6pt; margin-top: 6pt; }
.excerpt { font-style: italic; color: #52514e; }
.kvrow { border-bottom: 1px solid #e4e3dd; padding: 3pt 0; }
.finding { border-bottom: 1px solid #e4e3dd; padding: 4pt 0 5pt 0; }
"""


def render_html(d: ReportData, for_pdf: bool = False) -> str:
    r, m, v = d.run, d.manuscript, d.version
    summary = r.result_summary_json or {}
    sc = summary.get("score") or {}
    by_sev = summary.get("by_severity") or {}
    verification: dict[str, int] = {}
    for f in d.findings:
        verification[f.verification_status] = verification.get(f.verification_status, 0) + 1
    total_row = next((s for s in d.scores if s.result_type == "total"), None)

    out: list[str] = []
    w = out.append
    if not for_pdf:
        w("<!doctype html><html lang='id'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>")
        w(f"<title>Laporan screening {_e(m.internal_code)}</title><style>{CSS} body{{max-width:900px;margin:24px auto;padding:0 16px}}"
          "@media print{body{margin:0}} .noprint{margin-bottom:12px} @media print{.noprint{display:none}}</style></head><body>")
        w("<div class='noprint'><button onclick='window.print()'>Cetak / simpan PDF</button></div>")
    w("<div class='org'>PT Dimensi Antara Pustaka &middot; Sistem Screening Naskah</div>")
    w(f"<h1>Laporan Screening Naskah</h1><div class='muted small'>Dibuat {_tz(d.generated_at)} &middot; ID screening {_e(r.id)}</div>")
    w(f"<div class='box small'>{_e(DISCLAIMER)}</div>")

    w("<h2>Identitas naskah dan versi</h2><table class='kv'>")
    rows = [
        ("Kode naskah", m.internal_code), ("Judul kerja", m.working_title),
        ("Jenis naskah", MANUSCRIPT_TYPES.get(m.manuscript_type, m.manuscript_type)),
        ("Penulis", ", ".join(a.author_name for a in m.authors) or "Belum diisi"),
        ("Editor ditugaskan", d.names.get(m.assigned_editor_id, "-")),
        ("Versi berkas", f"v{v.version_number} - {v.original_filename}"), ("SHA-256", v.sha256_checksum),
        ("Status pembacaan", f"{v.extraction_status} (kualitas {v.extraction_quality or '-'}/100)"),
        ("Screening", f"ke-{r.run_number} untuk versi ini, selesai {_tz(r.completed_at)}"),
        ("Rule set", f"{r.rule_set.name} v{r.rule_set.version}"),
        ("Rubrik", f"{r.rubric.name} v{r.rubric.version}" if r.rubric else "-"),
        ("Mesin", r.engine_version), ("Status teknis", r.status),
    ]
    for k, val in rows:
        w(f"<tr><td>{_e(k)}</td><td>{_e(val)}</td></tr>")
    w("</table>")

    score_txt = f"{float(r.total_score):.2f} / 100" if r.total_score is not None else "Tidak diterbitkan"
    kv: list[tuple[str, str, bool]] = [
        ("Kepatuhan ISBN/administrasi", ISBN.get(r.isbn_status, r.isbn_status or "-"), True),
        ("Skor editorial", score_txt, True),
        ("Rekomendasi editorial", EDITORIAL.get(r.editorial_status, r.editorial_status or "-"), True),
    ]
    if sc:
        kv.append(("Cakupan penilaian", f"{sc.get('scored')} dari {sc.get('applicable')} kriteria (bobot {sc.get('coverage')}%)", False))
    kv.append(("Temuan", f"{len(d.findings)} total - " + ", ".join(f"{SEVERITY[k]} {by_sev.get(k, 0)}" for k in SEVERITY), False))
    kv.append(("Status verifikasi editor", ", ".join(f"{VERIFICATION.get(k, k)} {n}" for k, n in sorted(verification.items())) or "-", False))
    if r.final_decision:
        kv.append(("Keputusan akhir", DECISION.get(r.final_decision, r.final_decision), True))
        kv.append(("Penanggung jawab", f"{d.names.get(r.decided_by, '-')}, {_tz(r.decided_at)}", False))
        if r.decision_note:
            kv.append(("Catatan keputusan", r.decision_note, False))
    else:
        kv.append(("Keputusan akhir", "Belum ditetapkan", False))
    w("<h2>Ringkasan hasil</h2>")
    if for_pdf:
        # Tabel dua kolom dengan label panjang tidak ditata stabil oleh PDF Story; pakai baris blok.
        for k, val, strong in kv:
            w(f"<div class='kvrow'><span class='muted'>{_e(k)}:</span> {'<b>' if strong else ''}{_e(val)}{'</b>' if strong else ''}</div>")
    else:
        w("<table class='kv'>")
        for k, val, strong in kv:
            w(f"<tr><td>{_e(k)}</td><td>{'<b>' if strong else ''}{_e(val)}{'</b>' if strong else ''}</td></tr>")
        w("</table>")

    w("<h2>Kepatuhan ISBN dan administrasi</h2><table><tr><th>Persyaratan</th><th>Pengamatan</th><th>Status</th><th>Dasar aturan</th></tr>")
    for c in d.compliance:
        observed = OBSERVED.get(c.manual_observed or c.observed, c.observed)
        if c.manual_observed:
            observed += f" (bukti manual: {c.manual_note})"
        w(f"<tr><td><b>{_e(c.rule_code)}</b> {_e(c.title)}<div class='small muted'>{_e(c.explanation)}</div></td>"
          f"<td>{_e(observed)}</td><td>{_e(COMPLIANCE.get(c.result_status, c.result_status))}{' (wajib)' if c.blocking else ''}</td>"
          f"<td class='small'>{_e(AUTHORITY.get(c.authority_type, c.authority_type))}; "
          f"{'terverifikasi' if c.rule_verification_status == 'verified' else 'belum diverifikasi'}</td></tr>")
    w("</table>")

    w("<h2>Skor editorial per kriteria</h2>")
    w("<div class='small muted'>Skor kriteria = 100 dikurangi potongan temuan (dengan batas per aturan). Skor total = jumlah (bobot x skor) dibagi jumlah bobot kriteria yang dinilai.</div>")
    w("<table><tr><th>Kriteria</th><th>Bobot</th><th>Skor</th><th>Kontribusi</th><th>Keterangan</th></tr>")
    for s in d.scores:
        if s.result_type != "criterion":
            continue
        score_cell = f"{float(s.raw_score):.2f}" if s.raw_score is not None else ("Tidak berlaku" if s.scoring_status == "not_applicable" else "Tidak dinilai")
        contrib = f"{float(s.weighted_contribution):.2f}" if s.weighted_contribution is not None else "-"
        w(f"<tr><td>{_e(s.criterion_name_snapshot)}</td><td>{float(s.weight_percent):g}%</td><td>{_e(score_cell)}</td><td>{contrib}</td>"
          f"<td class='small'>{_e(s.explanation)}</td></tr>")
    if total_row:
        w(f"<tr><td><b>Skor total</b></td><td>100%</td><td><b>{_e(score_txt)}</b></td><td></td><td class='small'>{_e(total_row.explanation)}</td></tr>")
    w("</table>")

    w(f"<h2>Daftar temuan dan peta revisi ({len(d.findings)})</h2>")
    if not d.findings:
        w("<p>Tidak ada temuan dari aturan otomatis.</p>")
    else:
        # Blok per temuan (bukan baris tabel) agar pemotongan halaman PDF rapi.
        for i, f in enumerate(d.findings, 1):
            status = VERIFICATION.get(f.verification_status, "")
            if f.requires_human_verification and f.verification_status == "UNREVIEWED":
                status += " - perlu diperiksa editor"
            w(f"<div class='finding'><b>{i}. [{_e(SEVERITY.get(f.severity))}] {_e(f.title)}</b> <span class='small muted'>{_e(f.rule_code)}</span>"
              f"<div class='small muted'>Lokasi: {_e(_location(f))} &middot; Status: {_e(status)}</div>"
              f"<div class='small'>{_e(f.description)}</div>"
              + (f"<div class='small excerpt'>&laquo;{_e(f.evidence_excerpt)}&raquo;</div>" if f.evidence_excerpt else "")
              + (f"<div class='small'><b>Tindakan:</b> {_e(f.suggested_action)}</div>" if f.suggested_action else "")
              + (f"<div class='small'><b>Catatan editor:</b> {_e(f.review_note)}</div>" if f.review_note else "")
              + "</div>")

    human = [a for a in d.actions if a.action_type != "recalculation"]
    w("<h2>Catatan verifikasi dan keputusan</h2>")
    if not human:
        w("<p class='muted'>Belum ada tindakan verifikasi.</p>")
    else:
        w("<table><tr><th>Waktu</th><th>Pelaku</th><th>Tindakan</th><th>Catatan</th></tr>")
        for a in human:
            w(f"<tr><td class='small'>{_tz(a.created_at)}</td><td>{_e(d.names.get(a.actor_user_id, 'Sistem'))}</td>"
              f"<td>{_e(ACTIONS.get(a.action_type, a.action_type))}{' → ' + _e(a.new_status) if a.new_status else ''}</td>"
              f"<td class='small'>{_e(a.comment)}</td></tr>")
        w("</table>")
    if not for_pdf:
        w("</body></html>")
    return "".join(out)


def _pdf_safe(text: str) -> str:
    """Font bawaan PDF (Base-14) hanya mencakup Windows-1252; ganti karakter di luar itu."""
    repl = {"→": "->", "←": "<-", "Σ": "jumlah ", "≥": ">=", "≤": "<=", "±": "+/-", "✓": "v", "×": "x", "−": "-", "⏎": " "}
    for k, v in repl.items():
        text = text.replace(k, v)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def render_pdf(d: ReportData) -> bytes:
    story = pymupdf.Story(html=_pdf_safe(render_html(d, for_pdf=True)), user_css=CSS)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (40, 40, -40, -50)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    footer = _pdf_safe(f"{d.manuscript.internal_code} - screening {d.run.id} - {_tz(d.generated_at)}")
    for i, page in enumerate(doc, 1):
        page.insert_text((40, page.rect.height - 25), f"{footer}    Halaman {i}/{doc.page_count}", fontsize=7, color=(0.45, 0.45, 0.43))
    doc.set_metadata({"title": f"Laporan screening {d.manuscript.internal_code}", "producer": "Sistem Screening Naskah",
                      "creator": d.run.engine_version})
    data = doc.tobytes(deflate=True)
    doc.close()
    return data


def _cell(v: Any) -> Any:
    """Cegah formula injection saat CSV dibuka di spreadsheet."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def render_csv(d: ReportData, kind: str) -> str:
    buf = io.StringIO()
    buf.write("﻿")  # BOM agar Excel membaca UTF-8
    wr = csv.writer(buf)
    if kind == "findings":
        wr.writerow(["no", "kode_aturan", "keparahan", "jalur", "kategori", "judul", "deskripsi", "bagian", "halaman", "perkiraan_halaman",
                     "blok", "kutipan", "tindakan", "perlu_verifikasi_manusia", "status_verifikasi", "catatan_editor"])
        for i, f in enumerate(d.findings, 1):
            wr.writerow([_cell(x) for x in [i, f.rule_code, SEVERITY.get(f.severity), f.track, f.category, f.title, f.description, f.section_path,
                                            f.page_number, f.page_estimate, f.paragraph_id, f.evidence_excerpt, f.suggested_action,
                                            "ya" if f.requires_human_verification else "tidak", VERIFICATION.get(f.verification_status), f.review_note]])
    else:
        wr.writerow(["kode_kriteria", "kriteria", "jenis", "bobot_persen", "skor", "kontribusi", "status", "keterangan"])
        for s in d.scores:
            wr.writerow([_cell(x) for x in [s.criterion_code_snapshot, s.criterion_name_snapshot, s.result_type, float(s.weight_percent),
                                            float(s.raw_score) if s.raw_score is not None else "", float(s.weighted_contribution)
                                            if s.weighted_contribution is not None else "", s.scoring_status, s.explanation]])
    return buf.getvalue()
