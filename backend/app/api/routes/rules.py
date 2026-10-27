"""Manajemen aturan, rule set, dan rubrik (FR-05, FR-12).

Versi yang sudah terbit tidak pernah diubah: perubahan aturan baru berlaku setelah rule set
versi baru dibuat, diuji (simulasi), dan diterbitkan. Trigger database menegakkan hal ini.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePath
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import DB, Principal, require
from app.api.routes.versions import read_limited
from app.core.constants import MANUSCRIPT_TYPES
from app.core.errors import AppError, not_found
from app.core.permissions import Perm
from app.models import RubricCriterion, RubricVersion, Rule, RuleSet, RuleSetItem
from app.reader import ExtractionError, extract
from app.screening.catalog import build_rule_set, rule_snapshot
from app.screening.docview import DocView, ManuscriptInfo
from app.screening.engine import OFFICIAL, compliance_explanation, compliance_status
from app.screening.handlers import HANDLERS
from app.screening.runner import active_rubric, evaluate, finding_severity, rule_items
from app.services import audit
from app.services.file_validation import FileRejected, safe_filename, validate_upload

router = APIRouter(tags=["rules"])

SEVERITIES = ("critical", "major", "minor", "info")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RuleOut(ORM):
    id: uuid.UUID
    rule_code: str
    title: str
    description: str | None
    category: str
    track: str
    authority_type: str
    source_title: str | None
    source_url: str | None
    source_reference: str | None
    verification_status: str
    verified_at: datetime | None
    verification_note: str | None
    applies_to_types: list | None
    engine_key: str
    config_json: dict[str, Any]
    severity: str
    blocking: bool
    requires_human_verification: bool
    scoring_effect: dict[str, Any]
    execution_order: int
    status: str
    updated_at: datetime


class RuleUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=250)
    description: str | None = None
    severity: Literal["critical", "major", "minor", "info"] | None = None
    blocking: bool | None = None
    requires_human_verification: bool | None = None
    config_json: dict[str, Any] | None = None
    scoring_effect: dict[str, Any] | None = None
    status: Literal["active", "retired"] | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_reference: str | None = None


class RuleVerification(BaseModel):
    verification_status: Literal["verified", "unverified", "rejected"]
    note: str = Field(min_length=5, max_length=2000)


class RuleSetOut(ORM):
    id: uuid.UUID
    name: str
    version: int
    status: str
    description: str | None
    change_notes: str | None
    published_at: datetime | None
    created_at: datetime
    test_results_json: dict[str, Any] | None
    items_count: int = 0


class RuleSetDetail(RuleSetOut):
    items: list[dict[str, Any]]
    diff: dict[str, Any]


class RuleSetCreate(BaseModel):
    change_notes: str = Field(min_length=5, max_length=4000)


class CriterionOut(ORM):
    id: uuid.UUID
    criterion_code: str
    name: str
    description: str | None
    weight_percent: Decimal
    scoring_method_key: str
    required_for_scoring: bool


class RubricOut(ORM):
    id: uuid.UUID
    name: str
    version: int
    manuscript_type: str
    status: str
    min_scoring_coverage: Decimal
    score_thresholds_json: dict[str, Any]
    change_notes: str | None
    published_at: datetime | None
    created_at: datetime
    criteria: list[CriterionOut]


class CriterionPatch(BaseModel):
    criterion_code: str
    weight_percent: Decimal = Field(ge=0, le=100)
    required_for_scoring: bool = True


class RubricUpdate(BaseModel):
    min_scoring_coverage: Decimal | None = Field(None, ge=0, le=100)
    score_thresholds_json: dict[str, Any] | None = None
    criteria: list[CriterionPatch] | None = None
    change_notes: str | None = Field(None, max_length=4000)


# ---------------------------------------------------------------------------
# Aturan
# ---------------------------------------------------------------------------


def _rule_snapshot_dict(r: Rule) -> dict:
    return {k: v for k, v in rule_snapshot(r).items() if k not in ("rule_id",)}


@router.get("/rules", response_model=list[RuleOut])
def list_rules(db: DB, _: Principal = require(Perm.RULE_READ), track: str | None = None) -> list[RuleOut]:
    stmt = select(Rule).order_by(Rule.execution_order, Rule.rule_code)
    if track:
        stmt = stmt.where(Rule.track == track)
    return [RuleOut.model_validate(r) for r in db.scalars(stmt)]


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RuleUpdate, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RuleOut:
    r = db.get(Rule, rule_id)
    if r is None:
        raise not_found("Aturan")
    before = _rule_snapshot_dict(r)
    changes = body.model_dump(exclude_unset=True)
    if "scoring_effect" in changes and changes["scoring_effect"]:
        eff = changes["scoring_effect"]
        try:
            if float(eff.get("deduction_per_finding", 0)) < 0 or float(eff.get("max_deduction", 0)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise AppError(422, "INVALID_SCORING_EFFECT", "Potongan skor harus angka ≥ 0.") from None
    source_changed = any(k in changes for k in ("source_title", "source_url", "source_reference", "config_json"))
    for k, v in changes.items():
        setattr(r, k, v)
    # Perubahan sumber/konfigurasi aturan resmi membatalkan verifikasi sebelumnya.
    if source_changed and r.authority_type in OFFICIAL and r.verification_status == "verified":
        r.verification_status, r.verified_by, r.verified_at = "unverified", None, None
        r.verification_note = "Verifikasi dibatalkan otomatis karena sumber/konfigurasi diubah."
    db.flush()
    audit.record(db, "rule.updated", "rule", actor_id=principal.id, entity_id=r.id, before=before, after=_rule_snapshot_dict(r), request=request)
    db.commit()
    return RuleOut.model_validate(r)


@router.post("/rules/{rule_id}/verification", response_model=RuleOut)
def verify_rule(rule_id: uuid.UUID, body: RuleVerification, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RuleOut:
    r = db.get(Rule, rule_id)
    if r is None:
        raise not_found("Aturan")
    if body.verification_status == "verified" and r.authority_type in OFFICIAL and not (r.source_title and r.source_url and r.source_reference):
        raise AppError(422, "SOURCE_REQUIRED", "Aturan resmi wajib memiliki judul sumber, URL, dan rujukan pasal/ketentuan sebelum diverifikasi.")
    before = {"verification_status": r.verification_status, "note": r.verification_note}
    r.verification_status = body.verification_status
    r.verification_note = body.note
    r.verified_by = principal.id if body.verification_status == "verified" else None
    r.verified_at = datetime.now(UTC) if body.verification_status == "verified" else None
    audit.record(db, "rule.verification_changed", "rule", actor_id=principal.id, entity_id=r.id, before=before,
                 after={"verification_status": r.verification_status, "note": body.note, "rule_code": r.rule_code}, request=request)
    db.commit()
    return RuleOut.model_validate(r)


# ---------------------------------------------------------------------------
# Rule set
# ---------------------------------------------------------------------------


def _rs_out(db, rs: RuleSet) -> RuleSetOut:
    n = db.scalar(select(func.count()).select_from(RuleSetItem).where(RuleSetItem.rule_set_id == rs.id))
    return RuleSetOut.model_validate(rs).model_copy(update={"items_count": n})


TRACKED_FIELDS = ("title", "severity", "blocking", "requires_human_verification", "config_json", "scoring_effect",
                  "verification_status", "source_url", "source_reference", "applies_to_types")


def _diff(old: RuleSet | None, new: RuleSet) -> dict:
    if old is None:
        return {"against": None, "added": [], "removed": [], "changed": []}
    a = {i.rule_snapshot_json["rule_code"]: i.rule_snapshot_json for i in old.items}
    b = {i.rule_snapshot_json["rule_code"]: i.rule_snapshot_json for i in new.items}
    changed = []
    for code in sorted(a.keys() & b.keys()):
        fields = [f for f in TRACKED_FIELDS if a[code].get(f) != b[code].get(f)]
        if fields:
            changed.append({"rule_code": code, "fields": fields,
                            "before": {f: a[code].get(f) for f in fields if f != "config_json"},
                            "after": {f: b[code].get(f) for f in fields if f != "config_json"}})
    return {"against": f"{old.name} v{old.version}", "added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()), "changed": changed}


@router.get("/rule-sets", response_model=list[RuleSetOut])
def list_rule_sets(db: DB, _: Principal = require(Perm.RULE_READ)) -> list[RuleSetOut]:
    return [_rs_out(db, rs) for rs in db.scalars(select(RuleSet).order_by(RuleSet.version.desc()))]


@router.get("/rule-sets/{rs_id}", response_model=RuleSetDetail)
def get_rule_set(rs_id: uuid.UUID, db: DB, _: Principal = require(Perm.RULE_READ)) -> RuleSetDetail:
    rs = db.get(RuleSet, rs_id)
    if rs is None:
        raise not_found("Rule set")
    prev = db.scalar(select(RuleSet).where(RuleSet.name == rs.name, RuleSet.version < rs.version, RuleSet.status != "draft")
                     .order_by(RuleSet.version.desc()).limit(1))
    return RuleSetDetail(**_rs_out(db, rs).model_dump(), items=rule_items(rs), diff=_diff(prev, rs))


@router.post("/rule-sets", response_model=RuleSetOut, status_code=status.HTTP_201_CREATED)
def create_rule_set(body: RuleSetCreate, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RuleSetOut:
    if db.scalar(select(RuleSet.id).where(RuleSet.status == "draft").limit(1)):
        raise AppError(409, "DRAFT_EXISTS", "Masih ada draft rule set. Terbitkan atau hapus draft itu dulu.")
    rs = build_rule_set(db, "Rule set standar", created_by=principal.id, change_notes=body.change_notes)
    audit.record(db, "rule_set.created", "rule_set", actor_id=principal.id, entity_id=rs.id,
                 after={"version": rs.version, "rules": len(rs.items), "change_notes": body.change_notes}, request=request)
    db.commit()
    return _rs_out(db, rs)


@router.delete("/rule-sets/{rs_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule_set(rs_id: uuid.UUID, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> None:
    rs = db.get(RuleSet, rs_id)
    if rs is None:
        raise not_found("Rule set")
    if rs.status != "draft":
        raise AppError(409, "NOT_DRAFT", "Hanya draft yang dapat dihapus.")
    audit.record(db, "rule_set.deleted", "rule_set", actor_id=principal.id, entity_id=rs.id, before={"version": rs.version}, request=request)
    db.delete(rs)
    db.commit()


@router.post("/rule-sets/{rs_id}/simulate")
async def simulate(
    rs_id: uuid.UUID,
    db: DB,
    request: Request,
    file: UploadFile = File(...),
    manuscript_type: str = Form("lainnya"),
    principal: Principal = require(Perm.RULE_MANAGE),
) -> dict:
    """Uji rule set pada berkas contoh tanpa menyimpan naskah maupun hasil (kecuali ringkasan uji di draft)."""
    rs = db.get(RuleSet, rs_id)
    if rs is None:
        raise not_found("Rule set")
    if manuscript_type not in MANUSCRIPT_TYPES:
        raise AppError(422, "INVALID_TYPE", "Jenis naskah tidak dikenal.")
    filename = safe_filename(file.filename)
    data = await read_limited(file)
    try:
        vf = validate_upload(filename, data)
        res = extract(vf.source_format, data)
    except FileRejected as exc:
        raise AppError(422, exc.code, exc.message) from None
    except ExtractionError as exc:
        raise AppError(422, exc.code, exc.message) from None
    info = ManuscriptInfo(title=PurePath(filename).stem, manuscript_type=manuscript_type, language_code="id", authors=[],
                          metadata={}, has_submitted_at=False)
    doc = DocView.from_document(res.document, info, res.quality.status)
    rubric = active_rubric(db, manuscript_type)
    ev = evaluate(doc, rule_items(rs), rubric)

    findings = [
        {"rule_code": rr.code, "severity": finding_severity(rr, f), "track": rr.rule["track"], "title": f.title,
         "description": f.description, "excerpt": f.excerpt(), "block_id": f.block.block_id if f.block else None,
         "section_path": f.block.section_path if f.block else None, "page": f.block.page if f.block else None,
         "suggested_action": f.suggested_action}
        for rr in ev.results for f in rr.findings
    ]
    result = {
        "file": filename, "manuscript_type": manuscript_type, "extraction_status": res.quality.status,
        "isbn_status": ev.isbn_status,
        "compliance": [{"rule_code": rr.code, "title": rr.rule["title"], "observed": rr.observed,
                        "result_status": compliance_status(rr), "explanation": compliance_explanation(rr, compliance_status(rr))}
                       for rr in ev.results if rr.is_compliance],
        "rules": [{"rule_code": rr.code, "applicable": rr.applicable, "findings": len(rr.findings), "error": rr.error} for rr in ev.results],
        "score": None if not ev.score else {
            "total": ev.score.total, "editorial_status": ev.score.editorial_status, "coverage": ev.score.coverage,
            "criteria": [{"code": c.code, "name": c.name, "weight": c.weight, "status": c.status, "score": c.score} for c in ev.score.criteria],
        },
        "rubric": f"{rubric.name} v{rubric.version}" if rubric else None,
        "findings_total": len(findings),
        "findings": findings[:300],
    }
    if rs.status == "draft":
        runs = (rs.test_results_json or {}).get("runs", [])
        runs.append({"at": datetime.now(UTC).isoformat(), "by": str(principal.id), "file": filename, "manuscript_type": manuscript_type,
                     "isbn_status": ev.isbn_status, "editorial_status": ev.score.editorial_status if ev.score else None,
                     "total": ev.score.total if ev.score else None, "findings": len(findings),
                     "errors": [r["rule_code"] for r in result["rules"] if r["error"]]})
        rs.test_results_json = {"runs": runs[-20:]}
    audit.record(db, "rule_set.simulated", "rule_set", actor_id=principal.id, entity_id=rs.id,
                 after={"file": filename, "manuscript_type": manuscript_type, "findings": len(findings)}, request=request)
    db.commit()
    return result


@router.post("/rule-sets/{rs_id}/publish", response_model=RuleSetOut)
def publish_rule_set(rs_id: uuid.UUID, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RuleSetOut:
    rs = db.get(RuleSet, rs_id)
    if rs is None:
        raise not_found("Rule set")
    if rs.status != "draft":
        raise AppError(409, "NOT_DRAFT", "Hanya draft yang dapat diterbitkan.")
    problems = []
    for item in rs.items:
        s = item.rule_snapshot_json
        if s["engine_key"] not in HANDLERS:
            problems.append(f"{s['rule_code']}: handler '{s['engine_key']}' tidak dikenal")
        if s["authority_type"] in OFFICIAL and not (s.get("source_title") and s.get("source_url")):
            problems.append(f"{s['rule_code']}: aturan resmi tanpa sumber")
        if s["severity"] not in SEVERITIES:
            problems.append(f"{s['rule_code']}: severity tidak valid")
    runs = (rs.test_results_json or {}).get("runs", [])
    if not runs:
        problems.append("Belum ada simulasi. Uji rule set pada minimal satu berkas contoh sebelum diterbitkan.")
    elif runs[-1].get("errors"):
        problems.append(f"Simulasi terakhir memiliki aturan gagal: {', '.join(runs[-1]['errors'])}")
    if problems:
        raise AppError(422, "PUBLISH_VALIDATION_FAILED", "Rule set belum dapat diterbitkan.", {"problems": problems})
    now = datetime.now(UTC)
    for old in db.scalars(select(RuleSet).where(RuleSet.status == "published")):
        old.status = "archived"
    rs.status, rs.published_at, rs.published_by = "published", now, principal.id
    audit.record(db, "rule_set.published", "rule_set", actor_id=principal.id, entity_id=rs.id,
                 after={"version": rs.version, "rules": len(rs.items), "change_notes": rs.change_notes}, request=request)
    db.commit()
    return _rs_out(db, rs)


# ---------------------------------------------------------------------------
# Rubrik
# ---------------------------------------------------------------------------


def _measured_criteria(db) -> set[str]:
    rs = db.scalar(select(RuleSet).where(RuleSet.status == "published").limit(1))
    return {(i.rule_snapshot_json.get("scoring_effect") or {}).get("criterion_code") for i in rs.items} if rs else set()


@router.get("/rubrics", response_model=list[RubricOut])
def list_rubrics(db: DB, _: Principal = require(Perm.RULE_READ), manuscript_type: str | None = None) -> list[RubricOut]:
    stmt = select(RubricVersion).order_by(RubricVersion.manuscript_type, RubricVersion.version.desc())
    if manuscript_type:
        stmt = stmt.where(RubricVersion.manuscript_type == manuscript_type)
    return [RubricOut.model_validate(r) for r in db.scalars(stmt)]


@router.post("/rubrics/{rubric_id}/new-version", response_model=RubricOut, status_code=status.HTTP_201_CREATED)
def new_rubric_version(rubric_id: uuid.UUID, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RubricOut:
    src = db.get(RubricVersion, rubric_id)
    if src is None:
        raise not_found("Rubrik")
    if db.scalar(select(RubricVersion.id).where(RubricVersion.manuscript_type == src.manuscript_type, RubricVersion.status == "draft").limit(1)):
        raise AppError(409, "DRAFT_EXISTS", "Sudah ada draft rubrik untuk jenis naskah ini.")
    last = db.scalar(select(func.max(RubricVersion.version)).where(RubricVersion.name == src.name, RubricVersion.manuscript_type == src.manuscript_type))
    rv = RubricVersion(name=src.name, version=last + 1, manuscript_type=src.manuscript_type, status="draft",
                       min_scoring_coverage=src.min_scoring_coverage, score_thresholds_json=src.score_thresholds_json, created_by=principal.id)
    for c in src.criteria:
        rv.criteria.append(RubricCriterion(criterion_code=c.criterion_code, name=c.name, description=c.description, weight_percent=c.weight_percent,
                                           scoring_method_key=c.scoring_method_key, config_json=c.config_json,
                                           required_for_scoring=c.required_for_scoring, sort_order=c.sort_order))
    db.add(rv)
    db.flush()
    audit.record(db, "rubric.created", "rubric", actor_id=principal.id, entity_id=rv.id,
                 after={"name": rv.name, "version": rv.version, "manuscript_type": rv.manuscript_type}, request=request)
    db.commit()
    db.refresh(rv)
    return RubricOut.model_validate(rv)


@router.patch("/rubrics/{rubric_id}", response_model=RubricOut)
def update_rubric(rubric_id: uuid.UUID, body: RubricUpdate, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RubricOut:
    rv = db.get(RubricVersion, rubric_id)
    if rv is None:
        raise not_found("Rubrik")
    if rv.status != "draft":
        raise AppError(409, "NOT_DRAFT", "Rubrik terbit tidak dapat diubah; buat versi baru.")
    before = {"criteria": {c.criterion_code: float(c.weight_percent) for c in rv.criteria}, "min_coverage": float(rv.min_scoring_coverage),
              "thresholds": rv.score_thresholds_json}
    if body.min_scoring_coverage is not None:
        rv.min_scoring_coverage = body.min_scoring_coverage
    if body.score_thresholds_json is not None:
        rv.score_thresholds_json = {**rv.score_thresholds_json, **body.score_thresholds_json}
    if body.change_notes is not None:
        rv.change_notes = body.change_notes
    if body.criteria is not None:
        by_code = {c.criterion_code: c for c in rv.criteria}
        for p in body.criteria:
            if p.criterion_code not in by_code:
                raise AppError(422, "UNKNOWN_CRITERION", f"Kriteria {p.criterion_code} tidak ada di rubrik ini.")
            by_code[p.criterion_code].weight_percent = p.weight_percent
            by_code[p.criterion_code].required_for_scoring = p.required_for_scoring
    db.flush()
    audit.record(db, "rubric.updated", "rubric", actor_id=principal.id, entity_id=rv.id, before=before,
                 after={"criteria": {c.criterion_code: float(c.weight_percent) for c in rv.criteria},
                        "min_coverage": float(rv.min_scoring_coverage), "thresholds": rv.score_thresholds_json}, request=request)
    db.commit()
    db.refresh(rv)
    return RubricOut.model_validate(rv)


@router.delete("/rubrics/{rubric_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rubric(rubric_id: uuid.UUID, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> None:
    rv = db.get(RubricVersion, rubric_id)
    if rv is None:
        raise not_found("Rubrik")
    if rv.status != "draft":
        raise AppError(409, "NOT_DRAFT", "Hanya draft yang dapat dihapus.")
    audit.record(db, "rubric.deleted", "rubric", actor_id=principal.id, entity_id=rv.id, before={"version": rv.version}, request=request)
    db.delete(rv)
    db.commit()


@router.post("/rubrics/{rubric_id}/publish", response_model=RubricOut)
def publish_rubric(rubric_id: uuid.UUID, db: DB, request: Request, principal: Principal = require(Perm.RULE_MANAGE)) -> RubricOut:
    rv = db.get(RubricVersion, rubric_id)
    if rv is None:
        raise not_found("Rubrik")
    if rv.status != "draft":
        raise AppError(409, "NOT_DRAFT", "Hanya draft yang dapat diterbitkan.")
    problems = []
    total = sum(Decimal(c.weight_percent) for c in rv.criteria)
    if abs(total - Decimal(100)) > Decimal("0.01"):
        problems.append(f"Total bobot {total}%, harus 100%.")
    measured = _measured_criteria(db)
    for c in rv.criteria:
        if c.weight_percent > 0 and c.criterion_code not in measured:
            problems.append(f"Kriteria {c.criterion_code} tidak diukur oleh aturan mana pun di rule set terbit.")
    t = rv.score_thresholds_json or {}
    if not (float(t.get("pass", 85)) > float(t.get("minor_revision", 70)) > float(t.get("major_revision", 55))):
        problems.append("Ambang harus berurutan: lulus > revisi ringan > revisi besar.")
    if problems:
        raise AppError(422, "PUBLISH_VALIDATION_FAILED", "Rubrik belum dapat diterbitkan.", {"problems": problems})
    for old in db.scalars(select(RubricVersion).where(RubricVersion.manuscript_type == rv.manuscript_type, RubricVersion.status == "published")):
        old.status = "archived"
    rv.status, rv.published_at, rv.published_by = "published", datetime.now(UTC), principal.id
    audit.record(db, "rubric.published", "rubric", actor_id=principal.id, entity_id=rv.id,
                 after={"name": rv.name, "version": rv.version, "manuscript_type": rv.manuscript_type,
                        "weights": {c.criterion_code: float(c.weight_percent) for c in rv.criteria}}, request=request)
    db.commit()
    db.refresh(rv)
    return RubricOut.model_validate(rv)
