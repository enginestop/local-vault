import asyncio
import csv
import io
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..domain.models import now_utc
from ..domain.normalize import norm_url, norm_username

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ROWS = 100_000
DELIMITERS = [",", ";", "\t"]
LOCALVAULT_HEADERS = [
    "name",
    "url",
    "username",
    "password",
    "category",
    "tags",
    "favorite",
    "notes",
    "created_at",
    "updated_at",
    "custom_fields_json",
    "_localvault_escape_map",
]
CHROMIUM_HEADERS = ["name", "url", "username", "password", "note"]
FIREFOX_HEADERS = [
    "url",
    "username",
    "password",
    "httpRealm",
    "formActionOrigin",
    "guid",
    "timeCreated",
    "timeLastUsed",
    "timePasswordChanged",
]


def detect_delimiter(sample: str) -> str:
    candidates = []
    for delimiter in DELIMITERS:
        try:
            rows = list(
                csv.reader(
                    io.StringIO(sample),
                    delimiter=delimiter,
                    quotechar='"',
                    strict=True,
                )
            )
        except csv.Error:
            continue
        counts = [len(row) for row in rows[:20] if row]
        if not counts:
            continue
        modal = max(set(counts), key=counts.count)
        consistent = sum(count == modal for count in counts)
        candidates.append((delimiter, modal, consistent))
    if not candidates:
        return ","
    candidates.sort(
        key=lambda item: (item[1] > 1, item[2], item[1]), reverse=True
    )
    best_score = (candidates[0][1] > 1, candidates[0][2], candidates[0][1])
    tied = [
        item
        for item in candidates
        if (item[1] > 1, item[2], item[1]) == best_score
    ]
    return next(
        delimiter
        for delimiter in DELIMITERS
        if any(item[0] == delimiter for item in tied)
    )


def parse_csv_document(content: bytes, delimiter: str) -> tuple[list[str], list[dict]]:
    text = content.decode("utf-8-sig", errors="strict")
    reader = csv.reader(
        io.StringIO(text), delimiter=delimiter, quotechar='"', strict=True
    )
    rows = list(reader)
    if not rows:
        return [], []
    header = [column.strip() for column in rows[0]]
    if not any(header) or len(set(header)) != len(header):
        raise ValueError("CSV header is empty or contains duplicate columns")
    result = []
    for source in rows[1:]:
        if not source or all(value == "" for value in source):
            continue
        result.append(
            {
                column: source[index] if index < len(source) else ""
                for index, column in enumerate(header)
            }
        )
    return header, result


def parse_csv(content: bytes, delimiter: str) -> list[dict]:
    return parse_csv_document(content, delimiter)[1]


def detect_profile(header: list[str]) -> str:
    if header == LOCALVAULT_HEADERS:
        return "localvault"
    if all(column in header for column in CHROMIUM_HEADERS):
        return "chromium"
    if all(column in header for column in FIREFOX_HEADERS):
        return "firefox"
    return "generic"


def preset_columns(profile: str, header: list[str]) -> dict:
    if profile == "chromium":
        return {
            column: ("notes" if column == "note" else column)
            for column in header
            if column in CHROMIUM_HEADERS
        }
    if profile == "firefox":
        return {
            column: column
            for column in header
            if column in FIREFOX_HEADERS
        }
    if profile == "localvault":
        return {column: column for column in header if column in LOCALVAULT_HEADERS}
    return {column: column for column in header}


def normalize_for_dup(url: Optional[str], username: Optional[str]):
    return norm_url(url), norm_username(username)


@dataclass
class ImportPreview:
    id: str
    session_id: str
    base_vault_revision: int
    profile: str
    delimiter: str
    mapping: dict
    source_columns: list[str] = field(default_factory=list)
    source_rows: list[dict] = field(default_factory=list)
    valid_rows: list[dict] = field(default_factory=list)
    invalid_rows: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_utc)
    expires_at: str = field(default_factory=lambda: _future_timestamp(30))


class ImportPreviewStore:
    def __init__(self) -> None:
        self._previews: dict[str, ImportPreview] = {}
        self._lock = asyncio.Lock()

    async def put(self, preview: ImportPreview) -> None:
        async with self._lock:
            self._expire_locked()
            self._previews[preview.id] = preview

    async def get_owned(self, preview_id: str, session_id: str) -> ImportPreview:
        async with self._lock:
            self._expire_locked()
            preview = self._previews.get(preview_id)
            if preview is None:
                raise KeyError(preview_id)
            if preview.session_id != session_id:
                raise PermissionError(preview_id)
            return preview

    @asynccontextmanager
    async def owned(
        self, preview_id: str, session_id: str, *, remove_on_success: bool = False
    ):
        """Keep lookup, authorization, use, and optional removal under one lock."""
        async with self._lock:
            self._expire_locked()
            preview = self._previews.get(preview_id)
            if preview is None:
                raise KeyError(preview_id)
            if preview.session_id != session_id:
                raise PermissionError(preview_id)
            try:
                yield preview
            except Exception:
                raise
            else:
                if remove_on_success:
                    self._previews.pop(preview_id, None)

    async def remove_owned(self, preview_id: str, session_id: str) -> None:
        async with self._lock:
            preview = self._previews.get(preview_id)
            if preview is None:
                raise KeyError(preview_id)
            if preview.session_id != session_id:
                raise PermissionError(preview_id)
            self._previews.pop(preview_id, None)

    async def cleanup(self, active_session_ids: set[str]) -> None:
        async with self._lock:
            self._expire_locked()
            for preview_id, preview in list(self._previews.items()):
                if preview.session_id not in active_session_ids:
                    self._previews.pop(preview_id, None)

    def _expire_locked(self) -> None:
        now = datetime.now(timezone.utc)
        for preview_id, preview in list(self._previews.items()):
            try:
                expires_at = datetime.fromisoformat(
                    preview.expires_at.replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                expires_at = now
            if expires_at <= now:
                self._previews.pop(preview_id, None)


def _future_timestamp(minutes: int) -> str:
    future = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return future.strftime("%Y-%m-%dT%H:%M:%S.") + f"{future.microsecond // 1000:03d}Z"
