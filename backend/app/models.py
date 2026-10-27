"""Model ORM. Skema mengikuti PRD §14; perubahan struktural dilakukan lewat migrasi Alembic."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _now(nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('publisher_admin','system_admin','rule_admin','editor','manager','intake_operator','auditor')",
            name="ck_users_role",
        ),
    )


class UserSession(Base):
    """Sesi login; token JWT membawa `sid` sehingga logout dapat mencabut token."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)


class Manuscript(Base):
    __tablename__ = "manuscripts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    internal_code: Mapped[str] = mapped_column(String(50), unique=True)
    working_title: Mapped[str] = mapped_column(Text)
    manuscript_type: Mapped[str] = mapped_column(String(50))
    language_code: Mapped[str] = mapped_column(String(10), server_default=text("'id'"))
    intake_status: Mapped[str] = mapped_column(String(30), server_default=text("'RECEIVED'"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    assigned_editor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    metadata_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    authors: Mapped[list["ManuscriptAuthor"]] = relationship(
        back_populates="manuscript", order_by="ManuscriptAuthor.author_order", cascade="all, delete-orphan"
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="manuscript", order_by="DocumentVersion.version_number"
    )
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    assigned_editor: Mapped[User | None] = relationship(foreign_keys=[assigned_editor_id])

    __table_args__ = (
        Index("idx_manuscripts_created_at", "created_at"),
        Index("idx_manuscripts_assigned_editor", "assigned_editor_id"),
    )


class ManuscriptAuthor(Base):
    __tablename__ = "manuscript_authors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id", ondelete="CASCADE"))
    author_name: Mapped[str] = mapped_column(String(300))
    author_order: Mapped[int] = mapped_column(Integer)
    author_email: Mapped[str | None] = mapped_column(String(320))
    affiliation: Mapped[str | None] = mapped_column(Text)

    manuscript: Mapped[Manuscript] = relationship(back_populates="authors")

    __table_args__ = (
        UniqueConstraint("manuscript_id", "author_order", deferrable=True, initially="DEFERRED"),
        CheckConstraint("author_order > 0", name="ck_author_order_positive"),
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(150))
    source_format: Mapped[str] = mapped_column(String(10))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256_checksum: Mapped[str] = mapped_column(String(64))
    extraction_status: Mapped[str] = mapped_column(String(30), server_default=text("'PENDING'"))
    extraction_engine_version: Mapped[str | None] = mapped_column(String(100))
    extraction_quality: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    extraction_summary_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    extraction_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = _now()
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))

    manuscript: Mapped[Manuscript] = relationship(back_populates="versions")
    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by])

    __table_args__ = (
        UniqueConstraint("manuscript_id", "version_number"),
        UniqueConstraint("manuscript_id", "idempotency_key"),
        CheckConstraint("version_number > 0", name="ck_version_number_positive"),
        CheckConstraint("file_size_bytes > 0", name="ck_file_size_positive"),
        CheckConstraint("extraction_quality BETWEEN 0 AND 100", name="ck_extraction_quality_range"),
        CheckConstraint(
            "extraction_status IN ('PENDING','PROCESSING','EXTRACTED','INCOMPLETE','FAILED')",
            name="ck_extraction_status",
        ),
        CheckConstraint("source_format IN ('docx','pdf','txt')", name="ck_source_format"),
        Index("idx_document_versions_extraction_status", "extraction_status"),
    )


class DocumentSection(Base):
    """Satu blok dari model dokumen ternormalisasi (heading, paragraf, tabel, dst.)."""

    __tablename__ = "document_sections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"))
    parent_section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_sections.id", ondelete="CASCADE"))
    block_id: Mapped[str] = mapped_column(String(30))
    section_type: Mapped[str] = mapped_column(String(30))
    heading_level: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(Text)
    heading_text: Mapped[str | None] = mapped_column(Text)
    paragraph_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    text_content: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(BigInteger)
    char_end: Mapped[int] = mapped_column(BigInteger)
    locator_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    extraction_warnings: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        UniqueConstraint("document_version_id", "paragraph_index"),
        UniqueConstraint("document_version_id", "block_id"),
        CheckConstraint("char_end >= char_start", name="ck_section_char_range"),
        Index("idx_document_sections_version_page", "document_version_id", "page_number"),
        Index("idx_document_sections_version_path", "document_version_id", "section_path"),
    )


