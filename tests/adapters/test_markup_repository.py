from __future__ import annotations

from pathlib import Path

from adapters.filesystem.markup_repository import FileSystemMarkupRepository


def test_markup_repository_loads_markup_with_raw_control_characters(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    path.write_text(
        "{\n"
        "  // copied from production catalog\n"
        '  "markup_type": "service",\n'
        '  "service_name": "Billing\tSupport",\n'
        '  "procedures": []\n'
        "}\n",
        encoding="utf-8",
    )

    document = FileSystemMarkupRepository().load_by_path(path)

    assert document.markup_type == "service"
    assert document.service_name == "Billing\tSupport"


def test_markup_repository_loads_markup_with_raw_newlines_in_strings(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    path.write_text(
        "{\n"
        '  "markup_type": "service",\n'
        '  "service_name": "Billing\n'
        'Support",\n'
        '  "procedures": []\n'
        "}\n",
        encoding="utf-8",
    )

    document = FileSystemMarkupRepository().load_by_path(path)

    assert document.markup_type == "service"
    assert document.service_name == "Billing\nSupport"
