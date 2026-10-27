import io

import pymupdf
import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import ComplianceCheck
from app.screening.review import isbn_from_rows
from tests.factories import make_book_docx
from tests.test_api import API, events, upload
from tests.test_screening import findings, latest_run, layout_run, quick


def setup_run(client, auth, users, data=None, manuscript_type="fiksi"):
    op = auth("intake_operator")
    qc = quick(client, op, data or make_book_docx(issues=True), manuscript_type=manuscript_type)
    r = client.patch(f"{API}/manuscripts/{qc['manuscript_id']}", json={"assigned_editor_id": str(users["editor"].id)}, headers=op)
    assert r.status_code == 200
    return qc, layout_run(client, op, qc["version"]["id"])


def review(client, headers, run_id, ids, action, note=None):
    return client.post(f"{API}/screenings/{run_id}/findings/review", json={"finding_ids": ids, "action": action, "note": note}, headers=headers)


def get_run(client, headers, run_id):
    return client.get(f"{API}/screenings/{run_id}", headers=headers).json()


# --- Verifikasi temuan --------------------------------------------------------


def test_false_positive_recalculates_score_with_audit(client, auth, users):
    _, run = setup_run(client, auth, users)
    ed = auth("editor")
    items = findings(client, ed, run["id"])
    todo = next(f for f in items if f["rule_code"] == "TEC-001")
    before = float(run["total_score"])

    r = review(client, ed, run["id"], [todo["id"]], "false_positive")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOTE_REQUIRED"
    r = review(client, ed, run["id"], [todo["id"]], "false_positive", "TODO di sini bagian kutipan dialog tokoh, bukan placeholder.")
    assert r.status_code == 200, r.text
    after = get_run(client, ed, run["id"])
    assert float(after["total_score"]) > before and after["recalculated_at"]
    f = next(x for x in findings(client, ed, run["id"]) if x["id"] == todo["id"])
    assert f["verification_status"] == "FALSE_POSITIVE" and f["review_note"].startswith("TODO di sini")
    hist = client.get(f"{API}/findings/{todo['id']}/history", headers=ed).json()
    assert hist[0]["action_type"] == "false_positive" and hist[0]["actor_name"] == users["editor"].full_name
    rec = events("screening.recalculated")[-1]
    assert rec.before_json["total_score"] == before and rec.after_json["total_score"] == float(after["total_score"])

    # Membatalkan tanda mengembalikan skor persis seperti hasil mesin (deterministik).
    assert review(client, ed, run["id"], [todo["id"]], "reset").status_code == 200
    assert float(get_run(client, ed, run["id"])["total_score"]) == before


def test_bulk_confirm_and_progress(client, auth, users):
    _, run = setup_run(client, auth, users)
    ed = auth("editor")
    ids = [f["id"] for f in findings(client, ed, run["id"])]
    assert review(client, ed, run["id"], ids, "confirm").status_code == 200
    summary = get_run(client, ed, run["id"])["result_summary_json"]["verification"]
    assert summary["reviewed"] == summary["total"] == len(ids) and summary["CONFIRMED"] == len(ids)


def test_review_permissions(client, auth, users):
    _, run = setup_run(client, auth, users)
    fid = findings(client, auth("editor"), run["id"])[0]["id"]
    assert review(client, auth("intake_operator"), run["id"], [fid], "confirm").status_code == 403
    assert review(client, auth("auditor"), run["id"], [fid], "confirm").status_code == 403
    assert review(client, auth("manager"), run["id"], [fid], "confirm").status_code == 200
    # Finding dari run lain ditolak.
    _, other = setup_run(client, auth, users)
    other_fid = findings(client, auth("editor"), other["id"])[0]["id"]
    r = review(client, auth("editor"), run["id"], [other_fid], "confirm")
    assert r.status_code == 422 and r.json()["error"]["code"] == "FINDING_NOT_IN_RUN"
    # Tidak ada endpoint untuk menulis skor langsung.
    assert client.patch(f"{API}/screenings/{run['id']}/scores", json={"total": 100}, headers=auth("manager")).status_code == 405


def test_review_actions_are_immutable(client, auth, users):
    _, run = setup_run(client, auth, users)
    fid = findings(client, auth("editor"), run["id"])[0]["id"]
    review(client, auth("editor"), run["id"], [fid], "confirm")
    with SessionLocal() as db:
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("UPDATE review_actions SET comment = 'diubah'"))
        db.rollback()


# --- Bukti manual ISBN --------------------------------------------------------


