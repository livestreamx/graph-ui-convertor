# ruff: noqa: RUF001

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from fastapi import Request
from starlette.responses import Response

DEFAULT_UI_LANGUAGE: Final[str] = "en"
SUPPORTED_UI_LANGUAGES: Final[set[str]] = {"en", "ru"}
UI_LANGUAGE_QUERY_PARAM: Final[str] = "lang"
UI_LANGUAGE_COOKIE_NAME: Final[str] = "cjm_catalog_ui_lang"

_UI_LANGUAGE: ContextVar[str] = ContextVar("ui_language", default=DEFAULT_UI_LANGUAGE)

_RUSSIAN_TRANSLATIONS: Final[dict[str, str]] = {
    "Tool for viewing and analyzing service graphs": "Инструмент просмотра и анализа графов обслуживания",
    "Index JSON": "Индекс JSON",
    "Created by": "Создано",
    "Switch language": "Переключить язык",
    "Cross-team graph analytics": "Кросс-командная аналитика графов",
    "Get high-level graph analytics across multiple domain teams": "Сводная аналитика графов по нескольким доменным командам",
    "Open builder": "Открыть конструктор",
    "Search by title, tag, markup type": "Поиск по названию, тегу, типу разметки",
    "Criticality level": "Уровень критичности",
    "All levels": "Все уровни",
    "Team": "Команда",
    "All teams": "Все команды",
    "Active filters": "Активные фильтры",
    "Clear filters": "Сбросить фильтры",
    "Filter by group values inside each section.": "Фильтруйте по значениям групп в каждом разделе.",
    "scenes": "сцен",
    "Filter": "Фильтр",
    "Updated": "Обновлено",
    "View": "Открыть",
    "Back to catalog": "Назад в каталог",
    "Scene ID": "ID сцены",
    "Open the diagram": "Открыть диаграмму",
    "Get the diagram": "Получите диаграмму",
    "Open in Excalidraw or download both diagram formats for manual import and editing.": "Откройте в Excalidraw или скачайте оба формата диаграмм для ручного импорта и редактирования.",
    "Open Excalidraw": "Открыть Excalidraw",
    "Render graph": "Отрисовать граф",
    "Show graph": "Показать граф",
    "Service block graph": "Граф блоков услуги",
    "Fit graph": "Вписать граф",
    "Close": "Закрыть",
    "Press Render graph to load service graph.": "Нажмите «Отрисовать граф», чтобы загрузить граф услуги.",
    "Press Show graph to load service graph.": "Нажмите «Показать граф», чтобы загрузить граф услуги.",
    "Show reverse links": "Показывать обратные связи",
    "Loading graph...": "Загружаем граф...",
    "Failed to load graph data.": "Не удалось загрузить данные графа.",
    "Graph library did not load. Refresh the page and retry.": "Библиотека графа не загрузилась. Обновите страницу и повторите попытку.",
    "No block graph data available for this service.": "Для этой услуги нет данных block_graph.",
    "Rendered {nodes} nodes and {edges} edges.": "Отрисовано узлов: {nodes}; связей: {edges}.",
    "Block": "Блок",
    "Block type": "Тип блока",
    "Nesting level": "Уровень вложенности",
    "not reachable from start": "недостижимо от стартового блока",
    "regular": "обычный",
    "Download .excalidraw": "Скачать .excalidraw",
    "Download .unidraw": "Скачать .unidraw",
    "External resources": "Внешние ресурсы",
    "Open service resource": "Открыть ресурс услуги",
    "Open team resource": "Открыть ресурс команды",
    "Scene will be generated on demand from markup.": "Сцена будет сгенерирована по запросу из разметки.",
    "Scene file not found in {dir_name}. Run build-all before opening.": "Файл сцены не найден в {dir_name}. Запустите build-all перед открытием.",
    "Scene is too large for URL sharing. Use Download + Import.": "Сцена слишком большая для передачи через URL. Используйте Скачать + Импорт.",
    "Scene is injected via local storage for same-origin Excalidraw.": "Сцена передается через localStorage для same-origin Excalidraw.",
    "If the scene does not load, import the downloaded file manually.": "Если сцена не загрузилась, импортируйте скачанный файл вручную.",
    "Markup information": "Информация по разметке",
    "Markup file": "Файл markup",
    "Excalidraw file": "Файл Excalidraw",
    "Unidraw file": "Файл Unidraw",
    "Service ID": "ID услуги",
    "No catalog index yet": "Индекс каталога пока не собран",
    "Build the catalog index to list available scenes. Run": "Соберите индекс каталога, чтобы увидеть доступные сцены. Выполните",
    "Try index API": "Проверить API индекса",
    "Opening {diagram_label}...": "Открытие {diagram_label}...",
    "Preparing the scene in local storage and redirecting.": "Подготавливаем сцену в localStorage и выполняем редирект.",
    "Failed to load the latest scene. Please retry.": "Не удалось загрузить последнюю версию сцены. Повторите попытку.",
    "Retry": "Повторить",
    "Reason": "Причина",
    "Cross-team graphs builder": "Конструктор кросс-командных графов",
    "Build combined procedure graphs across selected teams.": "Собирайте объединенные графы процедур по выбранным командам.",
    "Step 1. Select teams": "Шаг 1. Выберите команды",
    "Step 2. Feature flags": "Шаг 2. Флаги функциональности",
    "Step 3. Merge graphs": "Шаг 3. Объедините графы",
    "Step 4. Analyze graphs": "Шаг 4. Анализ графов",
    "Step 5. Get diagram": "Шаг 5. Получите диаграмму",
    "Merge selected teams": "Объединить выбранные команды",
    "Merge": "Объединить",
    "Merge ready": "Объединение готово",
    "Merge blocked": "Объединение заблокировано",
    "Waiting for input": "Ожидание ввода",
    "Procedure-level diagram": "Диаграмма уровня процедур",
    "Service-level diagram": "Диаграмма уровня услуг",
    "Detailed flow between procedures with analytics context from Step 4.": "Детальный поток между процедурами с контекстом аналитики из шага 4.",
    "High-level service map: service nodes aggregate all selected service graphs.": "Верхнеуровневая карта услуг и их взаимосвязей",
    "Select teams and click Merge. Status, analytics, and diagram actions appear in Steps 3-5.": "Выберите команды и нажмите «Объединить». Статус, аналитика и действия с диаграммой появятся на шагах 3-5.",
    "Analytics is unavailable for the selected graph set.": "Для выбранного набора графов аналитика недоступна.",
    "Resolve merge issues in Step 3 to unlock analytics.": "Исправьте проблемы объединения на шаге 3, чтобы открыть аналитику.",
    "Merge graphs in Step 3 to open analytics.": "Объедините графы на шаге 3, чтобы открыть аналитику.",
    "Merge graphs in Step 3 to enable diagram actions.": "Объедините графы на шаге 3, чтобы включить действия с диаграммой.",
    "Enable": "Включить",
    "Disable": "Выключить",
    "Enabled": "Включено",
    "Disabled": "Выключено",
    "Hide disabled teams": "Скрыть отключенные команды",
    "Disable teams": "Отключить команды",
    "Disable teams from analytics": "Отключить команды из аналитики",
    "Disabled teams are fully omitted from builder analytics.": "Отключенные команды полностью исключаются из аналитики конструктора.",
    "Once merged, status appears here; analytics opens in Step 4 and actions in Step 5.": "После объединения статус отображается здесь; аналитика откроется на шаге 4, а действия - на шаге 5.",
    "Merge completed. Continue to Step 4 for analytics and Step 5 for diagram actions.": "Объединение завершено. Перейдите к шагу 4 для аналитики и к шагу 5 для работы с диаграммой.",
    "Select at least one team to enable Merge.": "Выберите хотя бы одну команду, чтобы включить «Объединить».",
    "Merging selected graphs": "Объединяем выбранные графы",
    "Mapping shared nodes and building a cross-team dashboard...": "Сопоставляем общие узлы и строим кросс-командный дашборд...",
    "0: merge nodes are disabled.": "0: узлы слияния отключены.",
    "1: each shared procedure is a merge node.": "1: каждая общая процедура считается узлом слияния.",
    "{count}: only non-overlapping linear chains of {count}+ shared procedures are counted.": "{count}: учитываются только непересекающиеся линейные цепочки из {count}+ общих процедур.",
    "node": "узел",
    "nodes": "узлов",
    "Show fewer teams": "Показать меньше команд",
    "Show {count} more teams": "Показать еще {count} команд",
    "Click to collapse": "Нажмите, чтобы свернуть",
    "Click to expand": "Нажмите, чтобы развернуть",
    "Select teams to merge their procedure_graph into a single overview.": "Выберите команды, чтобы объединить их procedure_graph в единый обзор.",
    "Teams in graph": "Команды в графе",
    "teams": "команды",
    "markups merged": "объединено разметок",
    "markups": "разметок",
    "Select teams to build a combined graph.": "Выберите команды, чтобы построить объединенный граф.",
    "Builds a procedure-level graph using procedure_graph across selected teams.": "Строит граф уровня процедур на основе procedure_graph по выбранным командам.",
    "Teams to merge": "Команды для объединения",
    "Included in graph build and analytics.": "Участвуют в построении графа и аналитике.",
    "included teams": "включено команд",
    "Ignored in all builder metrics, merge-node detection, and overlap stats.": "Игнорируются во всех метриках конструктора, обнаружении merge-узлов и статистике пересечений.",
    "disabled teams": "отключено команд",
    "Tune how selected markups render and how merge nodes are detected.": "Настройте рендер выбранных разметок и правила обнаружения merge-узлов.",
    "Merge node chain threshold": "Порог цепочки merge-узлов",
    "How merge chain threshold works": "Как работает порог цепочки merge-узлов",
    "Selects the minimum size of consecutive shared procedures to count as one merge chain.": "Задает минимальную длину подряд идущих общих процедур, считаемых одной merge-цепочкой.",
    "0: merge node detection is fully disabled.": "0: обнаружение merge-узлов полностью отключено.",
    "1: each shared procedure is treated as a merge node.": "1: каждая общая процедура считается merge-узлом.",
    "N > 1: only non-overlapping strictly linear chains of at least N shared procedures are counted.": "N > 1: учитываются только непересекающиеся строго линейные цепочки минимум из N общих процедур.",
    "Cycles are excluded from merge-chain detection.": "Циклы исключаются из обнаружения merge-цепочек.",
    "Branch/fork and join procedures are treated as chain boundaries for N > 1.": "Узлы ветвления/слияния считаются границами цепочки при N > 1.",
    "Merge markups by shared nodes": "Объединять разметки по общим узлам",
    "How selected graphs render their components in according to shared nodes.": "Определяет, как выбранные графы рендерят компоненты по общим узлам.",
    "Render merge nodes from all available markups": "Показывать merge-узлы по всем доступным разметкам",
    "Merge nodes are derived from the full catalog, while only selected teams render.": "Merge-узлы вычисляются по всему каталогу, но рендерятся только выбранные команды.",
    "Graphs info": "Информация о графах",
    "Graphs": "Графы",
    "Unique graphs": "Уникальные графы",
    "Count of unique graphs from selected teams.": "Количество уникальных графов из выбранных команд.",
    "Detailed list is shown below.": "Подробный список показан ниже.",
    "Bot graphs": "Bot-графы",
    "Graphs with bot": "Графы с ботом",
    "Graphs where at least one procedure_id contains bot.": "Графы, где хотя бы один procedure_id содержит bot.",
    "Multi graphs": "Multi-графы",
    "Multichannel graphs": "Мультиканальные графы",
    "Graphs where at least one procedure_id contains multi.": "Графы, где хотя бы один procedure_id содержит multi.",
    "Unique procedures": "Уникальные процедуры",
    "Unique procedure_id count across all selected markups.": "Количество уникальных procedure_id по всем выбранным разметкам.",
    "Graphs and intersections details": "Детализация графов и их пересечений",
    "Grouped by markup or by unique merged-markup combination, ranked by graph count.": "Группировка по разметке или по уникальной комбинации объединенных разметок с ранжированием по числу графов.",
    "Potential merges only: markups are rendered separately because Merge markups by shared nodes is disabled.": "Только потенциальные объединения: разметки отображаются отдельно, потому что «Объединять разметки по общим узлам» отключено.",
    "No graphs detected for selected markups.": "Для выбранных разметок графы не обнаружены.",
    "Markup types": "Типы разметки",
    "Total selected markups split by markup_type.": "Распределение выбранных разметок по markup_type.",
    "Procedure mix": "Состав процедур",
    "Share among all procedures in selected markups by procedure_id substring: bot, multi, and everything else is employee procedures.": "Доля среди всех процедур выбранных разметок по подстрокам procedure_id: bot, multi, остальные считаются employee-процедурами.",
    "Bot procedures": "Bot-процедуры",
    "Multichannel procedures": "Мультиканальные процедуры",
    "Employee procedures": "Процедуры сотрудника",
    "Markup self-sufficiency": "Самодостаточность разметок",
    "Internal overlap markups": "Разметки с внутренними пересечениями",
    "Markups that share at least one procedure with another selected markup.": "Разметки, которые делят хотя бы одну процедуру с другой выбранной разметкой.",
    "External overlap markups": "Разметки с внешними пересечениями",
    "Markups that intersect with at least one markup from teams outside selection.": "Разметки, пересекающиеся хотя бы с одной разметкой из внешних команд.",
    "Split markups": "Разделенные разметки",
    "Markups with more than one disconnected component in their procedure graph.": "Разметки с более чем одной несвязной компонентой в графе процедур.",
    "Target markups": "Целевые разметки",
    "Markups without overlaps with other markups and without disconnected parts.": "Разметки без пересечений с другими разметками и без разрывов на компоненты.",
    "External team overlaps": "Пересечения с внешними командами",
    "Teams outside selection are ranked by total merge intersections with a split by dependency direction: external team depends on selected teams, and selected teams depend on external team. Click a team row to view service-level details.": "Внешние команды ранжируются по общему числу merge-пересечений с разбиением по направлению зависимостей: внешняя команда зависит от выбранных, и выбранные зависят от внешней. Нажмите строку команды для деталей на уровне сервисов.",
    "No intersections with teams outside the selection.": "Нет пересечений с командами вне выбранного набора.",
    "Risk hotspots": "Зоны риска",
    "Top linking procedures": "Топ высокосвязных процедур",
    "Rank by cross-entity reuse and dependency fan-in/fan-out in merged procedure_graph data. Click a row to inspect per-graph dependency impact for the same procedure.": "Рейтинг по использованию в разных разметках и входящим/исходящим зависимостям в объединенных данных procedure_graph. Нажмите строку, чтобы посмотреть влияние зависимостей по графам для этой процедуры.",
    "Ranking priority: cross-entity reuse -> total dependencies (incoming + outgoing) -> incoming -> outgoing.": "Приоритет ранжирования: использование в разных разметках -> все зависимости (входящие + исходящие) -> входящие -> исходящие.",
    "Procedure": "Процедура",
    "Graph-level breakdown": "Разбивка по графам",
    "No procedure-level data.": "Нет данных на уровне процедур.",
    "Top overloaded entities": "Топ перегруженных разметок",
    "Rank by structural risk in merged procedure_graph: shared-node merges with other entities, cycles, procedure volume, then block volume.": "Рейтинг по структурному риску в объединенном procedure_graph: слияния по общим узлам с другими сущностями, циклы, объем процедур, затем объем блоков.",
    "Rank by structural risk in merged procedure_graph: shared-node merges with other markups, cycles, procedure volume, then block volume.": "Рейтинг по структурному риску в объединенном procedure_graph: слияния по общим узлам с другими разметками, циклы, объем процедур, затем объем блоков.",
    "Click a row for per-procedure breakdown.": "Нажмите строку для детализации по процедурам.",
    "In breakdown, Links is the sum of incoming and outgoing unique procedure links for each procedure.": "В детализации «Links» — это сумма входящих и исходящих уникальных связей процедур для каждой процедуры.",
    "With Merge markups by shared nodes disabled, merge metrics are shown as potential merges.": "Когда «Объединять разметки по общим узлам» отключено, merge-метрики показываются как потенциальные.",
    "Ranking priority: merges -> cycles -> procedures -> blocks. These metrics are computed directly from graph structure and block lists.": "Приоритет ранжирования: слияния -> циклы -> процедуры -> блоки. Эти метрики считаются напрямую по структуре графа и спискам блоков.",
    "Entity": "Разметка",
    "Markups": "Появляется в разметках",
    "Cross-markup": "Пересекающихся разметок",
    "Inbound deps": "Входящих зависимостей",
    "Outbound deps": "Исходящих зависимостей",
    "Count": "Количество",
    "Real merges": "Реальные слияния",
    "Potential merges": "Потенциальные слияния",
    "Graph {index}": "Граф {index}",
    "Merge node": "Узел слияния",
    "graph": "граф",
    "graphs": "графов",
    "potential": "узел",
    "potentials": "узлов",
    "Intersection node breakdown": "Разбивка по узлам пересечений",
    "Potential intersection node breakdown": "Разбивка по потенциальным узлам пересечений",
    "Merge node #{index}": "Узел слияния #{index}",
    "Potential merge node": "Потенциальный узел слияния",
    "Potential merge node #{index}": "Потенциальный узел слияния #{index}",
    "External -> selected": "Внешние -> выбранные",
    "Selected -> external": "Выбранные -> внешние",
    "Total": "Итого",
    "Overlap %": "Пересечение %",
    "Procedures": "Процедуры",
    "Merges": "Слияния",
    "Cycles": "Циклы",
    "Blocks": "Блоки",
    "Procedure-level breakdown (graph order)": "Разбивка по процедурам (порядок в графе)",
    "Procedure-level breakdown (graph order, potential merges)": "Разбивка по процедурам (порядок в графе, потенциальные слияния)",
    "Cycle": "Цикл",
    "Links": "Связи",
    "yes": "да",
    "no": "нет",
    "No service-level data.": "Нет данных на уровне сервисов.",
}

