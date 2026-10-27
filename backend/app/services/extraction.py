"""Menjalankan Document Reader untuk satu versi dokumen dan menyimpan model ternormalisasi."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import DocumentSection, DocumentVersion
from app.reader import ExtractionError, docx_reader, extract, pdf_reader, txt_reader
from app.services import audit, storage

log = logging.getLogger(__name__)

REEXTRACTABLE = ("FAILED", "INCOMPLETE", "EXTRACTED", "PENDING")


def claim(db: Session, version_id: uuid.UUID) -> bool:
    """Klaim atomik PENDING → PROCESSING agar dua worker tidak memproses versi yang sama."""
    res = db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.id == version_id, DocumentVersion.extraction_status == "PENDING")
        .values(extraction_status="PROCESSING", extraction_started_at=datetime.now(UTC), extraction_completed_at=None)
        .returning(DocumentVersion.id)
    )
    db.commit()
    return res.first() is not None


def run_extraction(version_id: uuid.UUID, screen_after: bool = True) -> None:
    """Entry point background task / worker. Membuka sesi database sendiri.

    Setelah pembacaan selesai (utuh maupun sebagian), screening otomatis dijalankan dengan
    rule set dan rubrik yang sedang terbit.
    """
    with SessionLocal() as db:
        if not claim(db, version_id):
            return
        try:
            _process(db, version_id)
        except Exception as exc:  # kesalahan sistem: tandai FAILED, jangan sampai status menggantung
            db.rollback()
            log.exception("Ekstraksi gagal karena kesalahan sistem untuk versi %s", version_id)
            _mark_failed(db, version_id, "SYSTEM_ERROR", "Kesalahan sistem saat ekstraksi.", kind="system",
                         detail=exc.__class__.__name__)
            return
        version = db.get(DocumentVersion, version_id)
        status, uploader = version.extraction_status, version.uploaded_by
    if screen_after and status in ("EXTRACTED", "INCOMPLETE"):
        from app.screening import runner  # impor lokal: runner bergantung pada model yang sama

        runner.queue_and_run(version_id, uploader, "after_extraction")


def process_pending(limit: int = 20) -> int:
    with SessionLocal() as db:
        ids = db.scalars(
            select(DocumentVersion.id)
            .where(DocumentVersion.extraction_status == "PENDING")
            .order_by(DocumentVersion.uploaded_at)
            .limit(limit)
        ).all()
    for vid in ids:
        run_extraction(vid)
    return len(ids)


def _process(db: Session, version_id: uuid.UUID) -> None:
    version = db.get(DocumentVersion, version_id)
    data = storage.read(version.storage_key)
    if storage.sha256_hex(data) != version.sha256_checksum:
        _mark_failed(db, version_id, "CHECKSUM_MISMATCH", "Checksum berkas tersimpan tidak cocok dengan catatan.", kind="integrity")
        return

    try:
        result = extract(version.source_format, data)
    except ExtractionError as exc:
        _mark_failed(db, version_id, exc.code, exc.message, kind="document", engine=_engine_for(version.source_format))
        return

    doc, quality = result.document, result.quality
    db.execute(delete(DocumentSection).where(DocumentSection.document_version_id == version_id))

    ids = [uuid.uuid4() for _ in doc.blocks]
    rows = []
    for b, sid in zip(doc.blocks, ids, strict=True):
        locator = {**b.locator, "block_id": b.block_id}
        if b.style:
            locator.setdefault("style", b.style)
        if b.detection:
            locator["heading_detection"] = b.detection
        rows.append(
            DocumentSection(
                id=sid,
                document_version_id=version_id,
                parent_section_id=ids[b.parent_index] if b.parent_index is not None else None,
                block_id=b.block_id,
                section_type=b.type,
                heading_level=b.level,
                section_path=b.section_path,
                heading_text=b.text if b.type == "heading" else None,
                paragraph_index=b.index,
                page_number=b.page_number,
                text_content=b.text,
                char_start=b.char_start,
                char_end=b.char_end,
                locator_json=locator,
            )
        )
    db.add_all(rows)

    summary = doc.to_summary()
    summary["quality"] = {"score": quality.score, "status": quality.status, "reasons": quality.reasons, **quality.metrics}
    summary["pages"] = [
        {"page_number": p.page_number, "label": p.label, "char_count": p.char_count, "is_scanned": p.is_scanned}
        for p in doc.pages
    ][:2000]
    version.extraction_status = quality.status
    version.extraction_quality = quality.score
    version.extraction_engine_version = doc.engine_version
    version.extraction_summary_json = summary
    version.extraction_completed_at = datetime.now(UTC)
    audit.record(
        db,
        "extraction.completed",
        "document_version",
        entity_id=version_id,
        manuscript_id=version.manuscript_id,
        after={
            "status": quality.status,
            "quality": quality.score,
            "reasons": quality.reasons,
            "blocks": len(doc.blocks),
            "engine_version": doc.engine_version,
        },
    )
    db.commit()


def _engine_for(fmt: str) -> str:
    return {"docx": docx_reader.ENGINE_VERSION, "pdf": pdf_reader.ENGINE_VERSION, "txt": txt_reader.ENGINE_VERSION}.get(fmt, "unknown")


def _mark_failed(db: Session, version_id: uuid.UUID, code: str, message: str, *, kind: str,
                 engine: str | None = None, detail: str | None = None) -> None:
    version = db.get(DocumentVersion, version_id)
    db.execute(delete(DocumentSection).where(DocumentSection.document_version_id == version_id))
    version.extraction_status = "FAILED"
    version.extraction_quality = None
    version.extraction_engine_version = engine
    version.extraction_summary_json = {"error": {"code": code, "message": message, "kind": kind, "detail": detail}}
    version.extraction_completed_at = datetime.now(UTC)
    audit.record(
        db,
        "extraction.failed",
        "document_version",
        entity_id=version_id,
        manuscript_id=version.manuscript_id,
        after={"code": code, "kind": kind},
    )
    db.commit()
