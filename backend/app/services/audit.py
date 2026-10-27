"""Pencatatan audit (FR-13). Audit log append-only; isi naskah tidak pernah dicatat."""

import ipaddress
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def client_info(request: Request | None) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip = request.client.host if request.client else None
    if ip and not _is_ip(ip):
        ip = None
    ua = request.headers.get("user-agent")
    return ip, ua[:500] if ua else None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def record(
    db: Session,
    event_type: str,
    entity_type: str,
    *,
    actor_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    manuscript_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    ip, ua = client_info(request)
    entry = AuditLog(
        actor_user_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        manuscript_id=manuscript_id,
        before_json=before,
        after_json=after,
        ip_address=ip,
        user_agent=ua,
    )
    db.add(entry)
    return entry