_HUMANIZE_RU_TRANSLATIONS: Final[dict[str, str]] = {
    "markup_type": "Тип разметки",
    "criticality_level": "Уровень критичности",
    "team_id": "Команда",
    "team_name": "Название команды",
    "service": "Услуга",
    "system_service_search": "Система поиска услуги",
    "system_task_processor": "Обработчик задач",
    "system_default": "Система",
    "unknown": "неизвестно",
    "yes": "да",
    "no": "нет",
}

_HUMANIZE_EN_TRANSLATIONS: Final[dict[str, str]] = {
    "service": "Service",
    "system_service_search": "Service Search System",
    "system_task_processor": "Task Processor",
    "system_default": "Default System",
    "unknown": "Unknown",
}
_MARKUP_TYPE_COLUMN_RU_TRANSLATIONS: Final[dict[str, str]] = {
    "service": "Услуги",
    "system_service_search": "Системы поиска услуг",
    "system_task_processor": "Обработчики задач",
    "system_default": "Системы",
    "unknown": "Неизвестные",
}
_MARKUP_TYPE_COLUMN_EN_TRANSLATIONS: Final[dict[str, str]] = {
    "service": "Services",
    "system_service_search": "Service Search Systems",
    "system_task_processor": "Task Processors",
    "system_default": "Default Systems",
    "unknown": "Unknown",
}

