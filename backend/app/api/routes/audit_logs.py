import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Principal, load_manuscript, require
from app.core.config import get_settings
from app.core.permissions import Perm
from app.models import AuditLog, User
from app.schemas import AuditOut, Page
from app.services import audit

router = APIRouter(tags=["audit"])


def _page(db, stmt, page: int, page_size: int) -> Page[AuditOut]:
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.add_columns(User.full_name)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [AuditOut.model_validate(r[0]).model_copy(update={"actor_name": r[1]}) for r in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/audit-logs", response_model=Page[AuditOut])
def search_audit(
    db: DB,
    request: Request,
    principal: Principal = require(Perm.AUDIT_READ),
    event_type: str | None = Query(None, max_length=100),
    actor_user_id: uuid.UUID | None = None,
    manuscript_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[AuditOut]:
    stmt = select(AuditLog)
    if event_type:
        stmt = stmt.where(AuditLog.event_type.startswith(event_type, autoescape=True))
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if manuscript_id:
        stmt = stmt.where(AuditLog.manuscript_id == manuscript_id)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max, UTC))
    # Pembacaan audit juga diaudit (PRD §14.3).
    audit.record(db, "audit.searched", "audit_log", actor_id=principal.id, manuscript_id=manuscript_id,
                 after={"event_type": event_type, "page": page}, request=request)
    db.commit()
    return _page(db, stmt, page, page_size)


@router.get("/manuscripts/{manuscript_id}/history", response_model=Page[AuditOut])
def manuscript_history(
    manuscript_id: uuid.UUID,
    db: DB,
    principal: CurrentUser,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[AuditOut]:
    """Riwayat peristiwa untuk satu naskah, bagi pengguna yang berhak membaca naskah tersebut."""
    load_manuscript(db, principal, manuscript_id, request)
    stmt = select(AuditLog).where(AuditLog.manuscript_id == manuscript_id, AuditLog.event_type != "access.denied")
    return _page(db, stmt, page, page_size)


@router.get("/audit-logs/summary")
def audit_summary(db: DB, request: Request, principal: Principal = require(Perm.AUDIT_READ), days: int = Query(30, ge=1, le=365)) -> dict:
    """Ringkasan audit untuk dashboard: volume per hari, per kelompok peristiwa, penolakan akses, pelaku teraktif."""
    since = datetime.now(UTC) - timedelta(days=days)
    base = select(AuditLog).where(AuditLog.created_at >= since).subquery()
    group = func.split_part(base.c.event_type, ".", 1)
    day = func.date(func.timezone(get_settings().display_timezone, base.c.created_at))
    actors = db.execute(
        select(User.full_name, User.role, func.count())
        .join(base, base.c.actor_user_id == User.id)
        .group_by(User.full_name, User.role)
        .order_by(func.count().desc())
        .limit(6)
    ).all()
    audit.record(db, "audit.searched", "audit_log", actor_id=principal.id, after={"summary_days": days}, request=request)
    db.commit()
    return {
        "days": days,
        "total": db.scalar(select(func.count()).select_from(base)),
        "by_group": dict(db.execute(select(group, func.count()).group_by(group)).all()),
        "daily": [{"date": d.isoformat(), "count": n} for d, n in db.execute(select(day, func.count()).group_by(day).order_by(day)).all()],
        "denied": db.scalar(select(func.count()).select_from(base).where(base.c.event_type == "access.denied")),
        "login_failed": db.scalar(select(func.count()).select_from(base).where(base.c.event_type == "auth.login_failed")),
        "decisions": db.scalar(select(func.count()).select_from(base).where(base.c.event_type == "screening.decided")),
        "reviews": db.scalar(select(func.count()).select_from(base).where(base.c.event_type == "finding.reviewed")),
        "top_actors": [{"name": n, "role": r, "count": c} for n, r, c in actors],
    }
