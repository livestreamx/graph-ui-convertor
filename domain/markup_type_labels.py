from __future__ import annotations

_DISPLAY_MARKUP_TYPE_BY_TECHNICAL: dict[str, str] = {
    "service": "услуга",
    "system_service_search": "система поиска услуги",
    "system_task_processor": "обработчик задач",
    "system_default": "система",
}
_DISPLAY_MARKUP_TYPE_COLUMN_BY_TECHNICAL: dict[str, str] = {
    "service": "услуги",
    "system_service_search": "системы поиска услуг",
    "system_task_processor": "обработчики задач",
    "system_default": "системы",
}


def humanize_markup_type(markup_type: str | None) -> str:
    normalized = str(markup_type or "").strip()
    if not normalized:
        return normalized
    return _DISPLAY_MARKUP_TYPE_BY_TECHNICAL.get(normalized, normalized)


def humanize_markup_type_for_brackets(markup_type: str | None) -> str:
    humanized = humanize_markup_type(markup_type)
    if not humanized:
        return humanized
    return humanized[:1].upper() + humanized[1:]


def humanize_markup_type_for_column(markup_type: str | None) -> str:
    normalized = str(markup_type or "").strip()
    if not normalized:
        return normalized
    humanized = _DISPLAY_MARKUP_TYPE_COLUMN_BY_TECHNICAL.get(normalized, normalized)
    return humanized[:1].upper() + humanized[1:]
