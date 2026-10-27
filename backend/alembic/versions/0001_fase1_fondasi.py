"""fase1 fondasi

Revision ID: 0001
Revises: 
Create Date: 2026-10-23 10:16:01.302017

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

IMMUTABLE_VERSION_FN = """
CREATE FUNCTION document_versions_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'document_versions bersifat immutable: penghapusan tidak diizinkan';
    END IF;
    IF NEW.manuscript_id IS DISTINCT FROM OLD.manuscript_id
       OR NEW.version_number IS DISTINCT FROM OLD.version_number
       OR NEW.original_filename IS DISTINCT FROM OLD.original_filename
       OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
       OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
       OR NEW.source_format IS DISTINCT FROM OLD.source_format
       OR NEW.file_size_bytes IS DISTINCT FROM OLD.file_size_bytes
       OR NEW.sha256_checksum IS DISTINCT FROM OLD.sha256_checksum
       OR NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by
       OR NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at
       OR NEW.supersedes_version_id IS DISTINCT FROM OLD.supersedes_version_id
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key THEN
        RAISE EXCEPTION 'document_versions bersifat immutable: identitas berkas tidak boleh diubah';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

AUDIT_APPEND_ONLY_FN = """
CREATE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs bersifat append-only';
END;
$$ LANGUAGE plpgsql;
"""

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE SEQUENCE manuscript_code_seq START 1")
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('role', sa.String(length=40), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('system_admin','rule_admin','editor','manager','intake_operator','auditor')", name='ck_users_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('manuscripts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('internal_code', sa.String(length=50), nullable=False),
    sa.Column('working_title', sa.Text(), nullable=False),
    sa.Column('manuscript_type', sa.String(length=50), nullable=False),
    sa.Column('language_code', sa.String(length=10), server_default=sa.text("'id'"), nullable=False),
    sa.Column('intake_status', sa.String(length=30), server_default=sa.text("'RECEIVED'"), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('assigned_editor_id', sa.UUID(), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_editor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('internal_code')
    )
    op.create_table('user_sessions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('manuscript_id', sa.UUID(), nullable=True),
    sa.Column('screening_run_id', sa.UUID(), nullable=True),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('entity_type', sa.String(length=100), nullable=False),
    sa.Column('entity_id', sa.UUID(), nullable=True),
    sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip_address', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['manuscript_id'], ['manuscripts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_audit_logs_actor_time', 'audit_logs', ['actor_user_id', 'created_at'], unique=False)
    op.create_index('idx_audit_logs_event_time', 'audit_logs', ['event_type', 'created_at'], unique=False)
    op.create_index('idx_audit_logs_manuscript_time', 'audit_logs', ['manuscript_id', 'created_at'], unique=False)
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('manuscript_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('original_filename', sa.Text(), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('mime_type', sa.String(length=150), nullable=False),
    sa.Column('source_format', sa.String(length=10), nullable=False),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256_checksum', sa.String(length=64), nullable=False),
    sa.Column('extraction_status', sa.String(length=30), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('extraction_engine_version', sa.String(length=100), nullable=True),
    sa.Column('extraction_quality', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('extraction_summary_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('extraction_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('extraction_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uploaded_by', sa.UUID(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('supersedes_version_id', sa.UUID(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.CheckConstraint("extraction_status IN ('PENDING','PROCESSING','EXTRACTED','INCOMPLETE','FAILED')", name='ck_extraction_status'),
    sa.CheckConstraint("source_format IN ('docx','pdf','txt')", name='ck_source_format'),
    sa.CheckConstraint('extraction_quality BETWEEN 0 AND 100', name='ck_extraction_quality_range'),
    sa.CheckConstraint('file_size_bytes > 0', name='ck_file_size_positive'),
    sa.CheckConstraint('version_number > 0', name='ck_version_number_positive'),
    sa.ForeignKeyConstraint(['manuscript_id'], ['manuscripts.id'], ),
    sa.ForeignKeyConstraint(['supersedes_version_id'], ['document_versions.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('manuscript_id', 'idempotency_key'),
    sa.UniqueConstraint('manuscript_id', 'version_number')
    )
    op.create_table('manuscript_authors',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('manuscript_id', sa.UUID(), nullable=False),
    sa.Column('author_name', sa.String(length=300), nullable=False),
    sa.Column('author_order', sa.Integer(), nullable=False),
    sa.Column('author_email', sa.String(length=320), nullable=True),
    sa.Column('affiliation', sa.Text(), nullable=True),
    sa.CheckConstraint('author_order > 0', name='ck_author_order_positive'),
    sa.ForeignKeyConstraint(['manuscript_id'], ['manuscripts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('manuscript_id', 'author_order', deferrable=True, initially='DEFERRED')
    )
    op.create_table('document_sections',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('document_version_id', sa.UUID(), nullable=False),
    sa.Column('parent_section_id', sa.UUID(), nullable=True),
    sa.Column('block_id', sa.String(length=30), nullable=False),
    sa.Column('section_type', sa.String(length=30), nullable=False),
    sa.Column('heading_level', sa.Integer(), nullable=True),
    sa.Column('section_path', sa.Text(), nullable=True),
    sa.Column('heading_text', sa.Text(), nullable=True),
    sa.Column('paragraph_index', sa.Integer(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('text_content', sa.Text(), nullable=False),
    sa.Column('char_start', sa.BigInteger(), nullable=False),
    sa.Column('char_end', sa.BigInteger(), nullable=False),
    sa.Column('locator_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('extraction_warnings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.CheckConstraint('char_end >= char_start', name='ck_section_char_range'),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_section_id'], ['document_sections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_version_id', 'block_id'),
    sa.UniqueConstraint('document_version_id', 'paragraph_index')
    )
    op.create_index('idx_document_sections_version_page', 'document_sections', ['document_version_id', 'page_number'], unique=False)
    op.create_index('idx_document_sections_version_path', 'document_sections', ['document_version_id', 'section_path'], unique=False)
    op.create_index('idx_manuscripts_created_at', 'manuscripts', ['created_at'], unique=False)
    op.create_index('idx_manuscripts_assigned_editor', 'manuscripts', ['assigned_editor_id'], unique=False)
    op.create_index('idx_document_versions_extraction_status', 'document_versions', ['extraction_status'], unique=False)

    # Berkas versi bersifat immutable: kolom identitas berkas tidak boleh diubah dan baris tidak boleh dihapus.
    op.execute(IMMUTABLE_VERSION_FN)
    op.execute("""
        CREATE TRIGGER trg_document_versions_immutable
        BEFORE UPDATE OR DELETE ON document_versions
        FOR EACH ROW EXECUTE FUNCTION document_versions_immutable()
    """)
    # Audit log append-only bagi aplikasi. Role aplikasi produksi tidak boleh menjadi pemilik tabel
    # (pemilik dapat menonaktifkan trigger).
    op.execute(AUDIT_APPEND_ONLY_FN)
    op.execute("""
        CREATE TRIGGER trg_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_logs_no_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_append_only()
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_document_versions_immutable ON document_versions")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.execute("DROP FUNCTION IF EXISTS document_versions_immutable()")
    op.drop_index('idx_document_versions_extraction_status', table_name='document_versions')
    op.drop_index('idx_manuscripts_assigned_editor', table_name='manuscripts')
    op.drop_index('idx_manuscripts_created_at', table_name='manuscripts')
    op.drop_index('idx_document_sections_version_path', table_name='document_sections')
    op.drop_index('idx_document_sections_version_page', table_name='document_sections')
    op.drop_table('document_sections')
    op.drop_table('manuscript_authors')
    op.drop_table('document_versions')
    op.drop_index('idx_audit_logs_manuscript_time', table_name='audit_logs')
    op.drop_index('idx_audit_logs_event_time', table_name='audit_logs')
    op.drop_index('idx_audit_logs_actor_time', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_table('user_sessions')
    op.drop_table('manuscripts')
    op.drop_table('users')
    op.execute("DROP SEQUENCE IF EXISTS manuscript_code_seq")
