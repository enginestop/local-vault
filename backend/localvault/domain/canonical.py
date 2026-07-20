import json
from typing import Any

from .models import VaultPayload


def _sort_payload(obj: Any) -> Any:
    """Normalize array ordering before serialization (DAT-005)."""
    if isinstance(obj, dict):
        return {k: _sort_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return []
        first = obj[0]
        if isinstance(first, dict):
            if "id" in first and "order" not in first:
                # credentials, categories, tags(catalog), custom fields handled in VaultPayload
                return [_sort_payload(x) for x in obj]
        return [_sort_payload(x) for x in obj]
    return obj


def canonical_json(payload: VaultPayload) -> str:
    """Deterministic canonical JSON (DAT-005/006): UTF-8, sorted keys, no whitespace."""
    data = payload.model_dump(mode="json", exclude_none=False)
    data = _normalize_top(data)
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize_top(data: dict) -> dict:
    # Sort credentials by id
    if "credentials" in data and isinstance(data["credentials"], list):
        data["credentials"] = sorted(data["credentials"], key=lambda c: c["id"])
        for c in data["credentials"]:
            if "custom_fields" in c and isinstance(c["custom_fields"], list):
                c["custom_fields"] = sorted(
                    c["custom_fields"], key=lambda f: (f.get("order", 0), f["id"])
                )
            if "password_history" in c and isinstance(c["password_history"], list):
                c["password_history"] = sorted(
                    c["password_history"],
                    key=lambda h: (h.get("changed_at", ""), h["id"]),
                    reverse=True,
                )
    if "categories" in data and isinstance(data["categories"], list):
        data["categories"] = sorted(data["categories"], key=lambda c: c["id"])
    if "tags" in data and isinstance(data["tags"], list):
        data["tags"] = sorted([t for t in data["tags"] if isinstance(t, str)])
    if "settings" in data and isinstance(data["settings"], dict):
        pass
    return data
