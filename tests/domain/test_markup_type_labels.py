from __future__ import annotations

import pytest

from domain.markup_type_labels import humanize_markup_type, humanize_markup_type_for_brackets


@pytest.mark.parametrize(
    ("technical", "humanized"),
    [
        ("service", "услуга"),
        ("system_service_search", "система поиска услуги"),
        ("system_task_processor", "обработчик задач"),
        ("system_default", "система"),
    ],
)
def test_humanize_markup_type_known_values(technical: str, humanized: str) -> None:
    assert humanize_markup_type(technical) == humanized


def test_humanize_markup_type_preserves_unknown() -> None:
    assert humanize_markup_type("custom_type") == "custom_type"


def test_humanize_markup_type_for_brackets_capitalizes_first_letter() -> None:
    assert humanize_markup_type_for_brackets("service") == "Услуга"
