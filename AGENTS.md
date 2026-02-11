# Repository Guidelines

MVP: round-trip конвертер CJM разметки ↔ Excalidraw. Python 3.14 + Poetry, CLI на Typer, гексагональная архитектура, layout-движок GridLayoutEngine.

## Architecture Guardrails (LLM focus)

- Domain (`domain/`) — чистая логика и модели, без IO/CLI.
- Ports (`domain/ports/`) — интерфейсы для IO/лейаута.
- Adapters (`adapters/`) — имплементации портов (filesystem, excalidraw, layout).
- App (`app/`) — только wiring/CLI, без бизнес-логики.
- Конвертеры (`domain/services/`) — трансформация markup ↔ excalidraw; не трогать файл-систему напрямую.
- Взаимодействия только через порты, чтобы сохранять гексагональную архитектуру.

## Localization Guardrails (catalog-ui)

- Catalog UI поддерживает 2 языка: `en` и `ru`.
- Любой user-facing текст в `app/web/templates/` и фронтовом JS должен идти через централизованный i18n-слой (`app/web_i18n.py`, функция `t(...)`), а не хардкодиться строками.
- Для JS-динамики передавай локализованные строки через шаблонный контекст (JSON-константы), не дублируй переводы в нескольких местах.
- Переключение языка поддерживай через `lang` query-параметр + cookie; при правках ссылок/форм/HTMX учитывай сохранение выбранной локали.
- Если добавляешь новые поля для humanize/лейблов, обновляй словари локализации и покрывай оба языка тестами.
- Любые изменения UI, затрагивающие текст или поведение локали, синхронно документируй в `docs/en` и `docs/ru`.

## Project Structure

- `app/cli.py` — Typer CLI (`cjm convert to-excalidraw|from-excalidraw|validate`).
- `domain/` — модели, порты, use-cases; `convert_markup_to_excalidraw.py`, `convert_excalidraw_to_markup.py`.
- `adapters/` — `filesystem` (IO), `excalidraw` (scene), `layout/grid.py` (детерминированный лейаут).
- `examples/markup/` — `basic.json`, `complex_graph.json`, `graphs_set.json`.
- `data/` — runtime IO (markup/excalidraw_in/excalidraw_out/roundtrip).
- `tests/` — pytest round-trip и метаданные.
- `makefile` — bootstrap/install/test/lint/fmt/convert/demo; Poetry ставится в `.venv`.

## Build & Run

- `make bootstrap` → venv + Poetry install.
- `make convert-to-ui` → markup → `data/excalidraw_in`.
- `EXCALIDRAW_PORT=5010 make demo` → конверт + docker run UI.
- `make convert-from-ui` → экспорт из UI (`data/excalidraw_out`) → markup `data/roundtrip`.
- Lint/format/typecheck: `make fmt`, `make lint`. Tests: `make test`.

## Conversion Logic (важно для доработок)

- Layout внутри процедуры: топосорт, стартовые слева, children центруются по позициям целей для уменьшения пересечений/длины стрелок; end-овалы справа, если помещаются, иначе снизу по центру.
- Процедуры располагаются и соединяются слева-направо в порядке JSON; если есть межпроцедурные связи по блокам, они рисуются; иначе фреймы соединяются последовательно.
- START овалы 180x90, вынесены влево; если старт один — текст `START`, иначе глобальная нумерация `START #N`. END — аналогично справа/снизу, стрелка привязана.
- Стрелки имеют start/end bindings + boundElements, опираются на края элементов; ветки с небольшими offset по Y для разведения.
- Текст блоков/маркеров подгоняется по ширине/высоте с автоуменьшением шрифта.
- `customData.cjm` — основной слой метаданных (schema_version, procedure_id, block_id, edge_type, role и т.д.). Любые новые поля добавляй здесь же.
- stable id через uuid5; не меняй схему id без миграции, иначе нарушится round-trip.

## Coding Style & Tooling

- Python 3.14, Poetry 2.2.x, Pydantic v2, Typer, Rich, orjson, optional networkx.
- Linters: ruff, mypy (strict). Tests: pytest. Pre-commit: ruff/format/mypy hooks.
- ASCII по умолчанию, краткие комментарии только при необходимости.

## Testing Expectations

- Любые изменения кода требуют новых/обновленных тестов.
- После правок обязательно запускай `make test` или `pytest` с `pytest-cov` (контроль процента покрытия).
- При изменениях лейаута/стрелок фиксируй кейсы в `tests/` (позиции, роли, bindings).
- При изменениях приложения обновляй документацию в `docs/en` и `docs/ru`, а также русскую секцию `README.md`.
- После изменений в коде обязательно запускай линтеры (`make lint`).
- По завершению работ обязательно прогоняй линтеры/форматтеры (`make lint`, `make fmt`) и убеждайся, что код соответствует стандартам.
- Если при внесении новой логики покрытие кода падает, обязательно допокрой изменения тестами до восстановления/роста покрытия.

## Agent Notes

- Сцены для проверки: `data/excalidraw_in/*.excalidraw` генерятся `make convert-to-ui`.
- Docker UI порт по умолчанию 5010. Если порт занят — задавай `EXCALIDRAW_PORT`.
- При изменениях лейаута/стрелок убедись, что биндинги сохраняются и тесты зелёные (`pytest`).  
- Любые изменения кода должны сопровождаться тестовым покрытием и обязательным запуском тестов сразу после правок (`make test` или `pytest`).

## Common Tasks (LLM hints)

- Конвертация в UI: `make convert-to-ui` → `data/excalidraw_in`.
- Обратная конвертация: `make convert-from-ui` → `data/roundtrip`.
- Для новых форматов обновляй `docs/en/FORMAT.md`, `docs/ru/FORMAT.md` и тесты round-trip.
