# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import AppSettings
from app.web_i18n import (
    humanize_markup_type_column_label,
    translate_humanized_text,
    translate_ui_text,
)
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


def test_markup_type_column_label_uses_plural_forms() -> None:
    assert humanize_markup_type_column_label("service", "ru") == "Услуги"
    assert humanize_markup_type_column_label("service", "en") == "Services"


@pytest.mark.parametrize(
    ("technical", "humanized"),
    [
        ("system_service_search", "Система поиска услуги"),
        ("system_task_processor", "Обработчик задач"),
        ("system_default", "Система"),
    ],
)
def test_humanized_system_markup_types_translate_in_russian(
    technical: str,
    humanized: str,
) -> None:
    assert translate_humanized_text(technical, "ru") == humanized


def test_service_level_builder_texts_are_localized_with_updated_copy() -> None:
    assert translate_ui_text("Service-level diagram", "ru") == "Диаграмма уровня услуг"
    assert (
        translate_ui_text(
            "High-level service map: service nodes aggregate all selected service graphs.",
            "ru",
        )
        == "Верхнеуровневая карта услуг и их взаимосвязей"
    )
    assert translate_ui_text("Graph {index}", "ru").format(index=1) == "Граф 1"
    assert translate_ui_text("Merge node", "ru") == "Узел слияния"
    assert translate_ui_text("Merge node #{index}", "ru").format(index=1) == "Узел слияния #1"
    assert translate_ui_text("Potential merge node", "ru") == "Потенциальный узел слияния"
    assert (
        translate_ui_text("Potential merge node #{index}", "ru").format(index=1)
        == "Потенциальный узел слияния #1"
    )
    assert translate_ui_text("Top overloaded entities", "ru") == "Топ перегруженных разметок"
    assert translate_ui_text("Entity", "ru") == "Разметка"


def test_catalog_detail_new_metadata_labels_are_localized_in_russian() -> None:
    assert translate_ui_text("Markup information", "ru") == "Информация по разметке"
    assert translate_ui_text("Service ID", "ru") == "ID услуги"
    assert translate_ui_text("Block-level diagram", "ru") == "Диаграмма уровня блоков"
    assert translate_ui_text("Show graph", "ru") == "Показать граф"
    assert translate_ui_text("Show reverse links", "ru") == "Показывать обратные связи"
    assert (
        translate_ui_text("Press Show graph to load procedure graph.", "ru")
        == "Нажмите «Показать граф», чтобы загрузить граф процедур."
    )
    assert (
        translate_ui_text("No procedure graph data available for this service.", "ru")
        == "Для этой услуги нет данных procedure_graph."
    )
    assert translate_ui_text("Block type", "ru") == "Тип блока"
    assert translate_ui_text("Starts", "ru") == "Старты"
    assert translate_ui_text("Branches", "ru") == "Ветвления"
    assert translate_ui_text("End blocks", "ru") == "End-блоки"
    assert translate_ui_text("Postpones", "ru") == "Отложенные"
    assert translate_ui_text("none", "ru") == "нет"
    assert translate_ui_text("Service block graph", "ru") == "Граф блоков услуги"


def test_catalog_health_texts_are_localized_in_russian() -> None:
    assert translate_ui_text("Analytics by teams", "ru") == "Аналитика по командам"
    assert translate_ui_text("Health problems", "ru") == "Проблемы здоровья"
    assert translate_ui_text("Only with problems", "ru") == "Только с проблемами"
    assert translate_ui_text("Gaming validity", "ru") == "Гейминг-валидность"
    assert translate_ui_text("Gaming marker problems", "ru") == "Проблемы гейминг-маркера"
    assert (
        translate_ui_text("No branches and no end blocks except postpone", "ru")
        == "Нет ветвлений и нет end-блоков, кроме postpone"
    )
    assert translate_ui_text("End blocks except postpone", "ru") == "End-блоки кроме postpone"
    assert translate_ui_text("Postpone end blocks", "ru") == "End-блоки postpone"
    assert (
        translate_ui_text("Gaming structure looks valid", "ru")
        == "Гейминг-структура выглядит валидной"
    )
    assert (
        translate_ui_text("Multiple graphs but no bot starts", "ru")
        == "Несколько графов, но нет bot/multi стартов"
    )
    assert translate_ui_text("No bot graphs found", "ru") == "Графы с ботом не найдены"
    assert translate_ui_text("Only bot graphs found", "ru") == "Только графы с ботом"
    assert (
        translate_ui_text("More than three graphs in markup", "ru")
        == "В разметке больше трёх графов"
    )
    assert translate_ui_text("Markup health markers", "ru") == "Маркеры здоровья разметки"
