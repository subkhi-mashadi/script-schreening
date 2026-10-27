"""Penyimpanan berkas privat dan immutable.

Berkas ditulis sekali dengan `O_EXCL` (tidak pernah menimpa) lalu dibuat read-only.
`storage_key` adalah path relatif internal; tidak pernah dikirim ke pengguna.
"""

import hashlib
import os
import uuid
from pathlib import Path

from app.core.config import get_settings


class StorageError(Exception):
    pass


def _root() -> Path:
    root = get_settings().storage_dir.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_key(manuscript_id: uuid.UUID, version_number: int, checksum: str, extension: str) -> str:
    # Sufiks acak mencegah tabrakan dengan sisa berkas dari unggahan yang gagal dicatat.
    return f"manuscripts/{manuscript_id}/v{version_number:04d}-{uuid.uuid4().hex[:8]}-{checksum[:16]}.{extension}"


def _path_for(key: str) -> Path:
    root = _root()
    path = (root / key).resolve()
    if root not in path.parents:
        raise StorageError("storage key di luar direktori penyimpanan")
    return path


def put_immutable(key: str, data: bytes) -> None:
    path = _path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise StorageError(f"berkas sudah ada untuk key {key}; penimpaan tidak diizinkan") from exc
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(path, 0o400)


def read(key: str) -> bytes:
    return _path_for(key).read_bytes()


def verify(key: str, expected_sha256: str) -> bool:
    return sha256_hex(read(key)) == expected_sha256


def remove_orphan(key: str) -> None:
    """Hanya untuk membersihkan berkas yang gagal dicatat di database (transaksi rollback)."""
    path = _path_for(key)
    if path.exists():
        os.chmod(path, 0o600)
        path.unlink()
