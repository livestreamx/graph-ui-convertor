# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import AppSettings
from app.web_i18n import translate_humanized_text
from tests.app.catalog_test_setup import build_catalog_test_context


def test_catalog_ui_language_switch_to_russian_and_cookie_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as context:
        ru_response = context.client.get("/catalog?lang=ru")
        assert ru_response.status_code == 200
        assert "Инструмент просмотра и анализа графов обслуживания" in ru_response.text
        assert "Индекс JSON" in ru_response.text
        assert "Кросс-командная аналитика графов" in ru_response.text
        assert 'href="/catalog?lang=en"' in ru_response.text

        persisted_response = context.client.get("/catalog")
        assert persisted_response.status_code == 200
        assert "Кросс-командная аналитика графов" in persisted_response.text


def test_catalog_open_and_team_graph_are_localized_in_russian(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as context:
        open_response = context.client.get(f"/catalog/{context.scene_id}/open?lang=ru")
        assert open_response.status_code == 200
        assert (
            "Не удалось загрузить последнюю версию сцены. Повторите попытку." in open_response.text
        )
        assert "Причина" in open_response.text
        assert "Подготавливаем сцену в localStorage и выполняем редирект." in open_response.text

        team_graph_response = context.client.get("/catalog/teams/graph?lang=ru")
        assert team_graph_response.status_code == 200
        assert "Шаг 1. Выберите команды" in team_graph_response.text
        assert "Шаг 5. Получите диаграмму" in team_graph_response.text
        assert "Отключить команды" in team_graph_response.text


def test_humanized_service_translates_to_usluga_in_russian() -> None:
    assert translate_humanized_text("service", "ru") == "Услуга"
