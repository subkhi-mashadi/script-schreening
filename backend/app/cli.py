"""Perintah operasional.

    uv run python -m app.cli create-user --email admin@contoh.id --name "Admin" --role system_admin
    uv run python -m app.cli extract-pending
    uv run python -m app.cli seed-catalog      # aturan & rubrik awal (idempoten)
    uv run python -m app.cli screen-pending    # proses screening yang masih QUEUED
    uv run python -m app.cli screen-unscreened # screening versi terbaru yang belum pernah diperiksa
    uv run python -m app.cli extract-file path/ke/naskah.docx   # uji reader tanpa database
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.permissions import Role
from app.core.security import hash_password
from app.models import User
from app.services import audit, extraction


def create_user(args: argparse.Namespace) -> int:
    # Validasi sama dengan API login, agar akun yang dibuat lewat CLI pasti bisa login.
    try:
        args.email = TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError as exc:
        print(f"Email tidak valid: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 1
    password = args.password or getpass.getpass("Kata sandi (min. 12 karakter): ")
    if len(password) < 12:
        print("Kata sandi minimal 12 karakter.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == args.email.lower())):
            print("Email sudah terdaftar.", file=sys.stderr)
            return 1
        u = User(full_name=args.name, email=args.email.lower(), role=args.role, password_hash=hash_password(password))
        db.add(u)
        db.flush()
        audit.record(db, "user.created", "user", entity_id=u.id, after={"email": u.email, "role": u.role, "via": "cli"})
        db.commit()
        print(f"Pengguna dibuat: {u.email} ({u.role}) id={u.id}")
    return 0


def extract_pending(_: argparse.Namespace) -> int:
    n = extraction.process_pending()
    print(f"{n} versi diproses.")
    return 0


def seed_catalog(_: argparse.Namespace) -> int:
    from app.screening.catalog import seed_catalog as seed

    with SessionLocal() as db:
        print(seed(db))
        db.commit()
    return 0


def screen_pending(_: argparse.Namespace) -> int:
    from app.screening import runner

    print(f"{runner.process_queued()} screening diproses.")
    return 0


def screen_unscreened(_: argparse.Namespace) -> int:
    """Screening untuk versi terbaru tiap naskah yang belum pernah diperiksa (mis. diunggah sebelum Fase 2)."""
    from sqlalchemy import func

    from app.models import DocumentVersion, ScreeningRun
    from app.screening import runner

    with SessionLocal() as db:
        latest = (
            select(DocumentVersion.manuscript_id, func.max(DocumentVersion.version_number).label("vn"))
            .group_by(DocumentVersion.manuscript_id)
            .subquery()
        )
        ids = db.scalars(
            select(DocumentVersion.id)
            .join(latest, (DocumentVersion.manuscript_id == latest.c.manuscript_id) & (DocumentVersion.version_number == latest.c.vn))
            .where(DocumentVersion.extraction_status.in_(("EXTRACTED", "INCOMPLETE")))
            .where(~select(ScreeningRun.id).where(ScreeningRun.document_version_id == DocumentVersion.id).exists())
        ).all()
    for vid in ids:
        runner.queue_and_run(vid, None, "backfill")
    print(f"{len(ids)} versi di-screening.")
    return 0


def extract_file(args: argparse.Namespace) -> int:
    from app.reader import extract

    path = Path(args.path)
    fmt = path.suffix.lower().lstrip(".")
    result = extract(fmt, path.read_bytes())
    summary = result.document.to_summary()
    summary["quality"] = {"score": result.quality.score, "status": result.quality.status, "reasons": result.quality.reasons}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", required=True, choices=[r.value for r in Role])
    cu.add_argument("--password")
    cu.set_defaults(func=create_user)
    sub.add_parser("extract-pending").set_defaults(func=extract_pending)
    sub.add_parser("seed-catalog").set_defaults(func=seed_catalog)
    sub.add_parser("screen-pending").set_defaults(func=screen_pending)
    sub.add_parser("screen-unscreened").set_defaults(func=screen_unscreened)
    ef = sub.add_parser("extract-file")
    ef.add_argument("path")
    ef.set_defaults(func=extract_file)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
