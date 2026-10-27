import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, Principal, require
from app.core.errors import AppError, not_found
from app.core.permissions import ROLE_LABELS, Perm, Role
from app.core.security import hash_password
from app.models import User, UserSession
from app.schemas import Page, UserBrief, UserCreate, UserOut, UserUpdate
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])


def _snapshot(u: User) -> dict:
    return {"full_name": u.full_name, "email": u.email, "role": u.role, "is_active": u.is_active}


@router.get("/roles")
def roles() -> list[dict]:
    return [{"value": r.value, "label": ROLE_LABELS[r]} for r in Role]


@router.get("", response_model=Page[UserOut])
def list_users(
    db: DB,
    _: Principal = require(Perm.USER_MANAGE),
    q: str | None = None,
    role: Role | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[UserOut]:
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(User.full_name.ilike(like) | User.email.ilike(like))
    if role:
        stmt = stmt.where(User.role == role.value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.full_name).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[UserOut.model_validate(u) for u in rows], total=total, page=page, page_size=page_size)


@router.get("/editors", response_model=list[UserBrief])
def list_editors(db: DB, _: Principal = require(Perm.MANUSCRIPT_UPDATE)) -> list[UserBrief]:
    """Daftar editor aktif untuk penugasan naskah."""
    rows = db.scalars(select(User).where(User.role == Role.EDITOR.value, User.is_active).order_by(User.full_name)).all()
    return [UserBrief.model_validate(u) for u in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: DB, request: Request, principal: Principal = require(Perm.USER_MANAGE)) -> UserOut:
    user = User(full_name=body.full_name, email=body.email.lower(), role=body.role.value, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError(status.HTTP_409_CONFLICT, "EMAIL_EXISTS", "Email sudah terdaftar.") from None
    audit.record(db, "user.created", "user", actor_id=principal.id, entity_id=user.id, after=_snapshot(user), request=request)
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, body: UserUpdate, db: DB, request: Request, principal: Principal = require(Perm.USER_MANAGE)
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("Pengguna")
    if user.id == principal.id and (body.is_active is False or (body.role and body.role.value != user.role)):
        raise AppError(status.HTTP_409_CONFLICT, "SELF_LOCKOUT", "Tidak dapat menonaktifkan atau mengubah peran akun sendiri.")
    before = _snapshot(user)
    changes = body.model_dump(exclude_unset=True)
    if "full_name" in changes:
        user.full_name = body.full_name
    if "role" in changes and body.role:
        user.role = body.role.value
    if "is_active" in changes and body.is_active is not None:
        user.is_active = body.is_active
    password_changed = bool(body.password)
    if password_changed:
        user.password_hash = hash_password(body.password)
    # Cabut sesi aktif bila akses berubah.
    if password_changed or user.is_active is False or user.role != before["role"]:
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    after = _snapshot(user) | ({"password_changed": True} if password_changed else {})
    audit.record(db, "user.updated", "user", actor_id=principal.id, entity_id=user.id, before=before, after=after, request=request)
    db.commit()
    return UserOut.model_validate(user)
