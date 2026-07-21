import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_NAME = 300
MAX_NOTES = 100_000
MAX_FIELD_VALUE = 100_000
MAX_FIELD_LABEL = 100
MAX_CUSTOM_FIELDS = 200
MAX_TAGS = 200
MAX_HISTORY = 5
MAX_PAYLOAD_BYTES = 1 * 1024 * 1024  # 1 MiB per credential payload


def now_utc() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def nfkc_casefold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def strength_of(pw: str) -> str:
    """Return 'weak' | 'good' | 'strong' (matches frontend strengthOf)."""
    if not pw:
        return "weak"
    s = 0
    if len(pw) >= 12:
        s += 1
    if len(pw) >= 18:
        s += 1
    if re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw):
        s += 1
    if re.search(r"\d", pw):
        s += 1
    if re.search(r"[^a-zA-Z0-9]", pw):
        s += 1
    return "strong" if s >= 4 else "good" if s >= 2 else "weak"


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomField(DomainModel):
    id: str = Field(default_factory=new_uuid)
    label: str = Field(min_length=1, max_length=MAX_FIELD_LABEL)
    type: Literal["text", "secret"]
    value: str = ""
    order: int = 0

    @field_validator("value")
    @classmethod
    def _value_len(cls, v: str) -> str:
        if len(v) > MAX_FIELD_VALUE:
            raise ValueError("custom field value too long")
        return v


class PasswordHistoryEntry(DomainModel):
    id: str = Field(default_factory=new_uuid)
    password: str
    changed_at: str


class Credential(DomainModel):
    id: str = Field(default_factory=new_uuid)
    name: str
    url: Optional[str] = None
    username: Optional[str] = None
    password: str = ""
    category_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    notes: str = ""
    custom_fields: list[CustomField] = Field(default_factory=list)
    password_history: list[PasswordHistoryEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_utc)
    updated_at: str = Field(default_factory=now_utc)
    deleted_at: Optional[str] = None
    revision: int = 1

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        t = v.strip()
        if len(t) < 1 or len(t) > MAX_NAME:
            raise ValueError("name must be 1-300 chars after trim")
        return t

    @field_validator("notes")
    @classmethod
    def _notes(cls, v: str) -> str:
        if len(v) > MAX_NOTES:
            raise ValueError("notes too long")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_TAGS:
            raise ValueError("too many tags")
        return v

    @field_validator("custom_fields")
    @classmethod
    def _fields(cls, v: list[CustomField]) -> list[CustomField]:
        if len(v) > MAX_CUSTOM_FIELDS:
            raise ValueError("too many custom fields")
        seen = set()
        for f in v:
            key = nfkc_casefold(f.label)
            if key in seen:
                raise ValueError("duplicate custom field label")
            seen.add(key)
        return v

    @field_validator("password_history")
    @classmethod
    def _history(cls, v: list[PasswordHistoryEntry]) -> list[PasswordHistoryEntry]:
        if len(v) > MAX_HISTORY:
            raise ValueError("password history exceeds 5")
        return v

    @property
    def payload_bytes(self) -> int:
        return len(self.model_dump_json().encode("utf-8"))


class Category(DomainModel):
    id: str = Field(default_factory=new_uuid)
    name: str
    created_at: str = Field(default_factory=now_utc)
    updated_at: str = Field(default_factory=now_utc)
    revision: int = 1

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        t = v.strip()
        if len(t) < 1 or len(t) > 100:
            raise ValueError("category name 1-100")
        return t


class VaultSettings(DomainModel):
    language: Literal["id", "en"] = "id"
    tag_filter_mode: Literal["and", "or"] = "and"
    default_sort: dict = Field(default_factory=lambda: {"field": "name", "direction": "asc"})
    page_size: Literal[25, 50, 100] = 50
    warning_acknowledgements: list[str] = Field(default_factory=list)


class VaultPayload(DomainModel):
    credentials: list[Credential] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    settings: VaultSettings = Field(default_factory=VaultSettings)


class TagRenameRequest(DomainModel):
    source: str
    target: str


# Validation helpers ----------------------------------------------------------

AMBIGUOUS_CODEPOINTS = set("Il1O0o|\\`'\"")


def validate_payload_size(payload: VaultPayload) -> None:
    for credential in payload.credentials:
        if credential.payload_bytes > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"credential {credential.id} exceeds the {MAX_PAYLOAD_BYTES}-byte limit"
            )
    total = len(canonical_bytes(payload))
    if total > MAX_PAYLOAD_BYTES * 64:  # whole-vault soft guard
        raise ValueError("vault payload too large")


def canonical_bytes(payload: VaultPayload) -> bytes:
    from .canonical import canonical_json

    return canonical_json(payload).encode("utf-8")
