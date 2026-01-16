from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppSettings
from app.web_main import create_app


def test_excalidraw_cache_invalidated_on_start(
    tmp_path: Path,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_in_dir.mkdir(parents=True)
    scene_path = excalidraw_in_dir / "demo.excalidraw"
    scene_path.write_text("{}", encoding="utf-8")

    settings = app_settings_factory(
        excalidraw_in_dir=excalidraw_in_dir,
        excalidraw_out_dir=tmp_path / "excalidraw_out",
        roundtrip_dir=tmp_path / "roundtrip",
        index_path=tmp_path / "catalog" / "index.json",
        auto_build_index=False,
        generate_excalidraw_on_demand=True,
        invalidate_excalidraw_cache_on_start=True,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/catalog")
        assert response.status_code == 200

    assert not scene_path.exists()
