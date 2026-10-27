import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.constants import LANGUAGES, MANUSCRIPT_TYPES
from app.core.permissions import Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


# --- Auth & users ---------------------------------------------------------


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORM):
    id: uuid.UUID
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class MeOut(UserOut):
    permissions: list[str] = []


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: MeOut


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    role: Role
    password: str = Field(min_length=12, max_length=200)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=200)


class UserBrief(ORM):
    id: uuid.UUID
    full_name: str


# --- Manuscripts ----------------------------------------------------------


class AuthorIn(BaseModel):
    author_name: str = Field(min_length=1, max_length=300)
    author_email: EmailStr | None = None
    affiliation: str | None = Field(default=None, max_length=2000)


class AuthorOut(ORM):
    id: uuid.UUID
    author_name: str
    author_order: int
    author_email: str | None
    affiliation: str | None


class _ManuscriptFields(BaseModel):
    @field_validator("manuscript_type", check_fields=False)
    @classmethod
    def _type(cls, v: str | None) -> str | None:
        if v is not None and v not in MANUSCRIPT_TYPES:
            raise ValueError(f"tipe naskah tidak dikenal: {v}")
        return v

    @field_validator("language_code", check_fields=False)
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is not None and v not in LANGUAGES:
            raise ValueError(f"kode bahasa tidak dikenal: {v}")
        return v


class ManuscriptCreate(_ManuscriptFields):
    working_title: str = Field(min_length=1, max_length=1000)
    manuscript_type: str
    language_code: str = "id"
    submitted_at: datetime | None = None
    assigned_editor_id: uuid.UUID | None = None
    authors: list[AuthorIn] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ManuscriptUpdate(_ManuscriptFields):
    working_title: str | None = Field(default=None, min_length=1, max_length=1000)
    manuscript_type: str | None = None
    language_code: str | None = None
    submitted_at: datetime | None = None
    assigned_editor_id: uuid.UUID | None = None
    intake_status: str | None = None
    authors: list[AuthorIn] | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None


class VersionBrief(ORM):
    id: uuid.UUID
    version_number: int
    original_filename: str
    source_format: str
    file_size_bytes: int
    sha256_checksum: str
    extraction_status: str
    extraction_quality: Decimal | None
    uploaded_at: datetime


class ManuscriptListItem(ORM):
    id: uuid.UUID
    internal_code: str
    working_title: str
    manuscript_type: str
    language_code: str
    intake_status: str
    submitted_at: datetime | None
    created_at: datetime
    assigned_editor: UserBrief | None
    authors: list[AuthorOut]
    latest_version: VersionBrief | None = None
    incomplete_fields: list[str] = []
    latest_screening: dict[str, Any] | None = None
    latest_layout: dict[str, Any] | None = None


class ManuscriptOut(ManuscriptListItem):
    metadata_json: dict[str, Any]
    creator: UserBrief
    updated_at: datetime
    versions: list[VersionBrief]


# --- Versions -------------------------------------------------------------


class VersionOut(VersionBrief):
    manuscript_id: uuid.UUID
    mime_type: str
    extraction_engine_version: str | None
    extraction_summary_json: dict[str, Any]
    extraction_started_at: datetime | None
    extraction_completed_at: datetime | None
    uploader: UserBrief | None = None
    supersedes_version_id: uuid.UUID | None
    warnings: list[str] = []


class SectionOut(ORM):
    id: uuid.UUID
    block_id: str
    parent_section_id: uuid.UUID | None
    section_type: str
    heading_level: int | None
    section_path: str | None
    paragraph_index: int
    page_number: int | None
    text_content: str
    char_start: int
    char_end: int
    locator_json: dict[str, Any]


# --- Audit ----------------------------------------------------------------


class AuditOut(ORM):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_name: str | None = None
    manuscript_id: uuid.UUID | None
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    ip_address: Any | None
    created_at: datetime