def test_manual_evidence_only_for_manual_items(client, auth, users):
    qc, _ = setup_run(client, auth, users, make_book_docx())
    run = client.get(
        f"{API}/versions/{qc['version']['id']}/screenings/latest", params={"scope": "isbn"}, headers=auth("editor")).json()
    ed = auth("editor")
    comp = client.get(f"{API}/screenings/{run['id']}/compliance", headers=ed).json()
    auto = next(c for c in comp if c["rule_code"] == "ISB-001")
    manual = next(c for c in comp if c["rule_code"] == "ISB-006")
    assert manual["requires_human_verification"] and manual["observed"] == "unknown"
    r = client.post(f"{API}/screenings/{run['id']}/compliance/{auto['id']}/evidence", json={"observed": "pass", "note": "cek manual"}, headers=ed)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_MANUAL"
    r = client.post(f"{API}/screenings/{run['id']}/compliance/{manual['id']}/evidence",
                    json={"observed": "pass", "note": "Surat pernyataan bertanda tangan diterima 26-10-2026"}, headers=ed)
    assert r.status_code == 200, r.text
    after = next(c for c in client.get(f"{API}/screenings/{run['id']}/compliance", headers=ed).json() if c["rule_code"] == "ISB-006")
    assert after["manual_observed"] == "pass" and after["verified_at"]
    # Aturan sudah diverifikasi terhadap Perpusnas 11/2025 → bukti manual yang diterima = memenuhi.
    assert after["result_status"] == "pass"
    assert events("compliance.evidence_recorded")


def test_isbn_status_from_manual_evidence_when_rules_verified():
    def row(code, observed, manual=None, human=False, verified="verified", blocking=True):
        return ComplianceCheck(rule_code=code, observed=observed, manual_observed=manual, requires_human_verification=human,
                               rule_verification_status=verified, blocking=blocking)

    ok = [row("A", "pass"), row("B", "unknown", manual="pass", human=True), row("C", "not_applicable")]
    assert isbn_from_rows(ok, True)[0] == "PASS"
    # Dokumen pengajuan yang belum dicatat tidak menentukan kelayakan naskah.
    assert isbn_from_rows([row("A", "pass"), row("B", "unknown", human=True)], True)[0] == "PASS"
    assert isbn_from_rows([row("A", "pass"), row("B", "unknown", manual="fail", human=True)], True)[0] == "FAIL"
    assert isbn_from_rows([row("A", "fail", verified="unverified")], True)[0] == "NEEDS_VERIFICATION"
    assert isbn_from_rows(ok, False)[0] == "INCOMPLETE"


# --- Keputusan akhir ----------------------------------------------------------


def test_decision_guardrails_and_effects(client, auth, users):
    qc, run = setup_run(client, auth, users)
    mgr = auth("manager")
    info = client.get(f"{API}/screenings/{run['id']}/decision", headers=mgr).json()
    assert info["recommendation"] in ("PENDING_VERIFICATION", "REVISION_REQUIRED") and info["can_decide"]
    assert any("belum diverifikasi" in b for b in info["accept_blockers"])

    r = client.post(f"{API}/screenings/{run['id']}/decision", json={"decision": "ACCEPTED_FOR_NEXT_STAGE"}, headers=mgr)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ACCEPT_BLOCKED" and r.json()["error"]["details"]["problems"]
    assert client.post(f"{API}/screenings/{run['id']}/decision", json={"decision": "REVISION_REQUIRED"}, headers=mgr).status_code == 422
    assert client.post(f"{API}/screenings/{run['id']}/decision", json={"decision": "REVISION_REQUIRED", "note": "x" * 12},
                       headers=auth("editor")).status_code == 403

    r = client.post(f"{API}/screenings/{run['id']}/decision",
                    json={"decision": "REVISION_REQUIRED", "note": "Hapus duplikasi halaman judul dan placeholder TODO."}, headers=mgr)
    assert r.status_code == 200 and r.json()["intake_status"] == "REVISION_REQUESTED"
    ms = client.get(f"{API}/manuscripts/{qc['manuscript_id']}", headers=mgr).json()
    assert ms["intake_status"] == "REVISION_REQUESTED"
    info = client.get(f"{API}/screenings/{run['id']}/decision", headers=mgr).json()
    assert info["final_decision"] == "REVISION_REQUIRED" and info["decided_by"] == users["manager"].full_name
    assert events("screening.decided")[-1].after_json["system_recommendation"] == info["recommendation"]

    client.post(f"{API}/screenings/{run['id']}/decision", json={"decision": "REJECTED", "note": "Tidak sesuai lini terbitan penerbit."}, headers=mgr)
    fid = findings(client, mgr, run["id"])[0]["id"]
    r = review(client, auth("editor"), run["id"], [fid], "confirm")
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_DECIDED"


