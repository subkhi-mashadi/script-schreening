import uuid
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, Header, Query, Request, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser, Principal, load_manuscript, require
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.permissions import Perm
from app.models import DocumentSection, DocumentVersion, Manuscript
from app.reader.model import PATH_SEPARATOR
from app.schemas import Page, SectionOut, VersionBrief, VersionOut
from app.services import audit, extraction, storage
from app.services.file_validation import FileRejected, ValidatedFile, safe_filename, validate_upload

router = APIRouter(tags=["versions"])

CHUNK = 1024 * 1024


def version_out(v: DocumentVersion, warnings: list[str] | None = None) -> VersionOut:
    out = VersionOut.model_validate(v)
    return out.model_copy(update={"warnings": warnings or []})


def _load_version(db, principal: Principal, version_id: uuid.UUID, request: Request) -> DocumentVersion:
    v = db.get(DocumentVersion, version_id)
    if v is None:
        raise not_found("Versi dokumen")
    load_manuscript(db, principal, v.manuscript_id, request)
    return v


async def read_limited(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    buf = bytearray()
    while chunk := await file.read(CHUNK):
        buf.extend(chunk)
        if len(buf) > limit:
            raise AppError(413, "FILE_TOO_LARGE", f"Ukuran berkas melebihi batas {get_settings().max_upload_mb} MB.")
    return bytes(buf)


def store_new_version(
    db, manuscript_id: uuid.UUID, filename: str, vf: ValidatedFile, data: bytes, principal: Principal,
    request: Request, idempotency_key: str | None = None,
) -> tuple[DocumentVersion, list[str]]:
    """Simpan berkas immutable + baris document_versions + audit, lalu commit."""
    checksum = storage.sha256_hex(data)
    # Kunci baris naskah agar nomor versi berurutan walau unggah bersamaan.
    db.execute(select(Manuscript.id).where(Manuscript.id == manuscript_id).with_for_update())
    previous = db.scalar(
        select(DocumentVersion).where(DocumentVersion.manuscript_id == manuscript_id).order_by(DocumentVersion.version_number.desc()).limit(1)
    )
    number = (previous.version_number + 1) if previous else 1
    warnings: list[str] = []
    duplicate = db.scalar(
        select(DocumentVersion.version_number).where(
            DocumentVersion.manuscript_id == manuscript_id, DocumentVersion.sha256_checksum == checksum
        ).limit(1)
    )
    if duplicate:
        warnings.append(f"DUPLICATE_OF_VERSION_{duplicate}")

    key = storage.build_key(manuscript_id, number, checksum, vf.extension)
    storage.put_immutable(key, data)
    v = DocumentVersion(
        manuscript_id=manuscript_id,
        version_number=number,
        original_filename=filename,
        storage_key=key,
        mime_type=vf.mime_type,
        source_format=vf.source_format,
        file_size_bytes=len(data),
        sha256_checksum=checksum,
        uploaded_by=principal.id,
        supersedes_version_id=previous.id if previous else None,
        idempotency_key=idempotency_key,
    )
    db.add(v)
    try:
        db.flush()
        audit.record(
            db, "version.uploaded", "document_version", actor_id=principal.id, entity_id=v.id, manuscript_id=manuscript_id,
            after={"version_number": number, "filename": filename, "sha256": checksum, "size": len(data),
                   "format": vf.source_format, "supersedes": str(previous.id) if previous else None},
            request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        storage.remove_orphan(key)
        raise AppError(409, "VERSION_CONFLICT", "Versi bentrok dengan unggahan lain. Silakan ulangi.") from None
    except Exception:
        db.rollback()
        storage.remove_orphan(key)
        raise
    db.refresh(v)
    return v, warnings


@router.post("/manuscripts/{manuscript_id}/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def upload_version(
    manuscript_id: uuid.UUID,
    db: DB,
    request: Request,
    background: BackgroundTasks,
    response: Response,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=100),
    principal: Principal = require(Perm.VERSION_UPLOAD),
) -> VersionOut:
    load_manuscript(db, principal, manuscript_id, request)

    if idempotency_key:
        existing = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.manuscript_id == manuscript_id, DocumentVersion.idempotency_key == idempotency_key
            )
        )
        if existing:
            response.status_code = status.HTTP_200_OK
            return version_out(existing, ["IDEMPOTENT_REPLAY"])

    filename = safe_filename(file.filename)
    data = await read_limited(file)
    try:
        vf = validate_upload(filename, data)
    except FileRejected as exc:
        audit.record(db, "version.upload_rejected", "manuscript", actor_id=principal.id, entity_id=manuscript_id,
                     manuscript_id=manuscript_id, after={"code": exc.code, "filename": filename, "size": len(data)}, request=request)
        db.commit()
        raise AppError(422, exc.code, exc.message) from None

    v, warnings = store_new_version(db, manuscript_id, filename, vf, data, principal, request, idempotency_key)
    if get_settings().extract_on_upload:
        background.add_task(extraction.run_extraction, v.id)
    return version_out(v, warnings)