class AuditLog(Base):
    """Append-only. Trigger database menolak UPDATE/DELETE."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    manuscript_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("manuscripts.id"))
    screening_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("screening_runs.id", name="fk_audit_logs_screening_run"))
    event_type: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        Index("idx_audit_logs_manuscript_time", "manuscript_id", "created_at"),
        Index("idx_audit_logs_actor_time", "actor_user_id", "created_at"),
        Index("idx_audit_logs_event_time", "event_type", "created_at"),
    )


# ---------------------------------------------------------------------------
# Fase 2 — mesin aturan & screening
# ---------------------------------------------------------------------------


class Rule(Base):
    """Definisi aturan master. Screening tidak membaca tabel ini langsung, melainkan
    snapshot di `rule_set_items` agar perubahan aturan tidak mengubah hasil historis."""

    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_code: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))
    # compliance = jalur ISBN/administratif; editorial = jalur editorial.
    track: Mapped[str] = mapped_column(String(20))
    authority_type: Mapped[str] = mapped_column(String(40))
    source_title: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(20), server_default=text("'unverified'"))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applies_to_types: Mapped[list | None] = mapped_column(JSONB)  # None = semua tipe
    engine_key: Mapped[str] = mapped_column(String(100))
    config_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    severity: Mapped[str] = mapped_column(String(20))
    blocking: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    requires_human_verification: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    scoring_effect: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    execution_order: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'active'"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "authority_type IN ('official_regulation','official_procedure','publisher_policy','editorial_indicator')",
            name="ck_rules_authority",
        ),
        CheckConstraint("severity IN ('critical','major','minor','info')", name="ck_rules_severity"),
        CheckConstraint("status IN ('draft','active','retired')", name="ck_rules_status"),
        CheckConstraint("track IN ('compliance','editorial')", name="ck_rules_track"),
        CheckConstraint("verification_status IN ('unverified','verified','rejected')", name="ck_rules_verification"),
    )


class RuleSet(Base):
    __tablename__ = "rule_sets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    description: Mapped[str | None] = mapped_column(Text)
    change_notes: Mapped[str | None] = mapped_column(Text)
    test_results_json: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    items: Mapped[list["RuleSetItem"]] = relationship(order_by="RuleSetItem.execution_order", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", "version"),
        CheckConstraint("status IN ('draft','published','archived')", name="ck_rule_sets_status"),
        CheckConstraint("version > 0", name="ck_rule_sets_version"),
    )


class RuleSetItem(Base):
    __tablename__ = "rule_set_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_sets.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    execution_order: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    # Snapshot lengkap definisi aturan saat rule set dibuat; yang dipakai screening.
    rule_snapshot_json: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("rule_set_id", "rule_id"),)


class RubricVersion(Base):
    __tablename__ = "rubric_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    manuscript_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'draft'"))
    min_scoring_coverage: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("80"))
    score_thresholds_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    change_notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    criteria: Mapped[list["RubricCriterion"]] = relationship(order_by="RubricCriterion.sort_order", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", "version", "manuscript_type"),
        CheckConstraint("status IN ('draft','published','archived')", name="ck_rubric_status"),
        CheckConstraint("min_scoring_coverage BETWEEN 0 AND 100", name="ck_rubric_coverage"),
        CheckConstraint("version > 0", name="ck_rubric_version"),
    )


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rubric_versions.id", ondelete="CASCADE"))
    criterion_code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    scoring_method_key: Mapped[str] = mapped_column(String(100), server_default=text("'deduction'"))
    config_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    required_for_scoring: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    __table_args__ = (
        UniqueConstraint("rubric_version_id", "criterion_code"),
        CheckConstraint("weight_percent >= 0 AND weight_percent <= 100", name="ck_criterion_weight"),
    )


class ScreeningRun(Base):
    __tablename__ = "screening_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    manuscript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("manuscripts.id"))
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    rule_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_sets.id"))
    rubric_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rubric_versions.id"))
    run_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), server_default=text("'QUEUED'"))
    isbn_status: Mapped[str | None] = mapped_column(String(30))
    editorial_status: Mapped[str | None] = mapped_column(String(30))
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    final_decision: Mapped[str | None] = mapped_column(String(40))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    recalculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    engine_version: Mapped[str] = mapped_column(String(100))
    trigger: Mapped[str] = mapped_column(String(30), server_default=text("'manual'"))
    # Tahap pemeriksaan: isbn (kelayakan ISBN, otomatis saat unggah) | layout (tata letak & kerapian, atas permintaan) | full (lama)
    scope: Mapped[str] = mapped_column(String(20), server_default=text("'full'"))
    extraction_summary_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    result_summary_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_details: Mapped[dict | None] = mapped_column(JSONB)

    rule_set: Mapped[RuleSet] = relationship()
    rubric: Mapped[RubricVersion | None] = relationship()

    __table_args__ = (
        UniqueConstraint("document_version_id", "run_number"),
        CheckConstraint("run_number > 0", name="ck_run_number"),
        CheckConstraint("status IN ('QUEUED','PROCESSING','COMPLETED','INCOMPLETE','FAILED','CANCELLED')", name="ck_run_status"),
        CheckConstraint(
            "final_decision IS NULL OR final_decision IN ('ACCEPTED_FOR_NEXT_STAGE','REVISION_REQUIRED','REJECTED','PENDING_VERIFICATION','SCREENING_INCOMPLETE')",
            name="ck_run_final_decision",
        ),
        Index("idx_screening_runs_status_started", "status", "started_at"),
        Index("idx_screening_runs_manuscript", "manuscript_id", "queued_at"),
        CheckConstraint("scope IN ('isbn','layout','full')", name="ck_run_scope"),
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    screening_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("screening_runs.id", ondelete="CASCADE"))
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    rule_code: Mapped[str] = mapped_column(String(80))
    track: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    criterion_code: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    page_estimate: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(Text)
    document_section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_sections.id"))
    paragraph_id: Mapped[str | None] = mapped_column(String(30))
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(BigInteger)
    char_end: Mapped[int | None] = mapped_column(BigInteger)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    requires_human_verification: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    blocking: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    verification_status: Mapped[str] = mapped_column(String(30), server_default=text("'UNREVIEWED'"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    sort_key: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    machine_result_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint("severity IN ('critical','major','minor','info')", name="ck_findings_severity"),
        CheckConstraint("char_end IS NULL OR char_start IS NULL OR char_end >= char_start", name="ck_findings_range"),
        CheckConstraint(
            "verification_status IN ('UNREVIEWED','CONFIRMED','FALSE_POSITIVE','NEEDS_FURTHER_CHECK','RESOLVED_IN_NEW_VERSION')",
            name="ck_findings_verification",
        ),
        Index("idx_findings_run_severity_status", "screening_run_id", "severity", "verification_status"),
        Index("idx_findings_version_page", "document_version_id", "page_number"),
        Index("idx_findings_run_sort", "screening_run_id", "sort_key"),
        Index("idx_findings_fingerprint", "fingerprint"),
    )


class ComplianceCheck(Base):
    __tablename__ = "compliance_checks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    screening_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("screening_runs.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id"))
    rule_code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    # Hasil pengamatan mesin (terlepas dari status verifikasi aturan): pass | fail | unknown
    observed: Mapped[str] = mapped_column(String(20))
    result_status: Mapped[str] = mapped_column(String(30))
    authority_type: Mapped[str] = mapped_column(String(40))
    rule_verification_status: Mapped[str] = mapped_column(String(20))
    blocking: Mapped[bool] = mapped_column(Boolean)
    evidence_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    explanation: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    requires_human_verification: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Pengamatan manusia atas bukti di luar naskah: pass | fail (NULL = belum).
    manual_observed: Mapped[str | None] = mapped_column(String(20))
    manual_note: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("screening_run_id", "rule_id"),
        CheckConstraint("result_status IN ('pass','fail','needs_verification','not_applicable','incomplete')", name="ck_compliance_status"),
        Index("idx_compliance_checks_run_status", "screening_run_id", "result_status"),
    )


class ScoreResult(Base):
    __tablename__ = "score_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    screening_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("screening_runs.id", ondelete="CASCADE"))
    rubric_criterion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rubric_criteria.id"))
    criterion_code_snapshot: Mapped[str | None] = mapped_column(String(80))
    criterion_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    result_type: Mapped[str] = mapped_column(String(20))
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    weight_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    weighted_contribution: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    scoring_status: Mapped[str] = mapped_column(String(30))
    evidence_coverage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    explanation: Mapped[str | None] = mapped_column(Text)
    calculation_details_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint("result_type IN ('criterion','total')", name="ck_score_type"),
        CheckConstraint("raw_score BETWEEN 0 AND 100", name="ck_score_range"),
        CheckConstraint("scoring_status IN ('scored','unscorable','not_applicable','needs_verification')", name="ck_score_status"),
        UniqueConstraint("screening_run_id", "criterion_code_snapshot", "result_type"),
    )


# ---------------------------------------------------------------------------
# Fase 4 — verifikasi editor & keputusan
# ---------------------------------------------------------------------------


class ReviewAction(Base):
    """Riwayat tindakan manusia atas temuan, item kepatuhan, dan screening (append-only)."""

    __tablename__ = "review_actions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    compliance_check_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("compliance_checks.id", ondelete="CASCADE"))
    screening_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("screening_runs.id", ondelete="CASCADE"))
    # NULL = tindakan sistem (mis. ditandai selesai otomatis oleh versi baru).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action_type: Mapped[str] = mapped_column(String(50))
    previous_status: Mapped[str | None] = mapped_column(String(50))
    new_status: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(
            "action_type IN ('confirm','false_positive','needs_check','reset','resolved_in_new_version','note',"
            "'manual_evidence','decision','recalculation')",
            name="ck_review_action_type",
        ),
        Index("idx_review_actions_run_time", "screening_run_id", "created_at"),
        Index("idx_review_actions_finding", "finding_id"),
    )
