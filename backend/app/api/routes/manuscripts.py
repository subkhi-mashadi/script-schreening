import uuid
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DB, CurrentUser, Principal, load_manuscript, require
from app.core.constants import DISTRIBUTION_OPTIONS, EXTRACTION_STATUS_LABELS, INTAKE_STATUSES, LANGUAGES, MANUSCRIPT_TYPES, REQUIRED_INTAKE_FIELDS
from app.core.errors import AppError
from app.core.permissions import Perm, Role
from app.models import DocumentVersion, Manuscript, ManuscriptAuthor, User
from app.schemas import (
    AuthorIn,
    ManuscriptCreate,
    ManuscriptListItem,
    ManuscriptOut,
    ManuscriptUpdate,
    Page,
    VersionBrief,
)
from app.screening.queries import latest_runs
from app.services import audit

router = APIRouter(prefix="/manuscripts", tags=["manuscripts"])


@router.get("/options")
def options(_: CurrentUser) -> dict:
    return {
        "manuscript_types": [{"value": k, "label": v} for k, v in MANUSCRIPT_TYPES.items()],
        "languages": [{"value": k, "label": v} for k, v in LANGUAGES.items()],
        "intake_statuses": list(INTAKE_STATUSES),
        "extraction_statuses": [{"value": k, "label": v} for k, v in EXTRACTION_STATUS_LABELS.items()],
        "distribution_options": [{"value": k, "label": v} for k, v in DISTRIBUTION_OPTIONS.items()],
    }


def incomplete_fields(m: Manuscript) -> list[str]:
    missing = []
    for f in REQUIRED_INTAKE_FIELDS:
        value = m.authors if f == "authors" else getattr(m, f)
        if not value:
            missing.append(f)
    return missing


def snapshot(m: Manuscript) -> dict:
    return {
        "working_title": m.working_title,
        "manuscript_type": m.manuscript_type,
        "language_code": m.language_code,
        "intake_status": m.intake_status,
        "submitted_at": m.submitted_at.isoformat() if m.submitted_at else None,
        "assigned_editor_id": str(m.assigned_editor_id) if m.assigned_editor_id else None,
        "authors": [{"name": a.author_name, "order": a.author_order, "affiliation": a.affiliation} for a in m.authors],
        "metadata": m.metadata_json,
    }


def _latest(m: Manuscript) -> VersionBrief | None:
    return VersionBrief.model_validate(m.versions[-1]) if m.versions else None


def to_list_item(m: Manuscript) -> ManuscriptListItem:
    item = ManuscriptListItem.model_validate(m)
    return item.model_copy(update={"latest_version": _latest(m), "incomplete_fields": incomplete_fields(m)})


def to_out(m: Manuscript) -> ManuscriptOut:
    item = ManuscriptOut.model_validate(m)
    return item.model_copy(update={"latest_version": _latest(m), "incomplete_fields": incomplete_fields(m)})


def _check_editor(db: Session, editor_id: uuid.UUID | None) -> None:
    if editor_id is None:
        return
    u = db.get(User, editor_id)
    if u is None or not u.is_active or u.role != Role.EDITOR.value:
        raise AppError(422, "INVALID_EDITOR", "Editor yang ditugaskan tidak ditemukan atau tidak aktif.")


def _set_authors(m: Manuscript, authors: list[AuthorIn]) -> None:
    m.authors.clear()
    for i, a in enumerate(authors, start=1):
        m.authors.append(
            ManuscriptAuthor(author_name=a.author_name.strip(), author_order=i, author_email=a.author_email, affiliation=a.affiliation)
        )


def next_code(db: Session) -> str:
    n = db.scalar(text("SELECT nextval('manuscript_code_seq')"))
    return f"NSK-{datetime.now(UTC).year}-{n:06d}"


@router.post("", response_model=ManuscriptOut, status_code=status.HTTP_201_CREATED)
def create_manuscript(body: ManuscriptCreate, db: DB, request: Request, principal: Principal = require(Perm.MANUSCRIPT_CREATE)) -> ManuscriptOut:
    _check_editor(db, body.assigned_editor_id)
    m = Manuscript(
        internal_code=next_code(db),
        working_title=body.working_title.strip(),
        manuscript_type=body.manuscript_type,
        language_code=body.language_code,
        submitted_at=body.submitted_at,
        created_by=principal.id,
        assigned_editor_id=body.assigned_editor_id,
        metadata_json=body.metadata,
    )
    _set_authors(m, body.authors)
    db.add(m)
    db.flush()
    audit.record(db, "manuscript.created", "manuscript", actor_id=principal.id, entity_id=m.id, manuscript_id=m.id,
                 after=snapshot(m), request=request)
    db.commit()
    db.refresh(m)
    return to_out(m)


