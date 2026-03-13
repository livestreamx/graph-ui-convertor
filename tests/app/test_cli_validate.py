from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.cli import app


def test_validate_accepts_markup_with_raw_control_characters(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    path.write_text(
        "{\n"
        '  "markup_type": "service",\n'
        '  "service_name": "Billing\tSupport",\n'
        '  "procedures": []\n'
        "}\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["validate", str(path)])

    assert result.exit_code == 0
    assert "Valid markup file" in result.stdout
