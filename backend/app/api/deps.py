import uuid
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import forbidden, not_found, unauthorized
from app.core.permissions import Perm, has_perm
from app.core.security import decode_access_token
from app.models import Manuscript, User, UserSession
from app.services import audit

DB = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)


class Principal:
    def __init__(self, user: User, session: UserSession) -> None:
        self.user = user
        self.session = session

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    def can(self, perm: Perm) -> bool:
        return has_perm(self.user.role, perm)


def get_principal(db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized("Login diperlukan.")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
        session_id = uuid.UUID(payload["sid"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise unauthorized() from None
    sess = db.get(UserSession, session_id)
    now = datetime.now(UTC)
    if sess is None or sess.user_id != user_id or sess.revoked_at is not None or sess.expires_at <= now:
        raise unauthorized()
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("Akun tidak aktif.")
    return Principal(user, sess)


CurrentUser = Annotated[Principal, Depends(get_principal)]


def deny(db: Session, principal: Principal, request: Request | None, reason: str, **ctx) -> None:
    """Catat penolakan akses pada audit log (transaksi terpisah dari operasi yang ditolak)."""
    db.rollback()
    audit.record(
        db,
        "access.denied",
        ctx.pop("entity_type", "endpoint"),
        actor_id=principal.id,
        entity_id=ctx.pop("entity_id", None),
        manuscript_id=ctx.pop("manuscript_id", None),
        after={"reason": reason, "path": request.url.path if request else None, "method": request.method if request else None, **ctx},
        request=request,
    )
    db.commit()


def require(perm: Perm):
    def dependency(principal: CurrentUser, db: DB, request: Request) -> Principal:
        if not principal.can(perm):
            deny(db, principal, request, f"missing_permission:{perm.value}")
            raise forbidden()
        return principal

    return Depends(dependency)


def can_access_manuscript(principal: Principal, m: Manuscript) -> bool:
    if principal.can(Perm.MANUSCRIPT_READ_ALL):
        return True
    if principal.can(Perm.MANUSCRIPT_READ_SCOPED):
        return m.created_by == principal.id or m.assigned_editor_id == principal.id
    return False


def load_manuscript(db: Session, principal: Principal, manuscript_id: uuid.UUID, request: Request | None) -> Manuscript:
    """Naskah di luar cakupan dilaporkan sebagai 404 agar keberadaannya tidak bocor."""
    m = db.get(Manuscript, manuscript_id)
    if m is None:
        raise not_found("Naskah")
    if not can_access_manuscript(principal, m):
        deny(db, principal, request, "manuscript_out_of_scope", entity_type="manuscript", entity_id=m.id, manuscript_id=m.id)
        raise not_found("Naskah")
    return m