@router.get("", response_model=Page[ManuscriptListItem])
def list_manuscripts(
    db: DB,
    principal: CurrentUser,
    q: str | None = Query(None, max_length=200),
    manuscript_type: str | None = None,
    intake_status: str | None = None,
    assigned_editor_id: uuid.UUID | None = None,
    extraction_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Page[ManuscriptListItem]:
    stmt = select(Manuscript)
    if not principal.can(Perm.MANUSCRIPT_READ_ALL):
        if not principal.can(Perm.MANUSCRIPT_READ_SCOPED):
            return Page(items=[], total=0, page=page, page_size=page_size)
        stmt = stmt.where(or_(Manuscript.created_by == principal.id, Manuscript.assigned_editor_id == principal.id))
    if q:
        like = f"%{q}%"
        author_match = exists().where(ManuscriptAuthor.manuscript_id == Manuscript.id, ManuscriptAuthor.author_name.ilike(like))
        stmt = stmt.where(or_(Manuscript.working_title.ilike(like), Manuscript.internal_code.ilike(like), author_match))
    if manuscript_type:
        stmt = stmt.where(Manuscript.manuscript_type == manuscript_type)
    if intake_status:
        stmt = stmt.where(Manuscript.intake_status == intake_status)
    if assigned_editor_id:
        stmt = stmt.where(Manuscript.assigned_editor_id == assigned_editor_id)
    if date_from:
        stmt = stmt.where(Manuscript.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        stmt = stmt.where(Manuscript.created_at <= datetime.combine(date_to, time.max, UTC))
    if extraction_status:
        latest = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.manuscript_id == Manuscript.id)
            .correlate(Manuscript)
            .scalar_subquery()
        )
        stmt = stmt.where(
            exists().where(
                DocumentVersion.manuscript_id == Manuscript.id,
                DocumentVersion.version_number == latest,
                DocumentVersion.extraction_status == extraction_status,
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.options(selectinload(Manuscript.authors), selectinload(Manuscript.versions), selectinload(Manuscript.assigned_editor))
        .order_by(Manuscript.created_at.desc(), Manuscript.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    ids = [m.id for m in rows]
    isbn, layout = latest_runs(db, ids, "isbn"), latest_runs(db, ids, "layout")
    items = [to_list_item(m).model_copy(update={"latest_screening": isbn.get(m.id), "latest_layout": layout.get(m.id)}) for m in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats")
def stats(db: DB, principal: CurrentUser) -> dict:
    """Ringkasan dashboard sesuai cakupan akses pengguna."""
    scope = select(Manuscript.id)
    if not principal.can(Perm.MANUSCRIPT_READ_ALL):
        if not principal.can(Perm.MANUSCRIPT_READ_SCOPED):
            return {"manuscripts": 0, "by_extraction_status": {}, "no_version": 0, "incomplete_metadata": None}
        scope = scope.where(or_(Manuscript.created_by == principal.id, Manuscript.assigned_editor_id == principal.id))
    ids = scope.subquery()
    total = db.scalar(select(func.count()).select_from(ids))
    latest = (
        select(DocumentVersion.manuscript_id, func.max(DocumentVersion.version_number).label("vn"))
        .where(DocumentVersion.manuscript_id.in_(select(ids.c.id)))
        .group_by(DocumentVersion.manuscript_id)
        .subquery()
    )
    rows = db.execute(
        select(DocumentVersion.extraction_status, func.count())
        .join(latest, (DocumentVersion.manuscript_id == latest.c.manuscript_id) & (DocumentVersion.version_number == latest.c.vn))
        .group_by(DocumentVersion.extraction_status)
    ).all()
    by_status = {s: c for s, c in rows}
    return {
        "manuscripts": total,
        "by_extraction_status": by_status,
        "no_version": total - sum(by_status.values()),
    }


@router.get("/{manuscript_id}", response_model=ManuscriptOut)
def get_manuscript(manuscript_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> ManuscriptOut:
    m = load_manuscript(db, principal, manuscript_id, request)
    return to_out(m).model_copy(update={"latest_screening": latest_runs(db, [m.id], "isbn").get(m.id),
                                        "latest_layout": latest_runs(db, [m.id], "layout").get(m.id)})


@router.patch("/{manuscript_id}", response_model=ManuscriptOut)
def update_manuscript(
    manuscript_id: uuid.UUID, body: ManuscriptUpdate, db: DB, request: Request, principal: Principal = require(Perm.MANUSCRIPT_UPDATE)
) -> ManuscriptOut:
    m = load_manuscript(db, principal, manuscript_id, request)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return to_out(m)
    before = snapshot(m)
    if "intake_status" in changes and body.intake_status not in INTAKE_STATUSES:
        raise AppError(422, "INVALID_STATUS", "Status penerimaan tidak dikenal.")
    if "assigned_editor_id" in changes:
        _check_editor(db, body.assigned_editor_id)
    type_manual = bool(changes.get("manuscript_type")) and changes["manuscript_type"] != m.manuscript_type
    for field in ("working_title", "manuscript_type", "language_code", "intake_status"):
        if field in changes:
            if changes[field] is None:
                raise AppError(422, "REQUIRED_FIELD", f"Kolom {field} tidak boleh dikosongkan.")
            setattr(m, field, changes[field].strip() if field == "working_title" else changes[field])
    if "submitted_at" in changes:
        m.submitted_at = body.submitted_at
    if "assigned_editor_id" in changes:
        m.assigned_editor_id = body.assigned_editor_id
    if "metadata" in changes:
        m.metadata_json = body.metadata or {}
    if type_manual:
        # Jenis dipilih manual: klasifikasi otomatis tidak lagi menimpanya.
        m.metadata_json = {**(m.metadata_json or {}), "type_source": "manual"}
    if "authors" in changes:
        _set_authors(m, body.authors or [])
    db.flush()
    after = snapshot(m)
    if after != before:
        audit.record(db, "manuscript.updated", "manuscript", actor_id=principal.id, entity_id=m.id, manuscript_id=m.id,
                     before=before, after=after, request=request)
    db.commit()
    db.refresh(m)
    return to_out(m)
