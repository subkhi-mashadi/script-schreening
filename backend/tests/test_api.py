import pytest
from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.core.permissions import Role
from app.models import AuditLog, DocumentVersion
from app.services import storage
from tests.conftest import PASSWORD, login, make_user
from tests.factories import make_docx, make_macro_docx, make_pdf, make_scanned_pdf, make_zip_bomb_docx

API = "/api/v1"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def events(*types: str) -> list[AuditLog]:
    with SessionLocal() as db:
        stmt = select(AuditLog).order_by(AuditLog.created_at)
        if types:
            stmt = stmt.where(AuditLog.event_type.in_(types))
        return list(db.scalars(stmt))


def create_ms(client, headers, **extra) -> dict:
    body = {
        "working_title": "Manajemen Penerbitan Modern",
        "manuscript_type": "buku_ilmiah",
        "language_code": "id",
        "submitted_at": "2026-10-20T03:00:00Z",
        "authors": [{"author_name": "A. Sutrisno"}, {"author_name": "B. Lestari", "affiliation": "Univ. Contoh"}],
        **extra,
    }
    r = client.post(f"{API}/manuscripts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, headers, ms_id, data=None, name="naskah.docx", mime=DOCX_MIME, **kw):
    return client.post(
        f"{API}/manuscripts/{ms_id}/versions",
        files={"file": (name, data if data is not None else make_docx(), mime)},
        headers=headers,
        **kw,
    )


# --- Auth -----------------------------------------------------------------


def test_login_logout_and_revocation(client, users):
    r = client.post(f"{API}/auth/login", json={"email": "editor@uji.id", "password": PASSWORD})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get(f"{API}/auth/me", headers=h).json()
    assert me["role"] == "editor" and "manuscript.read_scoped" in me["permissions"]
    assert client.post(f"{API}/auth/logout", headers=h).status_code == 204
    r = client.get(f"{API}/auth/me", headers=h)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
    assert [e.event_type for e in events("auth.login", "auth.logout")] == ["auth.login", "auth.logout"]


def test_login_failures_are_throttled(client, users):
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"email": "editor@uji.id", "password": "salah-salah-salah"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    r = client.post(f"{API}/auth/login", json={"email": "editor@uji.id", "password": PASSWORD})
    assert r.status_code == 429
    assert len(events("auth.login_failed")) == 5


def test_unknown_email_same_error(client, users):
    r = client.post(f"{API}/auth/login", json={"email": "tidakada@uji.id", "password": "apa-saja-123456"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_deactivated_user_sessions_revoked(client, users, auth):
    h = auth("editor")
    r = client.patch(f"{API}/users/{users['editor'].id}", json={"is_active": False}, headers=auth("system_admin"))
    assert r.status_code == 200
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401


# --- RBAC -----------------------------------------------------------------


@pytest.mark.parametrize("role", ["editor", "auditor", "rule_admin", "system_admin", "manager"])
def test_only_operator_creates_manuscripts(client, auth, role):
    r = client.post(f"{API}/manuscripts", json={"working_title": "X", "manuscript_type": "fiksi"}, headers=auth(role))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    denied = events("access.denied")
    assert denied and denied[-1].after_json["reason"] == "missing_permission:manuscript.create"


def test_user_management_requires_admin(client, auth):
    assert client.get(f"{API}/users", headers=auth("manager")).status_code == 403
    r = client.post(
        f"{API}/users",
        json={"full_name": "Baru", "email": "baru@uji.id", "role": "editor", "password": "kata-sandi-panjang-1"},
        headers=auth("system_admin"),
    )
    assert r.status_code == 201
    assert events("user.created")[-1].after_json["email"] == "baru@uji.id"
    assert "password" not in str(events("user.created")[-1].after_json)


def test_manuscript_scope(client, auth, users):
    op = auth("intake_operator")
    assigned = create_ms(client, op, assigned_editor_id=str(users["editor"].id))
    other = create_ms(client, op)

    editor = auth("editor")
    ids = {m["id"] for m in client.get(f"{API}/manuscripts", headers=editor).json()["items"]}
    assert ids == {assigned["id"]}
    assert client.get(f"{API}/manuscripts/{other['id']}", headers=editor).status_code == 404
    assert events("access.denied")[-1].entity_id is not None

    # Operator lain tidak melihat naskah operator pertama.
    op2 = make_user(Role.INTAKE_OPERATOR, email="op2@uji.id")
    h2 = login(client, op2.email)
    assert client.get(f"{API}/manuscripts", headers=h2).json()["total"] == 0

    # Manajer & auditor melihat semua.
    for role in ("manager", "auditor"):
        assert client.get(f"{API}/manuscripts", headers=auth(role)).json()["total"] == 2
    # Admin aturan tidak memiliki akses naskah.
    assert client.get(f"{API}/manuscripts", headers=auth("rule_admin")).json()["total"] == 0


# --- Naskah ---------------------------------------------------------------


def test_create_and_update_manuscript_with_audit(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    assert m["internal_code"].startswith("NSK-") and m["internal_code"].endswith("000001")
    assert [a["author_order"] for a in m["authors"]] == [1, 2]
    assert m["incomplete_fields"] == []

    r = client.patch(f"{API}/manuscripts/{m['id']}", json={"working_title": "Judul Baru", "authors": [{"author_name": "C"}]}, headers=op)
    assert r.status_code == 200 and r.json()["working_title"] == "Judul Baru"
    upd = events("manuscript.updated")[-1]
    assert upd.before_json["working_title"] == "Manajemen Penerbitan Modern"
    assert upd.after_json["working_title"] == "Judul Baru"


def test_incomplete_metadata_flagged_not_assumed(client, auth):
    r = client.post(f"{API}/manuscripts", json={"working_title": "Draf", "manuscript_type": "fiksi"}, headers=auth("intake_operator"))
    assert r.status_code == 201
    body = r.json()
    assert set(body["incomplete_fields"]) == {"authors", "submitted_at"}
    assert body["submitted_at"] is None


def test_invalid_type_rejected(client, auth):
    r = client.post(f"{API}/manuscripts", json={"working_title": "X", "manuscript_type": "komik"}, headers=auth("intake_operator"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Versi & ekstraksi ----------------------------------------------------


def test_upload_creates_immutable_versions_and_extracts(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    r1 = upload(client, op, m["id"], make_docx(footnote=True))
    assert r1.status_code == 201, r1.text
    v1 = r1.json()
    assert v1["version_number"] == 1 and len(v1["sha256_checksum"]) == 64

    detail = client.get(f"{API}/versions/{v1['id']}", headers=op).json()
    assert detail["extraction_status"] == "EXTRACTED"
    assert float(detail["extraction_quality"]) >= 60
    assert detail["extraction_engine_version"].startswith("docx-reader/")
    summary = detail["extraction_summary_json"]
    assert summary["block_counts"]["heading"] >= 5 and summary["block_counts"]["footnote"] == 1

    secs = client.get(f"{API}/versions/{v1['id']}/sections", params={"section_type": "heading"}, headers=op).json()
    assert any(s["text_content"] == "BAB I PENDAHULUAN" for s in secs["items"])
    sub = client.get(f"{API}/versions/{v1['id']}/sections", params={"section_path": "BAB I PENDAHULUAN > 1.1 Latar Belakang"}, headers=op).json()
    assert sub["total"] >= 3 and all(s["parent_section_id"] for s in sub["items"])
    # Prefix parsial tidak cocok: "BAB I" bukan induk "BAB II".
    bab1 = client.get(f"{API}/versions/{v1['id']}/sections", params={"section_path": "BAB I"}, headers=op).json()
    assert bab1["total"] == 0
    heads = summary["headings"]
    assert any(h["section_path"] == "BAB I PENDAHULUAN > 1.1 Latar Belakang" for h in heads)

    r2 = upload(client, op, m["id"], make_docx(title="Revisi"))
    v2 = r2.json()
    assert v2["version_number"] == 2 and v2["supersedes_version_id"] == v1["id"]

    # Berkas lama tetap ada & utuh.
    with SessionLocal() as db:
        old = db.get(DocumentVersion, v1["id"])
        assert storage.verify(old.storage_key, old.sha256_checksum)

    # Upload ulang berkas identik tetap versi baru, dengan peringatan duplikat.
    r3 = upload(client, op, m["id"], make_docx(title="Revisi"))
    assert r3.json()["version_number"] == 3 and "DUPLICATE_OF_VERSION_2" in r3.json()["warnings"]
    assert len(events("version.uploaded")) == 3
    assert len(events("extraction.completed")) == 3


def test_version_file_identity_cannot_be_changed(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    v = upload(client, op, m["id"]).json()
    with SessionLocal() as db:
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE document_versions SET sha256_checksum = repeat('0', 64) WHERE id = :id"), {"id": v["id"]})
        db.rollback()
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("DELETE FROM document_versions WHERE id = :id"), {"id": v["id"]})
        db.rollback()
    with pytest.raises(PermissionError):
        with SessionLocal() as db:
            key = db.get(DocumentVersion, v["id"]).storage_key
        open(storage._path_for(key), "wb")


def test_audit_log_is_append_only(client, auth):
    auth("editor")
    with SessionLocal() as db:
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("UPDATE audit_logs SET event_type = 'x'"))
        db.rollback()
        with pytest.raises(Exception, match="append-only"):
            db.execute(text("DELETE FROM audit_logs"))
        db.rollback()


def test_idempotent_upload(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    h = {**op, "Idempotency-Key": "unggah-123"}
    a = upload(client, h, m["id"])
    b = upload(client, h, m["id"])
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"] and "IDEMPOTENT_REPLAY" in b.json()["warnings"]


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("naskah.docx", make_pdf(), "CONTENT_MISMATCH"),
        ("naskah.pdf", b"bukan pdf sama sekali", "CONTENT_MISMATCH"),
        ("naskah.exe", b"MZ\x90\x00", "UNSUPPORTED_EXTENSION"),
        ("naskah.docx", make_macro_docx(), "MACRO_NOT_ALLOWED"),
        ("naskah.docx", make_zip_bomb_docx(), "ARCHIVE_SUSPICIOUS_RATIO"),
        ("kosong.txt", b"", "EMPTY_FILE"),
    ],
)
def test_upload_validation_by_content(client, auth, name, data, code):
    op = auth("intake_operator")
    m = create_ms(client, op)
    r = upload(client, op, m["id"], data, name=name, mime="application/octet-stream")
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code
    assert events("version.upload_rejected")[-1].after_json["code"] == code


def test_scanned_pdf_marked_incomplete(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    v = upload(client, op, m["id"], make_scanned_pdf(), name="pindai.pdf", mime="application/pdf").json()
    d = client.get(f"{API}/versions/{v['id']}", headers=op).json()
    assert d["extraction_status"] == "INCOMPLETE"
    codes = {w["code"] for w in d["extraction_summary_json"]["warnings"]}
    assert "OCR_NOT_AVAILABLE" in codes


def test_corrupt_pdf_fails_with_structured_error_and_can_requeue(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    v = upload(client, op, m["id"], b"%PDF-1.7\n rusak", name="rusak.pdf", mime="application/pdf").json()
    d = client.get(f"{API}/versions/{v['id']}", headers=op).json()
    assert d["extraction_status"] == "FAILED"
    assert d["extraction_summary_json"]["error"]["kind"] == "document"
    r = client.post(f"{API}/versions/{v['id']}/extract", headers=op)
    assert r.status_code == 202
    assert len(events("extraction.failed")) == 2 and len(events("extraction.requeued")) == 1


def test_pdf_page_locators(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    v = upload(client, op, m["id"], make_pdf(), name="naskah.pdf", mime="application/pdf").json()
    p3 = client.get(f"{API}/versions/{v['id']}/sections", params={"page_number": 3}, headers=op).json()
    assert p3["total"] > 0 and all(s["page_number"] == 3 for s in p3["items"])


def test_download_requires_scope_and_is_audited(client, auth, users):
    op = auth("intake_operator")
    m = create_ms(client, op)
    data = make_docx()
    v = upload(client, op, m["id"], data).json()
    r = client.get(f"{API}/versions/{v['id']}/download", headers=op)
    assert r.status_code == 200 and r.content == data
    assert r.headers["x-content-sha256"] == v["sha256_checksum"]
    assert events("version.downloaded")
    # Editor yang tidak ditugaskan tidak bisa mengunduh; storage_key tidak pernah terekspos.
    assert client.get(f"{API}/versions/{v['id']}/download", headers=auth("editor")).status_code == 404
    assert "storage_key" not in client.get(f"{API}/versions/{v['id']}", headers=op).text


def test_audit_search_requires_permission_and_is_audited(client, auth):
    create_ms(client, auth("intake_operator"))
    assert client.get(f"{API}/audit-logs", headers=auth("editor")).status_code == 403
    r = client.get(f"{API}/audit-logs", params={"event_type": "manuscript."}, headers=auth("auditor"))
    assert r.status_code == 200 and r.json()["total"] == 1
    assert events("audit.searched")


def test_stats_and_history(client, auth):
    op = auth("intake_operator")
    m = create_ms(client, op)
    upload(client, op, m["id"])
    create_ms(client, op)
    s = client.get(f"{API}/manuscripts/stats", headers=op).json()
    assert s == {"manuscripts": 2, "by_extraction_status": {"EXTRACTED": 1}, "no_version": 1}
    hist = client.get(f"{API}/manuscripts/{m['id']}/history", headers=op).json()
    assert {e["event_type"] for e in hist["items"]} >= {"manuscript.created", "version.uploaded", "extraction.completed"}


# --- Cek cepat ------------------------------------------------------------


def test_quick_check_creates_manuscript_and_extracts(client, auth):
    op = auth("intake_operator")
    r = client.post(f"{API}/quick-checks", files={"file": ("Buku_Penerbitan.docx", make_docx(), DOCX_MIME)}, headers=op)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["working_title"] == "Buku Penerbitan" and body["version"]["version_number"] == 1
    v = client.get(f"{API}/versions/{body['version']['id']}", headers=op).json()
    assert v["extraction_status"] == "EXTRACTED"
    m = client.get(f"{API}/manuscripts/{body['manuscript_id']}", headers=op).json()
    # Jenis diisi otomatis dari klasifikasi tahap 1 (bukan asumsi: ditandai sumbernya).
    assert m["manuscript_type"] != "lainnya" and m["metadata_json"]["type_source"] == "auto"
    assert set(m["incomplete_fields"]) == {"authors", "submitted_at"}, "metadata kosong ditandai, tidak diasumsikan"


def test_quick_check_rejected_file_leaves_no_manuscript(client, auth):
    op = auth("intake_operator")
    r = client.post(f"{API}/quick-checks", files={"file": ("x.docx", make_pdf(), DOCX_MIME)}, headers=op)
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONTENT_MISMATCH"
    assert client.get(f"{API}/manuscripts", headers=op).json()["total"] == 0
    assert events("version.upload_rejected")[-1].entity_type == "quick_check"


def test_quick_check_requires_create_permission(client, auth):
    r = client.post(f"{API}/quick-checks", files={"file": ("a.docx", make_docx(), DOCX_MIME)}, headers=auth("editor"))
    assert r.status_code == 403


# --- Dashboard ------------------------------------------------------------


def test_dashboard_aggregates_are_scoped(client, auth, users):
    op = auth("intake_operator")
    m1 = create_ms(client, op, assigned_editor_id=str(users["editor"].id))
    upload(client, op, m1["id"])
    m2 = create_ms(client, op)
    upload(client, op, m2["id"], make_scanned_pdf(), name="pindai.pdf", mime="application/pdf")
    client.post(f"{API}/manuscripts", json={"working_title": "Tanpa berkas", "manuscript_type": "fiksi"}, headers=op)

    d = client.get(f"{API}/dashboard", headers=op).json()
    k = d["kpi"]
    assert k["manuscripts"] == 3 and k["versions"] == 2 and k["ready"] == 1 and k["received_30d"] == 3
    assert d["by_extraction_status"] == {"EXTRACTED": 1, "INCOMPLETE": 1} and d["no_version"] == 1
    # Naskah contoh tanpa halaman hak cipta → belum layak ISBN → ikut perlu tindakan.
    assert k["needs_attention"] == 3
    reasons = {a["working_title"]: a["reasons"] for a in d["attention"]}
    assert reasons["Tanpa berkas"] == ["NO_VERSION", "INCOMPLETE_METADATA"]
    all_reasons = [r for a in d["attention"] for r in a["reasons"]]
    assert "EXTRACTION_INCOMPLETE" in all_reasons and "ISBN_FAIL" in all_reasons
    assert len(d["uploads_daily"]) == 14 and d["uploads_daily"][-1]["count"] == 2
    assert d["by_type"] == {"buku_ilmiah": 2, "fiksi": 1}
    assert any(a["event_type"] == "version.uploaded" for a in d["activity"])

    e = client.get(f"{API}/dashboard", headers=auth("editor")).json()
    assert e["kpi"]["manuscripts"] == 1 and e["kpi"]["ready"] == 1
    assert {a["manuscript_id"] for a in e["activity"]} == {m1["id"]}
    assert client.get(f"{API}/dashboard", headers=auth("rule_admin")).json()["has_access"] is False
