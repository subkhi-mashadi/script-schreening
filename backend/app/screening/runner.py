"""Orkestrasi screening run: antrean berbasis database, eksekusi, dan penyimpanan hasil."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import (
    ComplianceCheck,
    DocumentVersion,
    Finding,
    RubricVersion,
    RuleSet,
    ScoreResult,
    ScreeningRun,
)
from app.screening.compare import fingerprint
from app.screening.docview import DocView
from app.screening.engine import ENGINE_VERSION, RuleResult, compliance_explanation, compliance_status, isbn_overall, run_rules
from app.screening.scoring import RuleInput, ScoreOutcome, score
from app.reader.layout import analyze as analyze_layout
from app.services import audit, storage

log = logging.getLogger(__name__)


class NoActiveRuleSet(Exception):
    pass


def active_rule_set(db: Session) -> RuleSet | None:
    return db.scalar(select(RuleSet).where(RuleSet.status == "published").order_by(RuleSet.published_at.desc()).limit(1))


def active_rubric(db: Session, manuscript_type: str) -> RubricVersion | None:
    return db.scalar(
        select(RubricVersion)
        .where(RubricVersion.status == "published", RubricVersion.manuscript_type == manuscript_type)
        .order_by(RubricVersion.published_at.desc())
        .limit(1)
    )


def rule_items(rs: RuleSet) -> list[dict[str, Any]]:
    return [{**i.rule_snapshot_json, "enabled": i.enabled, "execution_order": i.execution_order} for i in rs.items]


def rubric_criteria(rv: RubricVersion | None) -> list[dict[str, Any]]:
    if rv is None:
        return []
    return [{"id": c.id, "code": c.criterion_code, "name": c.name, "weight": float(c.weight_percent), "required": c.required_for_scoring}
            for c in rv.criteria]


# ---------------------------------------------------------------------------
# Evaluasi murni (dipakai screening tersimpan dan simulasi)
# ---------------------------------------------------------------------------


@dataclass
class Evaluation:
    results: list[RuleResult]
    isbn_status: str
    isbn_counts: dict[str, int]
    score: ScoreOutcome | None
    extraction_ok: bool


def finding_severity(rr: RuleResult, fd) -> str:
    return fd.severity or rr.rule["severity"]


SCOPE_TRACK = {"isbn": "compliance", "layout": "editorial"}


def evaluate(doc: DocView, items: list[dict[str, Any]], rubric: RubricVersion | None, scope: str = "full") -> Evaluation:
    """scope isbn: hanya aturan kepatuhan; layout: aturan editorial + tata letak + skor; full: keduanya."""
    extraction_ok = doc.extraction_status == "EXTRACTED"
    track = SCOPE_TRACK.get(scope)
    items = [i for i in items if track is None or i.get("track") == track]
    results = run_rules(doc, items) if extraction_ok else []
    isbn_status, counts = isbn_overall(results, extraction_ok) if scope != "layout" else (None, {})
    outcome = None
    if rubric is not None and scope != "isbn":
        inputs, open_findings = [], []
        for rr in results:
            eff = rr.rule.get("scoring_effect") or {}
            fl = [{"severity": finding_severity(rr, f), "verification_status": "UNREVIEWED", "track": rr.rule["track"]} for f in rr.findings]
            open_findings.extend(fl)
            if rr.rule["track"] != "editorial":
                continue  # skor editorial tidak membaca jalur kepatuhan (gerbang terpisah)
            inputs.append(RuleInput(rr.code, rr.rule["title"], eff.get("criterion_code"), float(eff.get("deduction_per_finding", 0)),
                                    float(eff.get("max_deduction", 0)), rr.applicable, rr.error is not None, fl))
        outcome = score(rubric_criteria(rubric), inputs, rubric.score_thresholds_json or {}, float(rubric.min_scoring_coverage),
                        extraction_ok, open_findings)
    return Evaluation(results, isbn_status, counts, outcome, extraction_ok)


# ---------------------------------------------------------------------------
# Antrean & eksekusi
# ---------------------------------------------------------------------------


def create_run(db: Session, version: DocumentVersion, initiated_by: uuid.UUID | None, trigger: str, request=None,
               scope: str = "isbn") -> ScreeningRun:
    rs = active_rule_set(db)
    if rs is None:
        raise NoActiveRuleSet("Belum ada rule set yang dipublikasikan.")
    manuscript_type = version.manuscript.manuscript_type
    rubric = active_rubric(db, manuscript_type) if scope != "isbn" else None
    db.execute(select(DocumentVersion.id).where(DocumentVersion.id == version.id).with_for_update())
    number = (db.scalar(select(func.max(ScreeningRun.run_number)).where(ScreeningRun.document_version_id == version.id)) or 0) + 1
    run = ScreeningRun(
        manuscript_id=version.manuscript_id, document_version_id=version.id, rule_set_id=rs.id,
        rubric_version_id=rubric.id if rubric else None, run_number=number, status="QUEUED",
        initiated_by=initiated_by, engine_version=ENGINE_VERSION, trigger=trigger, scope=scope,
    )
    db.add(run)
    db.flush()
    audit.record(db, "screening.queued", "screening_run", actor_id=initiated_by, entity_id=run.id, manuscript_id=version.manuscript_id,
                 after={"run_number": number, "rule_set": f"{rs.name} v{rs.version}",
                        "rubric": f"{rubric.name} v{rubric.version}" if rubric else None, "trigger": trigger,
                        "scope": scope}, request=request)
    return run


def claim(db: Session, run_id: uuid.UUID) -> bool:
    res = db.execute(
        update(ScreeningRun)
        .where(ScreeningRun.id == run_id, ScreeningRun.status == "QUEUED")
        .values(status="PROCESSING", started_at=datetime.now(UTC))
        .returning(ScreeningRun.id)
    )
    db.commit()
    return res.first() is not None


def run_screening(run_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        if not claim(db, run_id):
            return
        try:
            execute(db, db.get(ScreeningRun, run_id))
        except Exception as exc:
            db.rollback()
            log.exception("Screening %s gagal", run_id)
            run = db.get(ScreeningRun, run_id)
            run.status = "FAILED"
            run.completed_at = datetime.now(UTC)
            run.error_details = {"code": "SYSTEM_ERROR", "message": "Kesalahan sistem saat screening.", "detail": exc.__class__.__name__}
            audit.record(db, "screening.failed", "screening_run", entity_id=run.id, manuscript_id=run.manuscript_id,
                         after={"code": "SYSTEM_ERROR"})
            db.commit()


def process_queued(limit: int = 20) -> int:
    with SessionLocal() as db:
        ids = db.scalars(select(ScreeningRun.id).where(ScreeningRun.status == "QUEUED").order_by(ScreeningRun.queued_at).limit(limit)).all()
    for rid in ids:
        run_screening(rid)
    return len(ids)


def queue_and_run(version_id: uuid.UUID, initiated_by: uuid.UUID | None, trigger: str, scope: str = "isbn") -> uuid.UUID | None:
    """Dipanggil setelah ekstraksi selesai. Tidak melempar error: screening otomatis bersifat best-effort."""
    with SessionLocal() as db:
        version = db.get(DocumentVersion, version_id)
        try:
            run = create_run(db, version, initiated_by, trigger, scope=scope)
        except NoActiveRuleSet:
            log.warning("Screening otomatis dilewati: belum ada rule set terbit.")
            return None
        db.commit()
        run_id = run.id
    run_screening(run_id)
    return run_id


def apply_classification(db: Session, run: ScreeningRun, version: DocumentVersion, doc: DocView) -> dict:
    """Tentukan jenis terbitan; bila jenis naskah belum dipilih manual, perbarui otomatis agar aturan per jenis berlaku."""
    from app.core.config import get_settings
    from app.models import Manuscript
    from app.screening.classify import classify

    result = classify(doc, doc.layout, version.source_format, get_settings().publisher_category)
    m = db.get(Manuscript, version.manuscript_id)
    detected = result["jenis_terbitan"]["value"]
    auto = m.manuscript_type == "lainnya" or (m.metadata_json or {}).get("type_source") == "auto"
    result["applied"] = auto
    result["manual_type"] = None if auto else m.manuscript_type
    meta = dict(m.metadata_json or {})
    meta["classification"] = {k: v for k, v in result.items() if k != "signals"}
    if auto and m.manuscript_type != detected:
        audit.record(db, "manuscript.auto_classified", "manuscript", entity_id=m.id, manuscript_id=m.id,
                     before={"manuscript_type": m.manuscript_type}, after={"manuscript_type": detected, "run": str(run.id)})
        m.manuscript_type = detected
    if auto:
        meta["type_source"] = "auto"
    m.metadata_json = meta
    doc.manuscript.manuscript_type = m.manuscript_type
    doc.manuscript.metadata = meta
    return result


def execute(db: Session, run: ScreeningRun) -> None:
    version = db.get(DocumentVersion, run.document_version_id)
    doc = DocView.from_db(db, version)
    layout_summary = None
    classification = None
    if version.extraction_status == "EXTRACTED":
        doc.layout = analyze_layout(version.source_format, storage.read(version.storage_key))
        if run.scope in ("layout", "full"):
            layout_summary = {k: v for k, v in doc.layout.items() if k not in ("samples", "sections")}
        if run.scope in ("isbn", "full"):
            classification = apply_classification(db, run, version, doc)
    ev = evaluate(doc, rule_items(run.rule_set), run.rubric, run.scope)

    # Hapus hasil parsial (retry aman / idempoten).
    for model in (Finding, ComplianceCheck, ScoreResult):
        db.query(model).filter(model.screening_run_id == run.id).delete()

    sev_counts: dict[str, int] = {}
    track_counts: dict[str, int] = {}
    for rr in ev.results:
        eff = rr.rule.get("scoring_effect") or {}
        for fd in rr.findings:
            b = fd.block
            sev = finding_severity(rr, fd)
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            track_counts[rr.rule["track"]] = track_counts.get(rr.rule["track"], 0) + 1
            start = b.char_start + fd.span[0] if b and fd.span else (b.char_start if b else None)
            end = b.char_start + fd.span[1] if b and fd.span else (b.char_end if b else None)
            db.add(Finding(
                screening_run_id=run.id, document_version_id=version.id, rule_id=uuid.UUID(rr.rule["rule_id"]),
                rule_code=rr.code, track=rr.rule["track"], category=rr.rule["category"], severity=sev,
                criterion_code=eff.get("criterion_code") if rr.rule["track"] == "editorial" else None,
                title=fd.title, description=fd.description, evidence_excerpt=fd.excerpt(),
                page_number=b.page_number if b else None, page_estimate=b.page_estimate if b else None,
                section_path=b.section_path if b else None, document_section_id=b.section_id if b else None,
                paragraph_id=b.block_id if b else None, paragraph_index=b.index if b else None, char_start=start, char_end=end,
                suggested_action=fd.suggested_action, fingerprint=fingerprint(rr.code, fd.title, fd.excerpt()),
                requires_human_verification=fd.requires_human_verification if fd.requires_human_verification is not None
                else bool(rr.rule.get("requires_human_verification")),
                blocking=bool(rr.rule.get("blocking")), sort_key=b.index if b else -1,
                machine_result_json={"details": fd.details, "rule_title": rr.rule["title"]},
            ))
    for i, rr in enumerate(r for r in ev.results if r.is_compliance):
        st = compliance_status(rr)
        db.add(ComplianceCheck(
            screening_run_id=run.id, rule_id=uuid.UUID(rr.rule["rule_id"]), rule_code=rr.code, title=rr.rule["title"],
            observed=rr.observed or ("error" if rr.error else "unknown") if rr.applicable else "not_applicable",
            result_status=st, authority_type=rr.rule["authority_type"], rule_verification_status=rr.rule.get("verification_status", "unverified"),
            blocking=bool(rr.rule.get("blocking")), requires_human_verification=bool(rr.rule.get("requires_human_verification")),
            evidence_json={**rr.evidence, **({"error": rr.error} if rr.error else {})},
            explanation=compliance_explanation(rr, st) or rr.error, sort_order=i,
        ))
    if ev.score:
        for i, c in enumerate(ev.score.criteria):
            db.add(ScoreResult(
                screening_run_id=run.id, rubric_criterion_id=c.criterion_id, criterion_code_snapshot=c.code, criterion_name_snapshot=c.name,
                result_type="criterion", raw_score=c.score, weight_percent=c.weight, weighted_contribution=c.contribution,
                scoring_status=c.status, explanation=c.explanation, calculation_details_json=c.details, sort_order=i,
            ))
        db.add(ScoreResult(
            screening_run_id=run.id, criterion_code_snapshot="TOTAL", criterion_name_snapshot="Skor total", result_type="total",
            raw_score=ev.score.total, weight_percent=100, scoring_status="scored" if ev.score.total is not None else "needs_verification",
            evidence_coverage=ev.score.coverage,
            explanation=f"{ev.score.scored_count} dari {ev.score.applicable_count} kriteria dapat dinilai (cakupan bobot {ev.score.coverage}%).",
            calculation_details_json={"formula": "S = Σ w_i s_i / Σ w_i", "reasons": ev.score.reasons}, sort_order=999,
        ))

    errors = [r.code for r in ev.results if r.error]
    run.isbn_status = ev.isbn_status
    run.editorial_status = None if run.scope == "isbn" else (ev.score.editorial_status if ev.score else "NOT_SCORABLE")
    run.total_score = ev.score.total if ev.score else None
    run.status = "COMPLETED" if ev.extraction_ok and not errors else "INCOMPLETE"
    run.completed_at = datetime.now(UTC)
    run.extraction_summary_json = {"status": version.extraction_status, "quality": float(version.extraction_quality or 0),
                                   "engine": version.extraction_engine_version}
    run.result_summary_json = {
        "findings_total": sum(sev_counts.values()), "by_severity": sev_counts, "by_track": track_counts,
        "isbn_counts": ev.isbn_counts, "rule_errors": errors, "rules_run": len(ev.results),
        "rules_not_applicable": sum(1 for r in ev.results if not r.applicable),
        "score": None if not ev.score else {"total": ev.score.total, "coverage": ev.score.coverage, "scored": ev.score.scored_count,
                                             "applicable": ev.score.applicable_count, "reasons": ev.score.reasons},
        "chapters": len(doc.chapters), "pages": doc.page_count, "scope": run.scope, "layout": layout_summary,
        "classification": classification,
        # Hasil mesin per aturan: dasar rekalkulasi setelah verifikasi editor.
        "rule_outcomes": {r.code: {"applicable": r.applicable, "error": r.error is not None} for r in ev.results},
        "verification": {"total": sum(sev_counts.values()), "reviewed": 0, "UNREVIEWED": sum(sev_counts.values())},
    }
    db.flush()
    from app.screening.review import mark_resolved_by_new_version  # impor lokal: review bergantung pada runner

    resolved = mark_resolved_by_new_version(db, run)
    if resolved:
        run.result_summary_json = {**run.result_summary_json, "resolved_previous": resolved}
    if not ev.extraction_ok:
        run.error_details = {"code": "EXTRACTION_INCOMPLETE", "message": "Pembacaan berkas tidak lengkap; screening tidak dapat dinilai."}
    audit.record(db, "screening.completed", "screening_run", entity_id=run.id, manuscript_id=run.manuscript_id,
                 after={"status": run.status, "isbn_status": run.isbn_status, "editorial_status": run.editorial_status,
                        "total_score": float(run.total_score) if run.total_score is not None else None,
                        "findings": sum(sev_counts.values())})
    db.commit()
