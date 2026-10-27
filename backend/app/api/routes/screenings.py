"""Screening run, temuan (peta revisi), kepatuhan ISBN, dan skor editorial.

Tidak ada endpoint untuk mengubah skor secara langsung (FR-07).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser, Principal, load_manuscript, require
from app.core.config import get_settings
from app.core.constants import DISCLAIMER
from app.core.errors import AppError, not_found
from app.core.permissions import Perm
from app.models import ComplianceCheck, DocumentVersion, Finding, ScoreResult, ScreeningRun
from app.reader.model import PATH_SEPARATOR
from app.schemas import Page
from app.screening import runner

router = APIRouter(tags=["screenings"])



class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RunBrief(ORM):
    id: uuid.UUID
    manuscript_id: uuid.UUID
    document_version_id: uuid.UUID
    run_number: int
    status: str
    isbn_status: str | None
    editorial_status: str | None
    total_score: Decimal | None
    trigger: str
    scope: str = "full"
    queued_at: datetime
    completed_at: datetime | None
    result_summary_json: dict[str, Any]


class RunOut(RunBrief):
    started_at: datetime | None
    engine_version: str
    rule_set: dict[str, Any]
    rubric: dict[str, Any] | None
    version_number: int
    error_details: dict[str, Any] | None
    extraction_summary_json: dict[str, Any]
    final_decision: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    recalculated_at: datetime | None = None
    disclaimer: str = DISCLAIMER


class FindingOut(ORM):
    id: uuid.UUID
    rule_code: str
    track: str
    category: str
    severity: str
    criterion_code: str | None
    title: str
    description: str
    evidence_excerpt: str | None
    page_number: int | None
    page_estimate: int | None
    section_path: str | None
    paragraph_id: str | None
    paragraph_index: int | None
    char_start: int | None
    char_end: int | None
    suggested_action: str | None
    requires_human_verification: bool
    blocking: bool
    verification_status: str
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    machine_result_json: dict[str, Any]


class ComplianceOut(ORM):
    id: uuid.UUID
    rule_code: str
    title: str
    observed: str
    result_status: str
    authority_type: str
    rule_verification_status: str
    blocking: bool
    evidence_json: dict[str, Any]
    explanation: str | None
    requires_human_verification: bool = False
    manual_observed: str | None = None
    manual_note: str | None = None
    verified_at: datetime | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_reference: str | None = None


class ScoreOut(ORM):
    criterion_code_snapshot: str | None
    criterion_name_snapshot: str | None
    result_type: str
    raw_score: Decimal | None
    weight_percent: Decimal
    weighted_contribution: Decimal | None
    scoring_status: str
    evidence_coverage: Decimal | None
    explanation: str | None
    calculation_details_json: dict[str, Any]


class RunCreate(BaseModel):
    document_version_id: uuid.UUID
    scope: Literal["isbn", "layout"] = "isbn"


def _run_out(db, r: ScreeningRun) -> RunOut:
    v = db.get(DocumentVersion, r.document_version_id)
    base = RunBrief.model_validate(r).model_dump()
    return RunOut(
        **base,
        started_at=r.started_at,
        engine_version=r.engine_version,
        rule_set={"id": str(r.rule_set_id), "name": r.rule_set.name, "version": r.rule_set.version},
        rubric={"id": str(r.rubric.id), "name": r.rubric.name, "version": r.rubric.version, "manuscript_type": r.rubric.manuscript_type,
                "min_scoring_coverage": float(r.rubric.min_scoring_coverage), "thresholds": r.rubric.score_thresholds_json} if r.rubric else None,
        version_number=v.version_number,
        error_details=r.error_details,
        extraction_summary_json=r.extraction_summary_json,
        final_decision=r.final_decision,
        decided_at=r.decided_at,
        decision_note=r.decision_note,
        recalculated_at=r.recalculated_at,
    )


def _load_run(db, principal: Principal, run_id: uuid.UUID, request: Request) -> ScreeningRun:
    r = db.get(ScreeningRun, run_id)
    if r is None:
        raise not_found("Screening")
    load_manuscript(db, principal, r.manuscript_id, request)
    return r


def _start(db, version: DocumentVersion, principal: Principal, request: Request, background: BackgroundTasks, trigger: str,
           scope: str = "isbn") -> ScreeningRun:
    if version.extraction_status in ("PENDING", "PROCESSING"):
        raise AppError(409, "EXTRACTION_IN_PROGRESS", "Berkas masih dibaca. Screening berjalan otomatis setelah pembacaan selesai.")
    if version.extraction_status == "FAILED":
        raise AppError(409, "EXTRACTION_FAILED", "Berkas gagal dibaca; perbaiki berkas dan unggah versi baru sebelum screening.")
    if db.scalar(select(ScreeningRun.id).where(ScreeningRun.document_version_id == version.id, ScreeningRun.scope == scope,
                                                ScreeningRun.status.in_(("QUEUED", "PROCESSING"))).limit(1)):
        raise AppError(409, "SCREENING_IN_PROGRESS", "Screening untuk versi ini sedang berjalan.")
    try:
        run = runner.create_run(db, version, principal.id, trigger, request, scope=scope)
    except runner.NoActiveRuleSet as exc:
        raise AppError(409, "NO_RULE_SET", str(exc)) from None
    db.commit()
    if get_settings().extract_on_upload:
        background.add_task(runner.run_screening, run.id)
    return run


@router.post("/screenings", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def create_screening(body: RunCreate, db: DB, request: Request, background: BackgroundTasks,
                     principal: Principal = require(Perm.SCREENING_RUN)) -> RunOut:
    v = db.get(DocumentVersion, body.document_version_id)
    if v is None:
        raise not_found("Versi dokumen")
    load_manuscript(db, principal, v.manuscript_id, request)
    return _run_out(db, _start(db, v, principal, request, background, "manual", body.scope))


@router.post("/versions/{version_id}/layout-check", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def layout_check(version_id: uuid.UUID, db: DB, request: Request, background: BackgroundTasks,
                 principal: Principal = require(Perm.SCREENING_RUN)) -> RunOut:
    """Tahap 2 atas permintaan: cek tata letak & kerapian naskah, beserta skor dan daftar revisi."""
    v = db.get(DocumentVersion, version_id)
    if v is None:
        raise not_found("Versi dokumen")
    load_manuscript(db, principal, v.manuscript_id, request)
    return _run_out(db, _start(db, v, principal, request, background, "layout_request", "layout"))


@router.post("/screenings/{run_id}/rerun", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def rerun(run_id: uuid.UUID, db: DB, request: Request, background: BackgroundTasks, principal: Principal = require(Perm.SCREENING_RUN)) -> RunOut:
    """Screening baru untuk versi yang sama dengan rule set & rubrik yang terbit saat ini. Hasil lama tetap tersimpan."""
    r = _load_run(db, principal, run_id, request)
    scope = r.scope if r.scope != "full" else "isbn"
    return _run_out(db, _start(db, db.get(DocumentVersion, r.document_version_id), principal, request, background, "rerun", scope))


@router.get("/manuscripts/{manuscript_id}/screenings", response_model=list[RunBrief])
def manuscript_runs(manuscript_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> list[RunBrief]:
    load_manuscript(db, principal, manuscript_id, request)
    rows = db.scalars(select(ScreeningRun).where(ScreeningRun.manuscript_id == manuscript_id).order_by(ScreeningRun.queued_at.desc())).all()
    return [RunBrief.model_validate(r) for r in rows]


@router.get("/versions/{version_id}/screenings/latest", response_model=RunOut | None)
def latest_for_version(version_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request,
                       scope: Literal["isbn", "layout"] | None = None) -> RunOut | None:
    v = db.get(DocumentVersion, version_id)
    if v is None:
        raise not_found("Versi dokumen")
    load_manuscript(db, principal, v.manuscript_id, request)
    stmt = select(ScreeningRun).where(ScreeningRun.document_version_id == version_id)
    if scope:
        # Run lama (full) memuat kedua tahap.
        stmt = stmt.where(ScreeningRun.scope.in_((scope, "full")))
    r = db.scalar(stmt.order_by(ScreeningRun.run_number.desc()).limit(1))
    return _run_out(db, r) if r else None


@router.get("/screenings/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> RunOut:
    return _run_out(db, _load_run(db, principal, run_id, request))


SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


@router.get("/screenings/{run_id}/findings", response_model=Page[FindingOut])
def findings(
    run_id: uuid.UUID,
    db: DB,
    principal: CurrentUser,
    request: Request,
    track: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    rule_code: str | None = None,
    section_path: str | None = Query(None, max_length=2000),
    page_number: int | None = Query(None, ge=1),
    verification_status: str | None = None,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> Page[FindingOut]:
    _load_run(db, principal, run_id, request)
    stmt = select(Finding).where(Finding.screening_run_id == run_id)
    for col, val in ((Finding.track, track), (Finding.severity, severity), (Finding.category, category),
                     (Finding.rule_code, rule_code), (Finding.verification_status, verification_status)):
        if val:
            stmt = stmt.where(col == val)
    if section_path:
        stmt = stmt.where(or_(Finding.section_path == section_path,
                              Finding.section_path.startswith(section_path + PATH_SEPARATOR, autoescape=True)))
    if page_number:
        stmt = stmt.where(or_(Finding.page_number == page_number, Finding.page_estimate == page_number))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Finding.title.ilike(like), Finding.description.ilike(like), Finding.evidence_excerpt.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Finding.sort_key, Finding.rule_code, Finding.char_start).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[FindingOut.model_validate(f) for f in rows], total=total, page=page, page_size=page_size)


@router.get("/screenings/{run_id}/findings/facets")
def finding_facets(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> dict:
    """Jumlah temuan per bab, keparahan, kategori, dan aturan — untuk filter peta revisi."""
    _load_run(db, principal, run_id, request)
    base = select(Finding).where(Finding.screening_run_id == run_id).subquery()

    def group(col):
        return {k or "": v for k, v in db.execute(select(col, func.count()).group_by(col)).all()}

    # Bagian tingkat teratas dari section_path, urut sesuai posisi di naskah.
    chapter = func.split_part(base.c.section_path, PATH_SEPARATOR, 1)
    chapters = db.execute(select(chapter, func.count()).group_by(chapter).order_by(func.min(base.c.sort_key))).all()
    return {
        "severity": group(base.c.severity),
        "track": group(base.c.track),
        "category": group(base.c.category),
        "rule_code": group(base.c.rule_code),
        "chapter": [{"section_path": k or None, "count": v} for k, v in chapters],
    }


@router.get("/screenings/{run_id}/compliance", response_model=list[ComplianceOut])
def compliance(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> list[ComplianceOut]:
    r = _load_run(db, principal, run_id, request)
    snaps = {i.rule_snapshot_json["rule_code"]: i.rule_snapshot_json for i in r.rule_set.items}
    rows = db.scalars(select(ComplianceCheck).where(ComplianceCheck.screening_run_id == run_id).order_by(ComplianceCheck.sort_order)).all()
    out = []
    for c in rows:
        s = snaps.get(c.rule_code, {})
        out.append(ComplianceOut.model_validate(c).model_copy(update={
            "source_title": s.get("source_title"), "source_url": s.get("source_url"), "source_reference": s.get("source_reference")}))
    return out


@router.get("/screenings/{run_id}/scores", response_model=list[ScoreOut])
def scores(run_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> list[ScoreOut]:
    _load_run(db, principal, run_id, request)
    rows = db.scalars(select(ScoreResult).where(ScoreResult.screening_run_id == run_id).order_by(ScoreResult.sort_order)).all()
    return [ScoreOut.model_validate(s) for s in rows]
