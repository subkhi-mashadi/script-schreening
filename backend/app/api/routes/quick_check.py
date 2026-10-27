"""Cek cepat: unggah satu berkas → rekaman naskah + versi 1 dibuat otomatis → ekstraksi.

Berkas divalidasi lebih dulu; rekaman naskah baru dibuat bila berkas diterima, dalam
transaksi yang sama dengan versi dokumen, sehingga unggahan yang ditolak tidak
meninggalkan naskah kosong. Metadata yang tidak diisi tetap ditandai belum lengkap.
"""

import uuid
from pathlib import PurePath

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile, status
from pydantic import BaseModel

from app.api.deps import DB, Principal, require
from app.api.routes.manuscripts import next_code, snapshot
from app.api.routes.versions import read_limited, store_new_version, version_out
from app.core.config import get_settings
from app.core.constants import DISTRIBUTION_OPTIONS, MANUSCRIPT_TYPES
from app.core.errors import AppError
from app.core.permissions import Perm
from app.models import Manuscript
from app.schemas import VersionOut
from app.services import audit, extraction
from app.services.file_validation import FileRejected, safe_filename, validate_upload

router = APIRouter(prefix="/quick-checks", tags=["quick-check"])


class QuickCheckOut(BaseModel):
    manuscript_id: uuid.UUID
    internal_code: str
    working_title: str
    version: VersionOut


@router.post("", response_model=QuickCheckOut, status_code=status.HTTP_201_CREATED)
async def quick_check(
    db: DB,
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    manuscript_type: str = Form("lainnya"),
    working_title: str | None = Form(None, max_length=1000),
    distribution: str | None = Form(None, description="dijual_umum | gratis_umum | terbatas"),
    principal: Principal = require(Perm.MANUSCRIPT_CREATE),
) -> QuickCheckOut:
    if not principal.can(Perm.VERSION_UPLOAD):
        raise AppError(403, "FORBIDDEN", "Anda tidak memiliki izin mengunggah berkas.")
    if distribution and distribution not in DISTRIBUTION_OPTIONS:
        raise AppError(422, "INVALID_DISTRIBUTION", "Rencana peredaran tidak dikenal.")
    if manuscript_type not in MANUSCRIPT_TYPES:
        raise AppError(422, "INVALID_TYPE", "Jenis naskah tidak dikenal.")

    filename = safe_filename(file.filename)
    data = await read_limited(file)
    try:
        vf = validate_upload(filename, data)
    except FileRejected as exc:
        audit.record(db, "version.upload_rejected", "quick_check", actor_id=principal.id,
                     after={"code": exc.code, "filename": filename, "size": len(data)}, request=request)
        db.commit()
        raise AppError(422, exc.code, exc.message) from None

    title = (working_title or "").strip() or PurePath(filename).stem.replace("_", " ").strip() or filename
    m = Manuscript(
        internal_code=next_code(db),
        working_title=title,
        manuscript_type=manuscript_type,
        created_by=principal.id,
        metadata_json={"intake_channel": "quick_check", **({"distribution": distribution} if distribution else {})},
    )
    db.add(m)
    db.flush()
    audit.record(db, "manuscript.created", "manuscript", actor_id=principal.id, entity_id=m.id, manuscript_id=m.id,
                 after={**snapshot(m), "via": "quick_check"}, request=request)
    # store_new_version melakukan commit: naskah dan versi tersimpan bersama atau tidak sama sekali.
    v, warnings = store_new_version(db, m.id, filename, vf, data, principal, request)
    if get_settings().extract_on_upload:
        background.add_task(extraction.run_extraction, v.id)
    return QuickCheckOut(manuscript_id=m.id, internal_code=m.internal_code, working_title=m.working_title,
                         version=version_out(v, warnings))
