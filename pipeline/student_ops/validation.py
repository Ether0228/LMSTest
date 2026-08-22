"""Strict JSON contracts for AI candidates; never infer omitted fields."""
from __future__ import annotations

import json
from typing import Any


class CandidateSchemaError(ValueError):
    pass


def parse_json_candidate(text: str) -> Any:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise CandidateSchemaError("markdown_fence_invalid")
        value = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise CandidateSchemaError("json_invalid") from None


def require_object(value: Any, required: set[str], enums: dict[str, set[str]] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        raise CandidateSchemaError("object_fields_invalid")
    for field, values in (enums or {}).items():
        if value.get(field) not in values:
            raise CandidateSchemaError(f"enum_invalid:{field}")
    if any(not isinstance(value[field], str) or not value[field].strip() for field in required):
        raise CandidateSchemaError("object_value_invalid")
    return value


def require_list(value: Any, required: set[str], enums: dict[str, set[str]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CandidateSchemaError("list_invalid")
    return [require_object(item, required, enums) for item in value]