_LANGUAGE_ICONS: Final[dict[str, str]] = {
    "en": "🇬🇧",
    "ru": "🇷🇺",
}

_LANGUAGE_LABELS: Final[dict[str, str]] = {
    "en": "English",
    "ru": "Русский",
}


@dataclass(frozen=True)
class UILocalizer:
    language: str

    @property
    def alternate_language(self) -> str:
        return "ru" if self.language == "en" else "en"

    @property
    def language_icon(self) -> str:
        return _LANGUAGE_ICONS[self.language]

    @property
    def alternate_language_icon(self) -> str:
        return _LANGUAGE_ICONS[self.alternate_language]

    @property
    def language_label(self) -> str:
        return _LANGUAGE_LABELS[self.language]

    @property
    def alternate_language_label(self) -> str:
        return _LANGUAGE_LABELS[self.alternate_language]

    def t(self, key: str, **kwargs: object) -> str:
        template = translate_ui_text(key, self.language)
        if not kwargs:
            return template
        values = {field: str(value) for field, value in kwargs.items()}
        try:
            return template.format(**values)
        except KeyError:
            return template

    def js(self, keys: list[str]) -> dict[str, str]:
        return {key: self.t(key) for key in keys}


def normalize_ui_language(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    lang = raw.replace("_", "-").split("-", 1)[0]
    if lang in SUPPORTED_UI_LANGUAGES:
        return lang
    return None


def resolve_ui_language(request: Request) -> str:
    requested = normalize_ui_language(request.query_params.get(UI_LANGUAGE_QUERY_PARAM))
    if requested is not None:
        return requested

    cookie_lang = normalize_ui_language(request.cookies.get(UI_LANGUAGE_COOKIE_NAME))
    if cookie_lang is not None:
        return cookie_lang

    accept_language = request.headers.get("accept-language", "")
    for part in accept_language.split(","):
        candidate = normalize_ui_language(part.split(";", 1)[0])
        if candidate is not None:
            return candidate
    return DEFAULT_UI_LANGUAGE


def build_localizer(request: Request) -> UILocalizer:
    return UILocalizer(language=resolve_ui_language(request))


def build_language_switch_url(request: Request, target_language: str) -> str:
    lang = normalize_ui_language(target_language) or DEFAULT_UI_LANGUAGE
    params: list[tuple[str, str]] = []
    if request.url.path in {"/catalog", "/catalog/teams/graph"}:
        for key, value in request.query_params.multi_items():
            if key == UI_LANGUAGE_QUERY_PARAM:
                continue
            params.append((key, value))
    params.append((UI_LANGUAGE_QUERY_PARAM, lang))
    query = urlencode(params, doseq=True)
    if not query:
        return request.url.path
    return f"{request.url.path}?{query}"


def apply_ui_language_cookie(response: Response, language: str) -> None:
    response.set_cookie(
        key=UI_LANGUAGE_COOKIE_NAME,
        value=normalize_ui_language(language) or DEFAULT_UI_LANGUAGE,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        path="/",
    )


def set_active_ui_language(language: str) -> Token[str]:
    normalized = normalize_ui_language(language) or DEFAULT_UI_LANGUAGE
    return _UI_LANGUAGE.set(normalized)


def reset_active_ui_language(token: Token[str]) -> None:
    _UI_LANGUAGE.reset(token)


def get_active_ui_language() -> str:
    return _UI_LANGUAGE.get()


def translate_ui_text(key: str, language: str) -> str:
    if language != "ru":
        return key
    return _RUSSIAN_TRANSLATIONS.get(key, key)


def translate_humanized_text(value: str, language: str) -> str:
    if language == "ru":
        return _HUMANIZE_RU_TRANSLATIONS.get(value, value)
    if language == "en":
        return _HUMANIZE_EN_TRANSLATIONS.get(value, value)
    return value


def humanize_markup_type_label(markup_type: str, language: str) -> str:
    normalized = str(markup_type or "").strip()
    if not normalized:
        return normalized
    translated = translate_humanized_text(normalized, language)
    if not translated:
        return translated
    return translated[:1].upper() + translated[1:]


def humanize_markup_type_column_label(markup_type: str, language: str) -> str:
    normalized = str(markup_type or "").strip()
    if not normalized:
        return normalized
    if " + " in normalized:
        parts = [part.strip() for part in normalized.split("+")]
        localized_parts = [humanize_markup_type_column_label(part, language) for part in parts]
        return " + ".join(item for item in localized_parts if item)
    if language == "ru":
        return _MARKUP_TYPE_COLUMN_RU_TRANSLATIONS.get(normalized, normalized)
    if language == "en":
        return _MARKUP_TYPE_COLUMN_EN_TRANSLATIONS.get(normalized, normalized)
    return normalized
