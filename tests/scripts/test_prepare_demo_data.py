from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_prepare_demo_data_preserves_existing_markup_and_clears_generated_files(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    markup_dir = tmp_path / "data" / "markup"
    excalidraw_dir = tmp_path / "data" / "excalidraw_in"
    unidraw_dir = tmp_path / "data" / "unidraw_in"

    source_dir.mkdir(parents=True)
    markup_dir.mkdir(parents=True)
    excalidraw_dir.mkdir(parents=True)
    unidraw_dir.mkdir(parents=True)

    (source_dir / "corner_cases.json").write_text('{"id":"corner"}', encoding="utf-8")
    (source_dir / "basic.json").write_text('{"id":"basic"}', encoding="utf-8")
    (markup_dir / "stale.json").write_text('{"id":"stale"}', encoding="utf-8")
    (excalidraw_dir / "stale.excalidraw").write_text("{}", encoding="utf-8")
    (excalidraw_dir / "stale.excalidraw.lock").write_text("", encoding="utf-8")
    (unidraw_dir / "stale.unidraw").write_text("{}", encoding="utf-8")
    (unidraw_dir / "stale.unidraw.lock").write_text("", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [
            sys.executable,
            "scripts/prepare_demo_data.py",
            "--source-dir",
            str(source_dir),
            "--markup-dir",
            str(markup_dir),
            "--excalidraw-dir",
            str(excalidraw_dir),
            "--unidraw-dir",
            str(unidraw_dir),
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert sorted(path.name for path in markup_dir.glob("*.json")) == [
        "basic.json",
        "corner_cases.json",
        "stale.json",
    ]
    assert (markup_dir / "corner_cases.json").read_text(encoding="utf-8") == '{"id":"corner"}'
    assert (markup_dir / "stale.json").read_text(encoding="utf-8") == '{"id":"stale"}'
    assert not list(excalidraw_dir.iterdir())
    assert not list(unidraw_dir.iterdir())
