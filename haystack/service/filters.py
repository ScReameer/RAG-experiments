import re
from typing import Any

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def validate_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER_RE.match(normalized):
        msg = (
            f"{field_name} must start with an alphanumeric character and contain only "
            "letters, digits, '_', '-', '.', ':'"
        )
        raise ValueError(msg)
    return normalized


def eq_filter(field: str, value: Any) -> dict[str, Any]:
    return {"field": field, "operator": "==", "value": value}


def and_filters(*filters: dict[str, Any] | None) -> dict[str, Any] | None:
    conditions = [condition for condition in filters if condition]
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"operator": "AND", "conditions": conditions}


def scoped_filter(
    shop_id: str,
    *,
    document_id: str | None = None,
    extra_filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    validate_identifier(shop_id, field_name="shop_id")
    document_condition = (
        eq_filter("meta.document_id", validate_identifier(document_id, field_name="document_id"))
        if document_id
        else None
    )
    return and_filters(document_condition, extra_filters)
