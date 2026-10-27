"""Verifikasi editor, bukti manual, keputusan akhir, perbandingan versi, dan laporan."""

import uuid
from typing import Any, Literal, NoReturn
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, Principal, load_manuscript, require
from app.core.errors import AppError, not_found
from app.core.permissions import Perm
from app.models import ComplianceCheck, Finding, ReviewAction, ScreeningRun, User
from app.screening import review
from app.screening.compare import compare, previous_run
from app.services import audit, report

router = APIRouter(tags=["review"])


class ReviewIn(BaseModel):
    finding_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["confirm", "false_positive", "needs_check", "reset"]
    note: str | None = Field(None, max_length=2000)


class EvidenceIn(BaseModel):
    observed: Literal["pass", "fail"] | None
    note: str = Field(max_length=2000)


class DecisionIn(BaseModel):
    decision: Literal["ACCEPTED_FOR_NEXT_STAGE", "REVISION_REQUIRED", "REJECTED", "PENDING_VERIFICATION", "SCREENING_INCOMPLETE"]
    note: str | None = Field(None, max_length=4000)


def _run(db, principal: Principal, run_id: uuid.UUID, request: Request) -> ScreeningRun:
    r = db.get(ScreeningRun, run_id)
    if r is None:
        raise not_found("Screening")
    load_manuscript(db, principal, r.manuscript_id, request)
    return r


def _raise(exc: review.ReviewError) -> NoReturn:
    status = 422 if exc.code in ("NOTE_REQUIRED", "INVALID_ACTION", "INVALID_OBSERVED", "INVALID_DECISION", "ACCEPT_BLOCKED", "FINDING_NOT_IN_RUN") else 409
    raise AppError(status, exc.code, exc.message, exc.details) from None


def _actions(db, stmt) -> list[dict[str, Any]]:
    rows = db.execute(stmt.add_columns(User.full_name).outerjoin(User, User.id == ReviewAction.actor_user_id).order_by(ReviewAction.created_at.desc())).all()
    return [
        {"id": str(a.id), "action_type": a.action_type, "actor_name": name, "previous_status": a.previous_status, "new_status": a.new_status,
         "comment": a.comment, "finding_id": str(a.finding_id) if a.finding_id else None,
         "compliance_check_id": str(a.compliance_check_id) if a.compliance_check_id else None, "created_at": a.created_at.isoformat(),
         "evidence_json": a.evidence_json}
        for a, name in rows
    ]


@router.post("/screenings/{run_id}/findings/review")
def review_findings(run_id: uuid.UUID, body: ReviewIn, db: DB, request: Request, principal: Principal = require(Perm.FINDING_VERIFY)) -> dict:
    r = _run(db, principal, run_id, request)
    try:
        out = review.review_findings(db, r, body.finding_ids, body.action, body.note, principal.id, request)
    except review.ReviewError as exc:
        db.rollback()
        _raise(exc)
    db.commit()
    return out


@router.post("/screenings/{run_id}/compliance/{check_id}/evidence")
def manual_evidence(run_id: uuid.UUID, check_id: uuid.UUID, body: EvidenceIn, db: DB, request: Request,
                    principal: Principal = require(Perm.FINDING_VERIFY)) -> dict:
    r = _run(db, principal, run_id, request)
    c = db.get(ComplianceCheck, check_id)
    if c is None or c.screening_run_id != r.id:
        raise not_found("Item kepatuhan")
    try:
        out = review.record_manual_evidence(db, r, c, body.observed, body.note, principal.id, request)
    except review.ReviewError as exc:
        db.rollback()
        _raise(exc)
    db.commit()
    return out


@router.get("/findings/{finding_id}/history")
def finding_history(finding_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> list[dict]:
    f = db.get(Finding, finding_id)
    if f is None:
        raise not_found("Temuan")
    _run(db, principal, f.screening_run_id, request)
    return _actions(db, select(ReviewAction).where(ReviewAction.finding_id == finding_id))


@router.get("/screenings/{run_id}/review-log")
def review_log(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request,
               include_system: bool = Query(False, description="Sertakan rekalkulasi otomatis")) -> list[dict]:
    _run(db, principal, run_id, request)
    stmt = select(ReviewAction).where(ReviewAction.screening_run_id == run_id)
    if not include_system:
        stmt = stmt.where(ReviewAction.action_type != "recalculation")
    return _actions(db, stmt)


@router.get("/screenings/{run_id}/decision")
def decision_info(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> dict:
    r = _run(db, principal, run_id, request)
    info = review.blockers_and_recommendation(db, r)
    decider = db.get(User, r.decided_by) if r.decided_by else None
    history = _actions(db, select(ReviewAction).where(ReviewAction.screening_run_id == run_id, ReviewAction.action_type == "decision"))
    return {
        **info,
        "final_decision": r.final_decision,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decided_by": decider.full_name if decider else None,
        "decision_note": r.decision_note,
        "history": history,
        "can_decide": principal.can(Perm.DECISION_MAKE),
    }


@router.post("/screenings/{run_id}/decision")
def make_decision(run_id: uuid.UUID, body: DecisionIn, db: DB, request: Request, principal: Principal = require(Perm.DECISION_MAKE)) -> dict:
    r = _run(db, principal, run_id, request)
    try:
        out = review.decide(db, r, body.decision, body.note, principal.id, request)
    except review.ReviewError as exc:
        db.rollback()
        _raise(exc)
    db.commit()
    return out


@router.get("/screenings/{run_id}/comparison")
def comparison(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> dict | None:
    r = _run(db, principal, run_id, request)
    prev = previous_run(db, r)
    return compare(db, prev, r) if prev else None


@router.get("/screenings/{run_id}/report")
def get_report(run_id: uuid.UUID, db: DB, request: Request, format: Literal["html", "pdf"] = "pdf",
               principal: Principal = require(Perm.REPORT_EXPORT)) -> Response:
    r = _run(db, principal, run_id, request)
    if r.status in ("QUEUED", "PROCESSING"):
        raise AppError(409, "RUN_NOT_FINISHED", "Screening belum selesai.")
    data = report.ReportData(db, r)
    name = f"laporan-{data.manuscript.internal_code}-v{data.version.version_number}-run{r.run_number}"
    audit.record(db, "report.exported", "screening_run", actor_id=principal.id, entity_id=r.id, manuscript_id=r.manuscript_id,
                 after={"format": format}, request=request)
    db.commit()
    if format == "html":
        return Response(report.render_html(data), media_type="text/html; charset=utf-8",
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}.html", "Cache-Control": "no-store",
                                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"})
    return Response(report.render_pdf(data), media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.pdf", "Cache-Control": "no-store"})


@router.get("/screenings/{run_id}/export")
def export_csv(run_id: uuid.UUID, db: DB, request: Request, kind: Literal["findings", "scores"] = "findings",
               principal: Principal = require(Perm.REPORT_EXPORT)) -> Response:
    r = _run(db, principal, run_id, request)
    data = report.ReportData(db, r)
    audit.record(db, "report.exported", "screening_run", actor_id=principal.id, entity_id=r.id, manuscript_id=r.manuscript_id,
                 after={"format": "csv", "kind": kind}, request=request)
    db.commit()
    name = f"{'temuan' if kind == 'findings' else 'skor'}-{data.manuscript.internal_code}-run{r.run_number}.csv"
    return Response(report.render_csv(data, kind), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "no-store"})

