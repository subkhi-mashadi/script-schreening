"""Agregat dashboard, selalu dibatasi pada naskah yang boleh dilihat pengguna."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, Principal
from app.api.routes.manuscripts import incomplete_fields
from app.core.config import get_settings
from app.core.permissions import Perm
from app.models import AuditLog, DocumentVersion, Finding, Manuscript, ScreeningRun, User
from app.screening.queries import latest_runs

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DAYS = 14
ATTENTION_LIMIT = 8
HIDDEN_EVENTS = ("access.denied", "audit.searched")


def _scope(principal: Principal) -> Select | None:
    """Subquery ID naskah dalam cakupan; None bila pengguna tidak punya akses naskah."""
    stmt = select(Manuscript.id)
    if principal.can(Perm.MANUSCRIPT_READ_ALL):
        return stmt
    if principal.can(Perm.MANUSCRIPT_READ_SCOPED):
        return stmt.where(or_(Manuscript.created_by == principal.id, Manuscript.assigned_editor_id == principal.id))
    return None


def _empty() -> dict:
    return {
        "has_access": False,
        "kpi": {"manuscripts": 0, "received_30d": 0, "received_prev_30d": 0, "versions": 0, "ready": 0,
                "needs_attention": 0, "avg_quality": None, "pages": 0},
        "by_extraction_status": {}, "no_version": 0, "by_type": {}, "uploads_daily": [], "by_isbn_status": {},
        "by_editorial_status": {}, "score_buckets": [], "not_screened": 0, "top_rules": [], "awaiting_decision": 0, "by_decision": {},
        "attention": [], "recent": [], "activity": [],
    }


@router.get("")
def dashboard(db: DB, principal: CurrentUser) -> dict:
    scope = _scope(principal)
    if scope is None:
        return _empty()
    ids = scope.subquery()
    in_scope = Manuscript.id.in_(select(ids.c.id))
    now = datetime.now(UTC)

    latest_vn = (
        select(DocumentVersion.manuscript_id, func.max(DocumentVersion.version_number).label("vn"))
        .where(DocumentVersion.manuscript_id.in_(select(ids.c.id)))
        .group_by(DocumentVersion.manuscript_id)
        .subquery()
    )
    latest = (
        select(DocumentVersion)
        .join(latest_vn, and_(DocumentVersion.manuscript_id == latest_vn.c.manuscript_id,
                              DocumentVersion.version_number == latest_vn.c.vn))
        .subquery()
    )

    total = db.scalar(select(func.count()).select_from(ids))
    received_30d = db.scalar(select(func.count()).where(in_scope, Manuscript.created_at >= now - timedelta(days=30)))
    received_prev = db.scalar(
        select(func.count()).where(in_scope, Manuscript.created_at >= now - timedelta(days=60),
                                   Manuscript.created_at < now - timedelta(days=30))
    )
    versions = db.scalar(select(func.count()).where(DocumentVersion.manuscript_id.in_(select(ids.c.id))))
    by_status = dict(db.execute(select(latest.c.extraction_status, func.count()).group_by(latest.c.extraction_status)).all())
    avg_quality = db.scalar(select(func.avg(latest.c.extraction_quality)).where(latest.c.extraction_status.in_(("EXTRACTED", "INCOMPLETE"))))
    pages = db.scalar(
        select(func.coalesce(func.sum(latest.c.extraction_summary_json["page_count"].as_integer()), 0))
        .where(latest.c.extraction_status.in_(("EXTRACTED", "INCOMPLETE")))
    )
    by_type = dict(db.execute(select(Manuscript.manuscript_type, func.count()).where(in_scope).group_by(Manuscript.manuscript_type)).all())

    tz = get_settings().display_timezone
    day = func.date(func.timezone(tz, DocumentVersion.uploaded_at))
    daily_rows = dict(
        db.execute(
            select(day, func.count())
            .where(DocumentVersion.manuscript_id.in_(select(ids.c.id)), DocumentVersion.uploaded_at >= now - timedelta(days=DAYS + 1))
            .group_by(day)
        ).all()
    )
    today = now.astimezone(ZoneInfo(tz)).date()
    uploads_daily = [
        {"date": (today - timedelta(days=i)).isoformat(), "count": daily_rows.get(today - timedelta(days=i), 0)}
        for i in range(DAYS - 1, -1, -1)
    ]

    no_version = total - sum(by_status.values())

    # Naskah yang perlu tindakan: berkas belum ada, ekstraksi gagal/tidak lengkap, atau metadata kosong.
    candidates = db.scalars(
        select(Manuscript)
        .where(in_scope)
        .options(selectinload(Manuscript.versions), selectinload(Manuscript.authors), selectinload(Manuscript.assigned_editor))
        .order_by(Manuscript.created_at.desc())
        .limit(200)
    ).all()
    runs_map = latest_runs(db, [m.id for m in candidates], "isbn")
    layout_map = latest_runs(db, [m.id for m in candidates], "layout")
    attention, needs_attention = [], 0
    for m in candidates:
        lv = m.versions[-1] if m.versions else None
        reasons = []
        if lv is None:
            reasons.append("NO_VERSION")
        elif lv.extraction_status in ("FAILED", "INCOMPLETE"):
            reasons.append(f"EXTRACTION_{lv.extraction_status}")
        missing = incomplete_fields(m)
        if missing:
            reasons.append("INCOMPLETE_METADATA")
        run = runs_map.get(m.id)
        if run and run["isbn_status"] == "FAIL":
            reasons.append("ISBN_FAIL")
        lay = layout_map.get(m.id)
        if lay and lay["editorial_status"] in ("MAJOR_REVISION", "SUBSTANTIAL_REWORK"):
            reasons.append("EDITORIAL_REVISION")
        if reasons:
            needs_attention += 1
            if len(attention) < ATTENTION_LIMIT:
                attention.append(_row(m, lv) | {"reasons": reasons, "missing_fields": missing})

    recent = [_row(m, m.versions[-1] if m.versions else None) for m in candidates[:6]]

    activity_rows = db.execute(
        select(AuditLog, User.full_name, Manuscript.working_title)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .join(Manuscript, Manuscript.id == AuditLog.manuscript_id)
        .where(AuditLog.manuscript_id.in_(select(ids.c.id)), AuditLog.event_type.notin_(HIDDEN_EVENTS))
        .order_by(AuditLog.created_at.desc())
        .limit(6)
    ).all()
    activity = [
        {"id": str(a.id), "event_type": a.event_type, "actor_name": name, "manuscript_id": str(a.manuscript_id),
         "manuscript_title": title, "created_at": a.created_at.isoformat(), "after": a.after_json}
        for a, name, title in activity_rows
    ]

    # Screening terbaru per naskah dalam cakupan.
    def latest_of(scope: str):
        return (
            select(ScreeningRun)
            .where(ScreeningRun.manuscript_id.in_(select(ids.c.id)), ScreeningRun.scope.in_((scope, "full")))
            .order_by(ScreeningRun.manuscript_id, ScreeningRun.queued_at.desc())
            .distinct(ScreeningRun.manuscript_id)
            .subquery()
        )

    latest_run = latest_of("isbn")
    latest_layout = latest_of("layout")
    awaiting_decision = db.scalar(
        select(func.count()).select_from(latest_run).where(latest_run.c.status.in_(("COMPLETED", "INCOMPLETE")), latest_run.c.final_decision.is_(None))
    )
    by_decision = dict(db.execute(select(latest_run.c.final_decision, func.count()).where(latest_run.c.final_decision.is_not(None))
                                  .group_by(latest_run.c.final_decision)).all())
    by_isbn = dict(db.execute(select(latest_run.c.isbn_status, func.count()).group_by(latest_run.c.isbn_status)).all())
    by_editorial = dict(db.execute(select(latest_layout.c.editorial_status, func.count()).group_by(latest_layout.c.editorial_status)).all())
    scores = [float(x) for x in db.scalars(select(latest_layout.c.total_score).where(latest_layout.c.total_score.is_not(None)))]
    buckets = [("< 55", 0, 55), ("55–69", 55, 70), ("70–84", 70, 85), ("85–100", 85, 101)]
    score_buckets = [{"label": lbl, "count": sum(1 for x in scores if lo <= x < hi)} for lbl, lo, hi in buckets]
    screened = sum(by_isbn.values())
    top_rules = [
        {"rule_code": code, "title": title, "count": n}
        for code, title, n in db.execute(
            select(Finding.rule_code, func.min(Finding.machine_result_json["rule_title"].astext), func.count())
            .where(Finding.screening_run_id.in_(select(latest_layout.c.id)), Finding.verification_status != "FALSE_POSITIVE")
            .group_by(Finding.rule_code)
            .order_by(func.count().desc())
            .limit(6)
        ).all()
    ]
    for row in attention + recent:
        row["screening"] = runs_map.get(uuid.UUID(row["id"]))
        row["layout"] = layout_map.get(uuid.UUID(row["id"]))
    layout_done = sum(by_editorial.values())

    return {
        "has_access": True,
        "generated_at": now.isoformat(),
        "kpi": {
            "manuscripts": total,
            "received_30d": received_30d,
            "received_prev_30d": received_prev,
            "versions": versions,
            "ready": by_status.get("EXTRACTED", 0),
            "needs_attention": needs_attention,
            "avg_quality": round(float(avg_quality), 1) if avg_quality is not None else None,
            "pages": pages,
        },
        "by_extraction_status": by_status,
        "no_version": no_version,
        "by_type": by_type,
        "uploads_daily": uploads_daily,
        "attention": attention,
        "recent": recent,
        "by_isbn_status": by_isbn,
        "by_editorial_status": by_editorial,
        "score_buckets": score_buckets,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "not_screened": total - screened,
        "layout_checked": layout_done,
        "top_rules": top_rules,
        "awaiting_decision": awaiting_decision,
        "by_decision": by_decision,
        "activity": activity,
    }


def _row(m: Manuscript, lv: DocumentVersion | None) -> dict:
    summary = lv.extraction_summary_json if lv else {}
    return {
        "id": str(m.id),
        "internal_code": m.internal_code,
        "working_title": m.working_title,
        "manuscript_type": m.manuscript_type,
        "authors": [a.author_name for a in m.authors],
        "assigned_editor": m.assigned_editor.full_name if m.assigned_editor else None,
        "created_at": m.created_at.isoformat(),
        "latest_version": None if lv is None else {
            "version_number": lv.version_number,
            "extraction_status": lv.extraction_status,
            "extraction_quality": float(lv.extraction_quality) if lv.extraction_quality is not None else None,
            "page_count": summary.get("page_count"),
            "chapter_count": len(summary.get("chapters") or []),
            "uploaded_at": lv.uploaded_at.isoformat(),
        },
    }

