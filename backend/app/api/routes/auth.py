from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.permissions import permissions_for
from app.core.security import DUMMY_HASH, create_access_token, session_expiry, verify_password
from app.models import AuditLog, User, UserSession
from app.schemas import LoginIn, MeOut, TokenOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "Email atau kata sandi salah."


def me_out(user: User) -> MeOut:
    return MeOut.model_validate(user).model_copy(update={"permissions": permissions_for(user.role)})


def _recent_failures(db, email: str) -> int:
    s = get_settings()
    since = datetime.now(UTC) - timedelta(minutes=s.login_window_minutes)
    return db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.event_type == "auth.login_failed",
            AuditLog.created_at >= since,
            AuditLog.after_json["email"].astext == email,
        )
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB, request: Request) -> TokenOut:
    email = body.email.lower()
    if _recent_failures(db, email) >= get_settings().login_max_failures:
        audit.record(db, "auth.login_throttled", "user", after={"email": email}, request=request)
        db.commit()
        raise AppError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "TOO_MANY_ATTEMPTS",
            f"Terlalu banyak percobaan login gagal. Coba lagi dalam {get_settings().login_window_minutes} menit.",
        )

    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit.record(
            db,
            "auth.login_failed",
            "user",
            actor_id=user.id if user else None,
            entity_id=user.id if user else None,
            after={"email": email, "reason": "inactive" if user and ok else "invalid_credentials"},
            request=request,
        )
        db.commit()
        raise AppError(status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", INVALID_LOGIN)

    expires = session_expiry()
    ip, ua = audit.client_info(request)
    sess = UserSession(user_id=user.id, expires_at=expires, ip_address=ip, user_agent=ua)
    db.add(sess)
    db.flush()
    audit.record(db, "auth.login", "user", actor_id=user.id, entity_id=user.id, request=request)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, sess.id, expires), expires_at=expires, user=me_out(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: CurrentUser, db: DB, request: Request) -> None:
    principal.session.revoked_at = datetime.now(UTC)
    audit.record(db, "auth.logout", "user", actor_id=principal.id, entity_id=principal.id, request=request)
    db.commit()


@router.get("/me", response_model=MeOut)
def me(principal: CurrentUser) -> MeOut:
    return me_out(principal.user)
