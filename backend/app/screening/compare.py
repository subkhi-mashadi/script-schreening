"""Perbandingan hasil screening antarversi (FR-10).

Temuan dicocokkan dengan sidik jari berbasis isi (kode aturan + judul + kutipan bukti yang
dinormalisasi), bukan nomor blok/halaman yang berubah saat naskah direvisi.
"""

import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentVersion, Finding, ScreeningRun

RE_LOCATION = re.compile(r"(±\s*)?(halaman|hal\.)\s*\d+|blok\s+b\d+|b\d{6}", re.IGNORECASE)


def _norm(text: str | None) -> str:
    t = RE_LOCATION.sub(" ", (text or "").lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def fingerprint(rule_code: str, title: str, excerpt: str | None) -> str:
    raw = f"{rule_code}|{_norm(title)}|{_norm(excerpt)[:240]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def previous_run(db: Session, run: ScreeningRun) -> ScreeningRun | None:
    """Screening selesai terakhir dari versi dokumen sebelumnya pada naskah yang sama."""
    current = db.get(DocumentVersion, run.document_version_id)
    return db.scalar(
        select(ScreeningRun)
        .join(DocumentVersion, DocumentVersion.id == ScreeningRun.document_version_id)
        .where(
            ScreeningRun.manuscript_id == run.manuscript_id,
            DocumentVersion.version_number < current.version_number,
            ScreeningRun.status.in_(("COMPLETED", "INCOMPLETE")),
            ScreeningRun.scope == run.scope,
        )
        .order_by(DocumentVersion.version_number.desc(), ScreeningRun.run_number.desc())
        .limit(1)
    )


def compare(db: Session, old: ScreeningRun, new: ScreeningRun) -> dict[str, Any]:
    def load(r: ScreeningRun) -> list[Finding]:
        return list(db.scalars(select(Finding).where(Finding.screening_run_id == r.id).order_by(Finding.sort_key)))

    a, b = load(old), load(new)
    a_fp = {f.fingerprint for f in a}
    b_fp = {f.fingerprint for f in b}

    def brief(f: Finding) -> dict[str, Any]:
        return {"id": str(f.id), "rule_code": f.rule_code, "severity": f.severity, "title": f.title, "section_path": f.section_path,
                "verification_status": f.verification_status}

    old_v = db.get(DocumentVersion, old.document_version_id).version_number
    new_v = db.get(DocumentVersion, new.document_version_id).version_number
    return {
        "previous": {"run_id": str(old.id), "version_number": old_v, "total_score": float(old.total_score) if old.total_score is not None else None,
                     "isbn_status": old.isbn_status, "editorial_status": old.editorial_status, "findings": len(a)},
        "current": {"run_id": str(new.id), "version_number": new_v, "total_score": float(new.total_score) if new.total_score is not None else None,
                    "isbn_status": new.isbn_status, "editorial_status": new.editorial_status, "findings": len(b)},
        "resolved": [brief(f) for f in a if f.fingerprint not in b_fp],
        "new": [brief(f) for f in b if f.fingerprint not in a_fp],
        "persisting": [brief(f) for f in b if f.fingerprint in a_fp],
        "rule_set_changed": old.rule_set_id != new.rule_set_id,
        "rubric_changed": old.rubric_version_id != new.rubric_version_id,
    }
