"""Verifikasi editor, rekalkulasi terkendali, dan keputusan akhir (FR-07, FR-09, PRD §7.4, §8).

Editor tidak mengisi skor. Tindakan editor hanya mengubah status verifikasi temuan atau
mencatat bukti manual; skor dan status turunan lalu dihitung ulang dengan rule set dan rubrik
yang SAMA, dan setiap perubahan tercatat (review_actions + audit log) dengan nilai sebelum/sesudah.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ComplianceCheck, DocumentVersion, Finding, Manuscript, ReviewAction, ScoreResult, ScreeningRun
from app.screening.compare import previous_run
from app.screening.runner import rubric_criteria
from app.screening.scoring import RuleInput, score
from app.services import audit

OPEN = ("UNREVIEWED", "CONFIRMED", "NEEDS_FURTHER_CHECK")
ACTION_STATUS = {
    "confirm": "CONFIRMED",
    "false_positive": "FALSE_POSITIVE",
    "needs_check": "NEEDS_FURTHER_CHECK",
    "reset": "UNREVIEWED",
}
DECISIONS = ("ACCEPTED_FOR_NEXT_STAGE", "REVISION_REQUIRED", "REJECTED", "PENDING_VERIFICATION", "SCREENING_INCOMPLETE")
INTAKE_BY_DECISION = {
    "ACCEPTED_FOR_NEXT_STAGE": "ACCEPTED",
    "REVISION_REQUIRED": "REVISION_REQUESTED",
    "REJECTED": "REJECTED",
    "PENDING_VERIFICATION": "IN_REVIEW",
    "SCREENING_INCOMPLETE": "IN_REVIEW",
}


class ReviewError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


# ---------------------------------------------------------------------------
# Status kepatuhan dari baris tersimpan
# ---------------------------------------------------------------------------


def stored_compliance_status(c: ComplianceCheck) -> str:
    """Sama dengan engine.compliance_status, ditambah bukti manual yang dicatat editor."""
    observed = c.manual_observed or c.observed
    if observed == "not_applicable":
        return "not_applicable"
    if observed == "error":
        return "incomplete"
    if observed == "unknown":
        return "needs_verification"
    if c.requires_human_verification and not c.manual_observed:
        return "needs_verification"
    if c.rule_verification_status != "verified":
        return "needs_verification"
    return "pass" if observed == "pass" else "fail"


def isbn_from_rows(rows: list[ComplianceCheck], extraction_ok: bool) -> tuple[str, dict[str, int]]:
    """Padanan engine.isbn_overall untuk baris tersimpan. Item bukti manual (dokumen pengajuan) tidak menentukan
    kelayakan naskah kecuali editor mencatat hasilnya secara eksplisit."""
    if not extraction_ok:
        return "INCOMPLETE", {}
    judged = [c for c in rows if not (c.requires_human_verification and not c.manual_observed)
              and ((c.manual_observed or c.observed) != "unknown" or (c.evidence_json or {}).get("requires_confirmation"))]
    statuses = [(c, stored_compliance_status(c)) for c in judged]
    counts: dict[str, int] = {}
    for _, st in statuses:
        counts[st] = counts.get(st, 0) + 1
    if any(st == "fail" and c.blocking for c, st in statuses):
        return "FAIL", counts
    if any(st == "incomplete" for _, st in statuses):
        return "INCOMPLETE", counts
    if any(st == "needs_verification" and c.blocking for c, st in statuses):
        return "NEEDS_VERIFICATION", counts
    if statuses and all(st == "not_applicable" for _, st in statuses):
        return "NOT_APPLICABLE", counts
    return "PASS", counts


# ---------------------------------------------------------------------------
# Rekalkulasi
# ---------------------------------------------------------------------------


def _snapshot(run: ScreeningRun) -> dict:
    return {
        "isbn_status": run.isbn_status,
        "editorial_status": run.editorial_status,
        "total_score": float(run.total_score) if run.total_score is not None else None,
    }


def recalculate(db: Session, run: ScreeningRun, actor_id: uuid.UUID | None, reason: str, request=None) -> dict:
    """Hitung ulang skor & status dari hasil mesin tersimpan + status verifikasi terbaru."""
    outcomes = (run.result_summary_json or {}).get("rule_outcomes")
    if outcomes is None:
        raise ReviewError("RECALC_UNSUPPORTED", "Screening ini dibuat sebelum rekalkulasi tersedia. Jalankan screening ulang.")
    before = _snapshot(run)
    extraction_ok = (run.extraction_summary_json or {}).get("status") == "EXTRACTED"
    findings = list(db.scalars(select(Finding).where(Finding.screening_run_id == run.id)))
    rows = list(db.scalars(select(ComplianceCheck).where(ComplianceCheck.screening_run_id == run.id)))

    isbn_status, isbn_counts = isbn_from_rows(rows, extraction_ok) if run.scope != "layout" else (None, {})
    for c in rows:
        c.result_status = stored_compliance_status(c)

    snaps = {i.rule_snapshot_json["rule_code"]: i.rule_snapshot_json for i in run.rule_set.items}
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_rule.setdefault(f.rule_code, []).append({"severity": f.severity, "verification_status": f.verification_status, "track": f.track})
    inputs = []
    for code, oc in outcomes.items():
        s = snaps.get(code)
        if not s or s["track"] != "editorial":
            continue
        eff = s.get("scoring_effect") or {}
        inputs.append(RuleInput(code, s["title"], eff.get("criterion_code"), float(eff.get("deduction_per_finding", 0)),
                                float(eff.get("max_deduction", 0)), oc["applicable"], oc["error"], by_rule.get(code, [])))
    open_findings = [{"severity": f.severity, "verification_status": f.verification_status, "track": f.track} for f in findings]

    if run.rubric is not None and run.scope != "isbn":
        out = score(rubric_criteria(run.rubric), inputs, run.rubric.score_thresholds_json or {}, float(run.rubric.min_scoring_coverage),
                    extraction_ok, open_findings)
        db.query(ScoreResult).filter(ScoreResult.screening_run_id == run.id).delete()
        for i, c in enumerate(out.criteria):
            db.add(ScoreResult(
                screening_run_id=run.id, rubric_criterion_id=c.criterion_id, criterion_code_snapshot=c.code, criterion_name_snapshot=c.name,
                result_type="criterion", raw_score=c.score, weight_percent=c.weight, weighted_contribution=c.contribution,
                scoring_status=c.status, explanation=c.explanation, calculation_details_json=c.details, sort_order=i,
            ))
        db.add(ScoreResult(
            screening_run_id=run.id, criterion_code_snapshot="TOTAL", criterion_name_snapshot="Skor total", result_type="total",
            raw_score=out.total, weight_percent=100, scoring_status="scored" if out.total is not None else "needs_verification",
            evidence_coverage=out.coverage,
            explanation=f"{out.scored_count} dari {out.applicable_count} kriteria dapat dinilai (cakupan bobot {out.coverage}%). "
                        f"Dihitung ulang setelah verifikasi editor.",
            calculation_details_json={"formula": "S = Σ w_i s_i / Σ w_i", "reasons": out.reasons, "recalculated": True}, sort_order=999,
        ))
        run.total_score, run.editorial_status = out.total, out.editorial_status
        summary_score = {"total": out.total, "coverage": out.coverage, "scored": out.scored_count,
                         "applicable": out.applicable_count, "reasons": out.reasons}
    else:
        summary_score = None

    run.isbn_status = isbn_status
    run.recalculated_at = datetime.now(UTC)
    summary = dict(run.result_summary_json or {})
    summary["score"] = summary_score
    summary["isbn_counts"] = isbn_counts
    summary["verification"] = verification_progress(findings)
    run.result_summary_json = summary
    after = _snapshot(run)
    db.add(ReviewAction(screening_run_id=run.id, actor_user_id=actor_id, action_type="recalculation",
                        previous_status=f"{before['editorial_status']} {before['total_score']}",
                        new_status=f"{after['editorial_status']} {after['total_score']}", comment=reason, evidence_json={"before": before, "after": after}))
    audit.record(db, "screening.recalculated", "screening_run", actor_id=actor_id, entity_id=run.id, manuscript_id=run.manuscript_id,
                 before=before, after={**after, "reason": reason}, request=request)
    return {"before": before, "after": after}


def verification_progress(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.verification_status] = counts.get(f.verification_status, 0) + 1
    counts["total"] = len(findings)
    counts["reviewed"] = len(findings) - counts.get("UNREVIEWED", 0)
    return counts


# ---------------------------------------------------------------------------
# Verifikasi temuan & bukti manual
# ---------------------------------------------------------------------------


def _ensure_editable(db: Session, run: ScreeningRun) -> None:
    if run.status not in ("COMPLETED", "INCOMPLETE"):
        raise ReviewError("RUN_NOT_FINISHED", "Screening belum selesai.")
    if run.final_decision == "ACCEPTED_FOR_NEXT_STAGE" or run.final_decision == "REJECTED":
        raise ReviewError("RUN_DECIDED", "Keputusan akhir sudah ditetapkan; ubah keputusan menjadi 'menunggu verifikasi' untuk membuka kembali.")


def review_findings(db: Session, run: ScreeningRun, finding_ids: list[uuid.UUID], action: str, note: str | None,
                    actor_id: uuid.UUID, request=None) -> dict:
    if action not in ACTION_STATUS:
        raise ReviewError("INVALID_ACTION", "Tindakan verifikasi tidak dikenal.")
    if action == "false_positive" and not (note and note.strip()):
        raise ReviewError("NOTE_REQUIRED", "Menandai temuan sebagai salah deteksi wajib disertai alasan.")
    _ensure_editable(db, run)
    rows = list(db.scalars(select(Finding).where(Finding.screening_run_id == run.id, Finding.id.in_(finding_ids))))
    if len(rows) != len(set(finding_ids)):
        raise ReviewError("FINDING_NOT_IN_RUN", "Sebagian temuan tidak termasuk dalam screening ini.")
    now = datetime.now(UTC)
    new_status = ACTION_STATUS[action]
    changed = 0
    for f in rows:
        if f.verification_status == "RESOLVED_IN_NEW_VERSION":
            continue
        prev = f.verification_status
        f.verification_status, f.reviewed_by, f.reviewed_at = new_status, actor_id, now
        f.review_note = note
        db.add(ReviewAction(finding_id=f.id, screening_run_id=run.id, actor_user_id=actor_id, action_type=action,
                            previous_status=prev, new_status=new_status, comment=note))
        changed += prev != new_status
    audit.record(db, "finding.reviewed", "screening_run", actor_id=actor_id, entity_id=run.id, manuscript_id=run.manuscript_id,
                 after={"action": action, "findings": len(rows), "changed": changed, "note": note}, request=request)
    db.flush()
    result = recalculate(db, run, actor_id, f"Verifikasi {len(rows)} temuan: {action}", request)
    return {"updated": len(rows), **result}


def record_manual_evidence(db: Session, run: ScreeningRun, check: ComplianceCheck, observed: str | None, note: str,
                           actor_id: uuid.UUID, request=None) -> dict:
    if observed not in ("pass", "fail", None):
        raise ReviewError("INVALID_OBSERVED", "Nilai bukti harus 'pass', 'fail', atau kosong.")
    if not check.requires_human_verification and check.observed != "unknown":
        raise ReviewError("NOT_MANUAL", "Item ini diperiksa otomatis oleh mesin, bukan dengan bukti manual.")
    if not note or len(note.strip()) < 5:
        raise ReviewError("NOTE_REQUIRED", "Sebutkan dokumen bukti yang diperiksa (min. 5 karakter).")
    _ensure_editable(db, run)
    prev = check.manual_observed
    check.manual_observed, check.manual_note = observed, note
    check.verified_by, check.verified_at = (actor_id, datetime.now(UTC)) if observed else (None, None)
    db.add(ReviewAction(compliance_check_id=check.id, screening_run_id=run.id, actor_user_id=actor_id, action_type="manual_evidence",
                        previous_status=prev, new_status=observed, comment=note))
    audit.record(db, "compliance.evidence_recorded", "screening_run", actor_id=actor_id, entity_id=run.id, manuscript_id=run.manuscript_id,
                 before={"rule_code": check.rule_code, "manual_observed": prev},
                 after={"rule_code": check.rule_code, "manual_observed": observed, "note": note}, request=request)
    db.flush()
    return recalculate(db, run, actor_id, f"Bukti manual {check.rule_code}: {observed or 'dibatalkan'}", request)


# ---------------------------------------------------------------------------
# Rekomendasi & keputusan
# ---------------------------------------------------------------------------


def blockers_and_recommendation(db: Session, run: ScreeningRun) -> dict:
    findings = list(db.scalars(select(Finding).where(Finding.screening_run_id == run.id)))
    open_critical = [f for f in findings if f.severity == "critical" and f.verification_status in OPEN]
    unreviewed_major = [f for f in findings if f.severity in ("critical", "major") and f.verification_status == "UNREVIEWED"]
    needs_check = [f for f in findings if f.verification_status == "NEEDS_FURTHER_CHECK"]
    newer = db.scalar(select(ScreeningRun.id).where(ScreeningRun.manuscript_id == run.manuscript_id, ScreeningRun.queued_at > run.queued_at).limit(1))

    accept_blockers = []
    if run.status != "COMPLETED":
        accept_blockers.append("Screening tidak lengkap.")
    if run.isbn_status in ("FAIL", "INCOMPLETE"):
        accept_blockers.append("Persyaratan wajib ISBN/administrasi belum terpenuhi.")
    if run.editorial_status in ("NOT_SCORABLE", "NEEDS_VERIFICATION"):
        accept_blockers.append("Skor editorial belum dapat diterbitkan.")
    if open_critical:
        accept_blockers.append(f"{len(open_critical)} temuan kritis masih terbuka.")
    if unreviewed_major:
        accept_blockers.append(f"{len(unreviewed_major)} temuan kritis/mayor belum diverifikasi editor.")
    if needs_check:
        accept_blockers.append(f"{len(needs_check)} temuan masih menunggu pemeriksaan lanjutan.")

    if run.status != "COMPLETED":
        rec = "SCREENING_INCOMPLETE"
    elif needs_check or unreviewed_major or run.editorial_status in ("NEEDS_VERIFICATION", "NOT_SCORABLE"):
        rec = "PENDING_VERIFICATION"
    elif run.isbn_status == "FAIL" or run.editorial_status in ("MINOR_REVISION", "MAJOR_REVISION", "SUBSTANTIAL_REWORK") or open_critical:
        rec = "REVISION_REQUIRED"
    else:
        rec = "ACCEPTED_FOR_NEXT_STAGE"
    return {
        "recommendation": rec,
        "accept_blockers": accept_blockers,
        "is_latest": newer is None,
        "verification": verification_progress(findings),
        "note": "Rekomendasi sistem; keputusan final ditetapkan pengguna berwenang.",
    }


def decide(db: Session, run: ScreeningRun, decision: str, note: str | None, actor_id: uuid.UUID, request=None) -> dict:
    if decision not in DECISIONS:
        raise ReviewError("INVALID_DECISION", "Keputusan tidak dikenal.")
    info = blockers_and_recommendation(db, run)
    if not info["is_latest"]:
        raise ReviewError("NOT_LATEST", "Sudah ada screening yang lebih baru untuk naskah ini; putuskan pada screening terbaru.")
    if run.status not in ("COMPLETED", "INCOMPLETE"):
        raise ReviewError("RUN_NOT_FINISHED", "Screening belum selesai.")
    if decision == "ACCEPTED_FOR_NEXT_STAGE" and info["accept_blockers"]:
        raise ReviewError("ACCEPT_BLOCKED", "Naskah belum dapat diteruskan.", {"problems": info["accept_blockers"]})
    if decision in ("REVISION_REQUIRED", "REJECTED") and not (note and len(note.strip()) >= 10):
        raise ReviewError("NOTE_REQUIRED", "Keputusan revisi/penolakan wajib disertai alasan (min. 10 karakter).")
    before = {"final_decision": run.final_decision, "note": run.decision_note}
    run.final_decision, run.decision_note = decision, note
    run.decided_by, run.decided_at = actor_id, datetime.now(UTC)
    m = db.get(Manuscript, run.manuscript_id)
    intake_before = m.intake_status
    m.intake_status = INTAKE_BY_DECISION[decision]
    db.add(ReviewAction(screening_run_id=run.id, actor_user_id=actor_id, action_type="decision",
                        previous_status=before["final_decision"], new_status=decision, comment=note,
                        evidence_json={"recommendation": info["recommendation"], "isbn_status": run.isbn_status,
                                       "editorial_status": run.editorial_status,
                                       "total_score": float(run.total_score) if run.total_score is not None else None}))
    audit.record(db, "screening.decided", "screening_run", actor_id=actor_id, entity_id=run.id, manuscript_id=run.manuscript_id,
                 before={**before, "intake_status": intake_before},
                 after={"final_decision": decision, "note": note, "intake_status": m.intake_status,
                        "system_recommendation": info["recommendation"]}, request=request)
    return {"final_decision": decision, "intake_status": m.intake_status}


# ---------------------------------------------------------------------------
# Versi baru
# ---------------------------------------------------------------------------


def mark_resolved_by_new_version(db: Session, run: ScreeningRun) -> int:
    """Temuan terbuka di versi sebelumnya yang tidak muncul lagi → RESOLVED_IN_NEW_VERSION (tindakan sistem)."""
    prev = previous_run(db, run)
    if prev is None:
        return 0
    current = {fp for fp in db.scalars(select(Finding.fingerprint).where(Finding.screening_run_id == run.id))}
    version = db.get(DocumentVersion, run.document_version_id).version_number
    n = 0
    for f in db.scalars(select(Finding).where(Finding.screening_run_id == prev.id, Finding.verification_status.in_(OPEN))):
        if f.fingerprint in current:
            continue
        db.add(ReviewAction(finding_id=f.id, screening_run_id=prev.id, actor_user_id=None, action_type="resolved_in_new_version",
                            previous_status=f.verification_status, new_status="RESOLVED_IN_NEW_VERSION",
                            comment=f"Tidak ditemukan lagi pada versi {version} (screening {run.id})."))
        f.verification_status = "RESOLVED_IN_NEW_VERSION"
        n += 1
    return n
