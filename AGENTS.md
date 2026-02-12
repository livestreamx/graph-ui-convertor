# Repository Guidelines

MVP: round-trip конвертер CJM разметки <-> Excalidraw/Unidraw. Python 3.14 + Poetry, CLI на Typer, гексагональная архитектура, layout-движок `GridLayoutEngine`.

## Agent Quick Checklist

- Прочитай `README.md` как короткий вход в проект, детали ищи в `docs/`.
- Для задач по структуре данных смотри `docs/en/FORMAT.md` и `docs/ru/FORMAT.md`.
- Для задач по Catalog UI/конфигам смотри `docs/en/CONFIG.md` и `docs/ru/CONFIG.md`.
- Сначала меняй domain-логику, затем адаптеры/веб-слой.
- Любые изменения поведения покрывай тестами.
- После правок в коде запускай `make test`, `make lint`, `make fmt`.

## Architecture Guardrails (LLM focus)

- Domain (`domain/`) - чистая логика и модели, без IO/CLI.
- Ports (`domain/ports/`) - интерфейсы для IO/лейаута.
- Adapters (`adapters/`) - имплементации портов (filesystem, excalidraw, unidraw, layout, s3).
- App (`app/`) - только wiring/CLI/web, без бизнес-логики.
- Конвертеры (`domain/services/`) - трансформация markup <-> excalidraw/unidraw; не трогать файл-систему напрямую.
- Взаимодействия только через порты, чтобы сохранять гексагональную архитектуру.

## Localization Guardrails (catalog-ui)

- Catalog UI поддерживает 2 языка: `en` и `ru`.
- Любой user-facing текст в `app/web/templates/` и фронтовом JS идет через централизованный i18n-слой (`app/web_i18n.py`, функция `t(...)`).
- Для JS-динамики передавай локализованные строки через шаблонный контекст (JSON-константы), не дублируй переводы.
- Переключение языка поддерживай через `lang` query-параметр + cookie; при правках ссылок/форм/HTMX сохраняй выбранную локаль.
- Если добавляешь новые поля для humanize/лейблов, обновляй словари локализации и покрывай оба языка тестами.

## Documentation Guardrails

- `README.md` держим компактным и только на английском.
- Детальные инструкции и спецификации живут в `docs/en` и `docs/ru`.
- При изменениях форматов/контрактов обновляй синхронно `docs/en/FORMAT.md` и `docs/ru/FORMAT.md`.
- При изменениях Catalog UI/локализации обновляй `docs/en/CONFIG.md` и `docs/ru/CONFIG.md`.

## Project Structure

- `app/cli.py` - Typer CLI (`cjm convert ...`, `cjm catalog ...`, `cjm pipeline ...`).
- `domain/` - модели, порты, use-cases.
- `adapters/` - filesystem/excalidraw/unidraw/layout/s3 адаптеры.
- `examples/markup/` - пример входных markup файлов.
- `data/` - runtime IO (markup/excalidraw_in/excalidraw_out/unidraw_in/roundtrip).
- `tests/` - pytest (round-trip, layout, metadata, catalog).
- `makefile` - bootstrap/install/test/lint/fmt/convert/demo.

## Build & Run

- `make bootstrap` -> venv + Poetry install.
- `make convert-to-ui` -> markup -> `data/excalidraw_in`.
- `make convert-to-unidraw` -> markup -> `data/unidraw_in`.
- `EXCALIDRAW_PORT=5010 make demo` -> локальный demo stack.
- `make convert-from-ui` -> экспорт из UI (`data/excalidraw_out`) -> markup `data/roundtrip`.

## Conversion Logic (critical)

- Layout внутри процедуры: topological sort; start слева; end справа (или снизу по центру, если справа не помещается).
- Процедуры располагаются слева-направо в порядке JSON; межпроцедурные связи рисуются по данным графа.
- START/END овалы: `180x90`; при нескольких стартах используется глобальная нумерация `START #N`.
- Стрелки имеют `startBinding`/`endBinding` + `boundElements`; ветки получают небольшой `y`-offset для разведения.
- Текст блоков/маркеров авто-уменьшается, чтобы помещаться в фигуры.
- `customData.cjm` (Excalidraw) и `cjm` (Unidraw) - источник метаданных (`schema_version`, `procedure_id`, `block_id`, `edge_type`, `role`, ...).
- Stable ID строятся через `uuid5`; не менять схему ID без миграции.

## Testing Expectations

- Любые изменения кода требуют новых/обновленных тестов.
- После правок обязательно запускай `make test` (или `pytest`).
- При изменениях layout/стрелок фиксируй кейсы в `tests/` (позиции, роли, bindings).
- После изменений в коде запускай линтеры и форматтер: `make lint`, `make fmt`.

## Common Tasks

- Конвертация в Excalidraw: `make convert-to-ui`.
- Конвертация в Unidraw: `make convert-to-unidraw`.
- Обратная конвертация: `make convert-from-ui`.
- Локальный Catalog UI: `make s3-up && make s3-seed && cjm catalog serve --config config/catalog/app.s3.yaml`.
- Пересборка индекса: `cjm catalog build-index --config config/catalog/app.s3.yaml`.
