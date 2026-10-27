"""Query baca untuk ringkasan screening terbaru per naskah (dipakai daftar naskah & dashboard)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScreeningRun


def latest_runs(db: Session, manuscript_ids: list[uuid.UUID], scope: str | None = None) -> dict[uuid.UUID, dict[str, Any]]:
    """Screening terbaru per naskah; `scope` isbn/layout menyertakan run lama berlingkup full."""
    if not manuscript_ids:
        return {}
    stmt = select(ScreeningRun).where(ScreeningRun.manuscript_id.in_(manuscript_ids))
    if scope:
        stmt = stmt.where(ScreeningRun.scope.in_((scope, "full")))
    rows = db.scalars(
        stmt
        .order_by(ScreeningRun.manuscript_id, ScreeningRun.queued_at.desc())
        .distinct(ScreeningRun.manuscript_id)
    ).all()
    return {r.manuscript_id: brief(r) for r in rows}


def brief(r: ScreeningRun) -> dict[str, Any]:
    summary = r.result_summary_json or {}
    return {
        "id": str(r.id),
        "scope": r.scope,
        "status": r.status,
        "isbn_status": r.isbn_status,
        "editorial_status": r.editorial_status,
        "total_score": float(r.total_score) if r.total_score is not None else None,
        "findings_total": summary.get("findings_total"),
        "by_severity": summary.get("by_severity", {}),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }
