import csv
import io
from datetime import datetime, timezone
from typing import Optional

from ..domain.models import Credential, VaultPayload, nfkc_casefold

AMBIGUOUS_PREFIX = ("=", "+", "-", "@")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )


def _fmt(dt: Optional[str]) -> str:
    return dt or ""


def _escape_formula(value: str, escape_map: list) -> str:
    if value and value[0] in AMBIGUOUS_PREFIX:
        escape_map.append(True)
        return "'" + value
    return value


def build_spreadsheet(payload: VaultPayload) -> tuple[str, list[str]]:
    out = io.StringIO()
    w = csv.writer(out, delimiter=",", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    header = ["name", "url", "username", "password", "category", "tags", "favorite", "notes", "created_at", "updated_at", "custom_fields_json", "_localvault_escape_map"]
    w.writerow(header)
    escape_fields = []
    for c in payload.credentials:
        cat = _cat_name(payload, c.category_id)
        tags = ";".join(c.tags)
        cf_json = _custom_fields_json(c)
        row = [
            c.name, c.url or "", c.username or "", c.password, cat, tags,
            "true" if c.favorite else "false", c.notes, _fmt(c.created_at), _fmt(c.updated_at), cf_json, "",
        ]
        # formula mitigation (EXP-008)
        emap = []
        for idx in (0, 1, 2, 3, 4, 5, 7, 10):
            if row[idx] and row[idx][0] in AMBIGUOUS_PREFIX:
                emap.append(header[idx])
                row[idx] = "'" + row[idx]
        row[11] = ";".join(emap)
        w.writerow(row)
    return out.getvalue(), header


def build_chromium(payload: VaultPayload) -> str:
    out = io.StringIO()
    w = csv.writer(out, delimiter=",", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["name", "url", "username", "password", "note"])
    for c in payload.credentials:
        w.writerow([c.name, c.url or "", c.username or "", c.password, c.notes])
    return out.getvalue()


def build_firefox(payload: VaultPayload) -> str:
    out = io.StringIO()
    w = csv.writer(out, delimiter=",", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(["url", "username", "password", "httpRealm", "formActionOrigin", "guid", "timeCreated", "timeLastUsed", "timePasswordChanged"])
    for c in payload.credentials:
        epoch = _epoch_ms(c.updated_at)
        w.writerow([c.url or "", c.username or "", c.password, "", "", c.id, epoch, epoch, epoch])
    return out.getvalue()


def _cat_name(payload, cat_id):
    for c in payload.categories:
        if c.id == cat_id:
            return c.name
    return ""


def _custom_fields_json(c: Credential) -> str:
    import json

    arr = [{"label": f.label, "type": f.type, "value": f.value} for f in c.custom_fields]
    return json.dumps(arr, ensure_ascii=False, separators=(",", ":"))


def _epoch_ms(dt: Optional[str]) -> int:
    if not dt:
        return 0
    try:
        from datetime import datetime as dtmod

        d = dtmod.strptime(dt, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        return int(d.timestamp() * 1000)
    except Exception:
        return 0