@router.get("/manuscripts/{manuscript_id}/versions", response_model=list[VersionBrief])
def list_versions(manuscript_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> list[VersionBrief]:
    m = load_manuscript(db, principal, manuscript_id, request)
    return [VersionBrief.model_validate(v) for v in m.versions]


@router.get("/versions/{version_id}", response_model=VersionOut)
def get_version(version_id: uuid.UUID, db: DB, principal: CurrentUser, request: Request) -> VersionOut:
    return version_out(_load_version(db, principal, version_id, request))


@router.get("/versions/{version_id}/sections", response_model=Page[SectionOut])
def list_sections(
    version_id: uuid.UUID,
    db: DB,
    principal: CurrentUser,
    request: Request,
    section_type: str | None = None,
    page_number: int | None = Query(None, ge=1),
    section_path: str | None = Query(None, max_length=2000),
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> Page[SectionOut]:
    _load_version(db, principal, version_id, request)
    stmt = select(DocumentSection).where(DocumentSection.document_version_id == version_id)
    if section_type:
        stmt = stmt.where(DocumentSection.section_type == section_type)
    if page_number:
        stmt = stmt.where(DocumentSection.page_number == page_number)
    if section_path:
        # Bagian beserta subbagiannya; "BAB I" tidak boleh ikut mencocokkan "BAB II".
        stmt = stmt.where(
            or_(
                DocumentSection.section_path == section_path,
                DocumentSection.section_path.startswith(section_path + PATH_SEPARATOR, autoescape=True),
            )
        )
    if q:
        stmt = stmt.where(DocumentSection.text_content.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(DocumentSection.paragraph_index).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[SectionOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/versions/{version_id}/download")
def download_version(version_id: uuid.UUID, db: DB, request: Request, principal: Principal = require(Perm.VERSION_DOWNLOAD)) -> Response:
    v = _load_version(db, principal, version_id, request)
    data = storage.read(v.storage_key)
    if storage.sha256_hex(data) != v.sha256_checksum:
        audit.record(db, "version.integrity_failed", "document_version", actor_id=principal.id, entity_id=v.id, manuscript_id=v.manuscript_id)
        db.commit()
        raise AppError(500, "CHECKSUM_MISMATCH", "Integritas berkas tersimpan gagal diverifikasi. Hubungi admin sistem.")
    audit.record(db, "version.downloaded", "document_version", actor_id=principal.id, entity_id=v.id, manuscript_id=v.manuscript_id, request=request)
    db.commit()
    return Response(
        content=data,
        media_type=v.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(v.original_filename)}",
            "X-Content-SHA256": v.sha256_checksum,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/versions/{version_id}/extract", response_model=VersionOut, status_code=status.HTTP_202_ACCEPTED)
def reextract(
    version_id: uuid.UUID, db: DB, request: Request, background: BackgroundTasks, principal: Principal = require(Perm.VERSION_REEXTRACT)
) -> VersionOut:
    v = _load_version(db, principal, version_id, request)
    if v.extraction_status not in extraction.REEXTRACTABLE:
        raise AppError(409, "EXTRACTION_IN_PROGRESS", "Ekstraksi sedang berjalan untuk versi ini.")
    before = {"status": v.extraction_status, "engine_version": v.extraction_engine_version}
    v.extraction_status = "PENDING"
    audit.record(db, "extraction.requeued", "document_version", actor_id=principal.id, entity_id=v.id, manuscript_id=v.manuscript_id,
                 before=before, after={"status": "PENDING"}, request=request)
    db.commit()
    if get_settings().extract_on_upload:
        background.add_task(extraction.run_extraction, v.id)
    return version_out(v)