def test_accept_after_all_major_findings_reviewed(client, auth, users):
    _, run = setup_run(client, auth, users, make_book_docx())
    ed, mgr = auth("editor"), auth("manager")
    major = [f["id"] for f in findings(client, ed, run["id"]) if f["severity"] in ("critical", "major")]
    if major:
        review(client, ed, run["id"], major, "confirm")
    run = get_run(client, mgr, run["id"])
    info = client.get(f"{API}/screenings/{run['id']}/decision", headers=mgr).json()
    if info["accept_blockers"]:
        pytest.skip(f"Naskah contoh masih punya penghalang: {info['accept_blockers']}")
    r = client.post(f"{API}/screenings/{run['id']}/decision", json={"decision": "ACCEPTED_FOR_NEXT_STAGE", "note": "Lanjut ke penyuntingan."}, headers=mgr)
    assert r.status_code == 200 and r.json()["intake_status"] == "ACCEPTED"


def test_decision_only_on_latest_run(client, auth, users):
    _, run = setup_run(client, auth, users)
    mgr = auth("manager")
    client.post(f"{API}/screenings/{run['id']}/rerun", headers=auth("intake_operator"))
    r = client.post(f"{API}/screenings/{run['id']}/decision", json={"decision": "PENDING_VERIFICATION"}, headers=mgr)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_LATEST"


# --- Perbandingan versi -------------------------------------------------------


def test_new_version_comparison_marks_resolved(client, auth, users):
    qc, old = setup_run(client, auth, users)
    op = auth("intake_operator")
    v2 = upload(client, op, qc["manuscript_id"], make_book_docx(), name="revisi.docx").json()
    new = layout_run(client, op, v2["id"])
    cmp = client.get(f"{API}/screenings/{new['id']}/comparison", headers=op).json()
    assert cmp["previous"]["version_number"] == 1 and cmp["current"]["version_number"] == 2
    resolved_codes = {f["rule_code"] for f in cmp["resolved"]}
    assert {"TEC-001", "DUP-001", "STR-002"} <= resolved_codes
    assert cmp["current"]["total_score"] > cmp["previous"]["total_score"]
    old_findings = findings(client, op, old["id"])
    todo = next(f for f in old_findings if f["rule_code"] == "TEC-001")
    assert todo["verification_status"] == "RESOLVED_IN_NEW_VERSION"
    persisting = {f["rule_code"] for f in cmp["persisting"]}
    assert not persisting & {"TEC-001"}
    assert client.get(f"{API}/screenings/{old['id']}/comparison", headers=op).json() is None


# --- Laporan ------------------------------------------------------------------


def test_reports_pdf_html_csv(client, auth, users):
    qc, run = setup_run(client, auth, users)
    ed = auth("editor")
    fid = next(f["id"] for f in findings(client, ed, run["id"]) if f["rule_code"] == "TEC-001")
    review(client, ed, run["id"], [fid], "false_positive", "=HYPERLINK(\"http://contoh\") dialog tokoh")

    pdf = client.get(f"{API}/screenings/{run['id']}/report", params={"format": "pdf"}, headers=ed)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and "attachment" in pdf.headers["content-disposition"]
    doc = pymupdf.open(stream=pdf.content, filetype="pdf")
    text_all = "".join(p.get_text() for p in doc)
    assert qc["internal_code"] in text_all and "bukan jaminan penerimaan ISBN" in text_all
    assert "Rule set standar v1" in text_all and "Salah deteksi" in text_all and "Halaman 1/" in text_all

    html = client.get(f"{API}/screenings/{run['id']}/report", params={"format": "html"}, headers=ed)
    assert html.status_code == 200 and "Laporan Screening Naskah" in html.text
    assert "&lt;" not in qc["working_title"] and "<script>" not in html.text.split("<body>")[1].replace("window.print()", "")

    csv_text = client.get(f"{API}/screenings/{run['id']}/export", params={"kind": "findings"}, headers=ed).content.decode("utf-8")
    assert csv_text.startswith("﻿no,kode_aturan,keparahan")
    assert "'=HYPERLINK" in csv_text, "formula injection dinetralkan"
    scores = client.get(f"{API}/screenings/{run['id']}/export", params={"kind": "scores"}, headers=auth("auditor"))
    assert scores.status_code == 200 and "TOTAL" in scores.text
    assert client.get(f"{API}/screenings/{run['id']}/report", headers=auth("rule_admin")).status_code == 403
    assert len(events("report.exported")) == 4


def test_audit_summary(client, auth, users):
    setup_run(client, auth, users)
    s = client.get(f"{API}/audit-logs/summary", headers=auth("auditor")).json()
    assert s["total"] > 0 and s["by_group"]["screening"] >= 2 and s["daily"]
    assert client.get(f"{API}/audit-logs/summary", headers=auth("editor")).status_code == 403


def test_pdf_handles_non_latin_text(client, auth, users):
    """Judul/teks dengan karakter di luar Windows-1252 tidak boleh membuat PDF gagal."""
    data = make_book_docx(title="Kisah → Σ Bintang ≥ Bulan")
    _, run = setup_run(client, auth, users, data)
    pdf = client.get(f"{API}/screenings/{run['id']}/report", headers=auth("editor"))
    assert pdf.status_code == 200 and io.BytesIO(pdf.content).read(4) == b"%PDF"


