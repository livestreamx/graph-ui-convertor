# CJM UI Convertor

Round-trip converter between CJM markup graphs and Excalidraw/Unidraw scenes with deterministic layout and metadata for lossless reconstruction.

Documentation is mirrored in `docs/en` and `docs/ru`. Russian version is below.

## Quick start

```bash
make bootstrap             # create .venv, install Poetry + deps
open Docker Desktop or start Colima
make demo                  # seed S3 stub, start UIs (on-demand conversion)
# In browser: open Catalog (http://localhost:8080/catalog)
# Click “Open Excalidraw”, edit, export to data/excalidraw_out
make convert-from-ui       # rebuild markup from exported Excalidraw

# Catalog UI (local)
# Uses S3 stub config; ensure MinIO is running (make s3-up + make s3-seed)
cjm catalog serve --config config/catalog/app.s3.yaml
# Open http://localhost:8080/catalog
```

Set `CJM_CATALOG__DIAGRAM_FORMAT=unidraw` and provide `CJM_CATALOG__UNIDRAW_BASE_URL` (external Unidraw UI),
then run `make convert-to-unidraw` to work with Unidraw scenes.

## Commands (Typer CLI)

- `cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in`
- `cjm convert to-unidraw --input-dir data/markup --output-dir data/unidraw_in`
- `cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip`
- `cjm validate <path>` to sanity-check markup or Excalidraw JSON.
- `cjm catalog build-index --config config/catalog/app.s3.yaml`
- `cjm catalog serve --host 0.0.0.0 --port 8080 --config config/catalog/app.s3.yaml`
- `cjm pipeline build-all` (convert + index build; config defaults to `config/catalog/app.s3.yaml`)

## Project layout

- `app/` – CLI entrypoint (Typer).
- `domain/` – models, ports, use-cases (hexagonal core).
- `adapters/filesystem/` – JSON IO for markup/Excalidraw.
- `adapters/unidraw/` – JSON IO for Unidraw scenes.
- `adapters/layout/` – deterministic grid layout engine.
- `examples/markup/` – sample markup JSON inputs.
- `docs/en/FORMAT.md` – mapping + metadata schema.
- `docs/en/CONFIG.md` – catalog configuration schema and examples.
- `docs/en/c4/` – C4 diagrams (local + k8s) and rendered SVGs.
- `docs/en/K8S.md` – Kubernetes deployment notes and manifests.
- `docs/ru/` – Russian mirror of the documentation.
- `config/catalog/` – catalog config variants (local/docker/k8s).
- `docker/catalog/` – Catalog UI Dockerfile.
- `docker/compose.demo.yaml` – local demo composition (catalog + excalidraw + s3 stub).
- `data/` – default runtime IO folders (created by `make dirs`, includes `unidraw_in`).
- `tests/` – pytest suite (round-trip, metadata checks).

## Architecture (hexagonal)

- Domain = pure conversion logic and data models.
- Ports = `domain/ports/*` contracts for layout and repositories.
- Adapters = filesystem IO + Excalidraw scene + layout implementation.
- App = wiring only (CLI), no business logic.

## Round-trip contract

- Excalidraw elements carry `customData.cjm` metadata; Unidraw elements carry `cjm`.
- Stable IDs are derived via uuid5; do not change without a migration plan.
- Layout is deterministic; manual UI moves are preserved but not re-applied on rebuild.
- Start/End markers have fixed sizes (180x90), labels and edge bindings.

## Development

- Python `>=3.14,<3.15`, Poetry `2.2.x`.
- Lint/format/typecheck: `make fmt` / `make lint`.
- Tests: `make test`.
- Pre-commit: `pre-commit install` (config in `.pre-commit-config.yaml`).
- E2E (Playwright): `poetry run playwright install` to fetch browsers; tests skip if browsers are missing.
- Local S3 stub (MinIO) is started by `make demo` and configured via `config/catalog/app.s3.yaml`.
- Render C4 diagrams: `make c4-render` (outputs to `docs/en/c4/rendered` and `docs/ru/c4/rendered`).

## Conversion notes

- Layout: per-procedure grid with topological ordering; start markers left with extra offset, end markers right (or below if no space); blocks within a level reordered to reduce crossings; procedures placed left→right in JSON order and connected with arrows if no explicit cross-procedure edges.
- Metadata: stored under `customData.cjm` with `schema_version`, `procedure_id`, `block_id`, `edge_type`, `role`, `markup_type`. See `docs/en/FORMAT.md`.
- Arrows: bound to blocks/markers/frames (startBinding/endBinding) so they follow elements; branch arrows get slight vertical offsets to reduce overlap.
- Text fit: block/marker labels auto-shrink to stay within shapes; single start → `START`, multiple → global `START #N`.
- Best effort: user-added blocks/text inside a frame become new blocks; arrows labeled/metadata as `branch` are ingested into `branches`.

## Large diagrams

- Same-origin Excalidraw (via `/excalidraw` proxy) uses localStorage injection (`/catalog/{scene_id}/open`) to avoid URL length limits.
- Cross-origin Excalidraw falls back to `#json` URL only when shorter than `excalidraw_max_url_length`; otherwise use Download + Import.
- Very large scenes may exceed browser localStorage limits or be slow to load; use the manual import flow in that case.

## Contributor workflow (LLM-friendly)

1. Update domain logic first, keep adapters thin.
2. Add/adjust tests for any behavioral changes.
3. Run `pytest` (or `make test`) immediately after edits.
4. Update `docs/en/FORMAT.md` and `docs/ru/FORMAT.md` if metadata shape changes.

## Limitations

- Relies on Excalidraw JSON export/import; no network services.
- Uses deterministic layout; manual repositioning in UI is preserved but not re-applied on rebuild.

## Catalog UI workflow

1. Seed markup into S3 (local: `make s3-seed`).
2. Open the catalog: `cjm catalog serve` and visit `/catalog`.
3. Set `CJM_CATALOG__DIAGRAM_FORMAT=unidraw` and `CJM_CATALOG__UNIDRAW_BASE_URL` to switch the UI into Unidraw mode.
4. Open the diagram in Excalidraw/Unidraw or download `.excalidraw`/`.unidraw` and `markup.json` for manual import or review.
5. Export `.excalidraw` into `data/excalidraw_out`, then run `make convert-from-ui` to rebuild markup.

---

# CJM UI Convertor (Русская версия)

Круговой конвертер между CJM markup-графами и сценами Excalidraw/Unidraw с детерминированным лейаутом и метаданными для без потерь.

Документация зеркалируется в `docs/en` и `docs/ru`.

## Быстрый старт

```bash
make bootstrap             # создание .venv, установка Poetry + deps
запустите Docker Desktop или Colima
make demo                  # заполнение S3 stub, запуск UI (конвертация по запросу)
# В браузере: открыть Catalog (http://localhost:8080/catalog)
# Нажать “Open Excalidraw”, отредактировать, экспортировать в data/excalidraw_out
make convert-from-ui       # восстановить markup из экспортированного Excalidraw

# Catalog UI (локально)
# Использует конфиг S3 stub; убедитесь, что MinIO запущен (make s3-up + make s3-seed)
cjm catalog serve --config config/catalog/app.s3.yaml
# Открыть http://localhost:8080/catalog
```

Чтобы использовать Unidraw, задайте `CJM_CATALOG__DIAGRAM_FORMAT=unidraw`, укажите внешний URL через
`CJM_CATALOG__UNIDRAW_BASE_URL` и выполните `make convert-to-unidraw`.

## Команды (Typer CLI)

- `cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in`
- `cjm convert to-unidraw --input-dir data/markup --output-dir data/unidraw_in`
- `cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip`
- `cjm validate <path>` для проверки корректности markup или Excalidraw JSON.
- `cjm catalog build-index --config config/catalog/app.s3.yaml`
- `cjm catalog serve --host 0.0.0.0 --port 8080 --config config/catalog/app.s3.yaml`
- `cjm pipeline build-all` (конвертация + индекс; config по умолчанию `config/catalog/app.s3.yaml`)

## Структура проекта

- `app/` – CLI входная точка (Typer).
- `domain/` – модели, порты, use-cases (hexagonal core).
- `adapters/filesystem/` – JSON IO для markup/Excalidraw.
- `adapters/unidraw/` – JSON IO для Unidraw сцен.
- `adapters/layout/` – детерминированный grid layout engine.
- `examples/markup/` – примеры входных markup JSON.
- `docs/ru/FORMAT.md` – формат и схема метаданных.
- `docs/ru/CONFIG.md` – схема конфигурации каталога и примеры.
- `docs/ru/c4/` – C4 диаграммы (local + k8s) и SVG.
- `docs/ru/K8S.md` – заметки по Kubernetes и манифесты.
- `docs/en/` – английская версия документации.
- `config/catalog/` – варианты конфигурации каталога (local/docker/k8s).
- `docker/catalog/` – Dockerfile для Catalog UI.
- `docker/compose.demo.yaml` – локальный демо compose (catalog + excalidraw + s3 stub).
- `data/` – директории runtime IO (создаются `make dirs`, включает `unidraw_in`).
- `tests/` – pytest suite (round-trip, проверки метаданных).

## Архитектура (гексагональная)

- Domain = чистая логика конвертации и модели данных.
- Ports = `domain/ports/*` контракты для лейаута и репозиториев.
- Adapters = filesystem IO + Excalidraw scene + layout implementation.
- App = только wiring (CLI), без бизнес-логики.

## Контракт round-trip

- Элементы Excalidraw несут `customData.cjm`, элементы Unidraw — `cjm`.
- Stable IDs получаются через uuid5; не менять без плана миграции.
- Лейаут детерминированный; ручные перемещения в UI сохраняются, но не пересчитываются при rebuild.
- Маркеры Start/End имеют фиксированные размеры (180x90), подписи и биндинги стрелок.

## Разработка

- Python `>=3.14,<3.15`, Poetry `2.2.x`.
- Lint/format/typecheck: `make fmt` / `make lint`.
- Tests: `make test`.
- Pre-commit: `pre-commit install` (config в `.pre-commit-config.yaml`).
- E2E (Playwright): `poetry run playwright install` для загрузки браузеров; тесты пропускаются без браузеров.
- Локальный S3 stub (MinIO) запускается `make demo`, конфиг — `config/catalog/app.s3.yaml`.
- Если добавляете новую важную `CJM_*` переменную в конфиг приложения, прокидывайте ее в `makefile` для `docker run` (`CATALOG_ENV_EXTRA`), иначе в `make demo` значение не попадет в контейнер Catalog UI.
- Переопределение текстов Catalog UI: `CJM_CATALOG__UI_TEXT_OVERRIDES` (JSON-словарь).
- Рендер C4 диаграмм: `make c4-render` (вывод в `docs/en/c4/rendered` и `docs/ru/c4/rendered`).

## Примечания по конвертации

- Layout: per-procedure grid с топологическим порядком; start слева с доп. отступом, end справа (или снизу при нехватке места); блоки внутри уровня переупорядочиваются для уменьшения пересечений; процедуры размещаются слева направо в порядке JSON и соединяются стрелками при отсутствии межпроцедурных ребер.
- `block_graph`: при наличии задает основные переходы между блоками (ветки `branches` не рисуются); `branches` используется только для расстановки `turn_out` по ключам; порядок процедур берётся из `block_graph`, если `procedure_graph` пуст.
- Metadata: хранится в `customData.cjm` с `schema_version`, `procedure_id`, `block_id`, `edge_type`, `role`, `markup_type`. См. `docs/ru/FORMAT.md`.
- Arrows: привязываются к блокам/маркерам/фреймам (startBinding/endBinding), чтобы следовать элементам; ветки получают небольшой вертикальный offset для разведения.
- Text fit: подписи блоков/маркеров авто-уменьшаются, чтобы уместиться; один start → `START`, несколько → глобальный `START #N`.
- Best effort: пользовательские блоки/текст внутри фрейма становятся новыми блоками; стрелки с меткой/metadata `branch` добавляются в `branches`.
- Кросс-командные графы: для `is_intersection` добавляется красный блок "Узлы слияния" с группировкой
  `> [Команда] Услуга x [Команда] Услуга:` и строками `(N) Название процедуры`; узлы на графе имеют
  красный овал и номер в кружке (в Unidraw кружок номера пунктирный, а frame узла слияния без заливки).

## Большие диаграммы

- При same-origin Excalidraw (через прокси `/excalidraw`) используется инъекция сцены через localStorage (`/catalog/{scene_id}/open`), чтобы обойти лимиты длины URL.
- При cross-origin Excalidraw используется `#json` только если URL короче `excalidraw_max_url_length`; иначе нужен сценарий Download + Import.
- Очень большие сцены могут превышать лимиты localStorage или загружаться медленно; в таком случае используйте ручной импорт.

## Рабочий процесс для контрибьюторов (LLM-friendly)

1. Сначала обновляйте domain-логику, адаптеры держите тонкими.
2. Добавляйте/обновляйте тесты для любых изменений поведения.
3. Запускайте `pytest` (или `make test`) сразу после правок.
4. Обновляйте `docs/en/FORMAT.md` и `docs/ru/FORMAT.md`, если меняется структура метаданных.

## Ограничения

- Опираться на экспорт/импорт Excalidraw JSON; сетевые сервисы не используются.
- Лейаут детерминированный; ручное позиционирование в UI сохраняется, но не пересчитывается при rebuild.

## Сценарий работы через Catalog UI

1. Загрузите markup в S3 (локально: `make s3-seed`).
2. Откройте каталог: `cjm catalog serve` и перейдите на `/catalog`.
3. Используйте фильтры по критичности и команде (отображается `team_name`).
4. В каталоге есть отдельный раздел для кросс-командных графов (кнопка Open builder): перейдите на
   `/catalog/teams/graph`, выберите команды и нажмите Merge для построения общего графа
   на основе `procedure_graph`.
5. В Step 1 есть подраздел "Disable teams from analytics": отключенные команды полностью исключаются
   из метрик, расчета merge-nodes и внешних пересечений. Значения по умолчанию можно задать через
   `CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS` (список `finedog_unit_id` через запятую, JSON-массив
   или bracket-формат вроде `[team-forest]`).
6. В сборщике кросс-командного графа есть секция Feature flags: каждый флаг оформлен карточкой с
   оконтовкой как подразделом, кнопкой Enable/Disable и подсветкой активного состояния. При включении
   карточка получает легкий зеленый оттенок, а кнопка становится темной.
   При построении графа автоматически выбрасываются промежуточные процедуры, если одновременно
   выполнены условия: у процедуры нет START/END-блоков (включая `postpone`), у нее ровно одна
   входящая и одна исходящая связь, и она не является merge-node.
   `merge_selected_markups` выключен по умолчанию: при включении графы выбранных разметок мержатся по
   общим `procedure_id`, при выключении рендерятся as is отдельными компонентами.
   `merge_nodes_all_markups` включает расчет узлов слияния по всем доступным разметкам, при этом рисуются
   только выбранные команды. Счетчики графов в dashboard считаются по тому же merged graph, который
   формируется для открытия/скачивания диаграммы.
7. На Step 3 после Merge отображается dashboard из трех секций:
   `Graphs info` (распределение `markup_type`, уникальные графы, уникальные процедуры, bot/multi coverage),
   `Service Integrity` (внутренние/внешние пересечения услуг, расщепленные графы, доля целевого состояния)
   и `Risk Hotspots` (топ связывающих процедур и перегруженных услуг по узлам слияния/циклам/процедурам/блокам).
   Блоки сверстаны карточками для удобного скриншота и объяснения метрик на встречах.
   В плашках и drilldown для графов/пересечений используется единый формат `team / service` с цветовой
   маркировкой команд, включая списки `Multi graphs` и табличную детализацию `Top linking procedures`
   по конкретным графам (`cross-entity`, `inbound deps`, `outbound deps`).
   В `Top overloaded entities` детализация показывает эту же колонночную статистику на уровне процедур
   в порядке их размещения в графе, включая breakdown по типам блоков (start/end-типы) с теми же
   цветами, что и на диаграмме. Порядок и связи процедур считаются по тому же merged procedure graph
   payload, который используется для рендера командной диаграммы.
   В числовых колонках таблиц dashboard доступна сортировка по клику на заголовок, кроме
   детализации `Procedure-level breakdown (graph order, potential merges)`, где порядок фиксирован:
   по depth-first проходу графа от стартовых процедур к конечным с отдельными группами для несвязных
   компонент (`Graph 1`, `Graph 2`, ...) — так же, как на диаграмме. Для каждой процедуры показываются
   оба маркера: порядковый `P#` и уровень `L#` (от вершины графа).
   В `Risk Hotspots` у каждого подраздела есть краткое пояснение приоритетов ранжирования и источник
   вычислений для лучшей интерпретации и доверия к метрикам.
   В `External team overlaps` каждая внешняя команда показывает четыре счетчика:
   `external → selected`, `selected → external`, `total` и `overlap %`.
   `overlap %` — доля уникальных `procedure_id` выбранных команд, которые пересекаются
   с разметками конкретной внешней команды. Сумма двух направлений всегда равна `total`.
   В детализации по внешней команде показываются все услуги без внутреннего скролла.
   По умолчанию отображаются топ-10 внешних команд, остальные раскрываются кнопкой `Show N more teams`.
8. На Step 4 доступны два подраздела действий: слева диаграмма по процедурам, справа верхнеуровневая
   диаграмма по услугам. Для API/open-роутов уровень выбирается параметром `graph_level`
   (`procedure` по умолчанию, `service` для агрегации услуг).
9. При скачивании общего графа файл получает суффикс с `team_ids` (например,
   `team-graph_alpha_beta.excalidraw`).
10. Установите `CJM_CATALOG__DIAGRAM_FORMAT=unidraw` и `CJM_CATALOG__UNIDRAW_BASE_URL`, чтобы включить режим Unidraw.
11. Откройте диаграмму в Excalidraw/Unidraw или скачайте `.excalidraw`/`.unidraw` и `markup.json` для ручного импорта или проверки.
12. Экспортируйте `.excalidraw` в `data/excalidraw_out`, затем выполните `make convert-from-ui`.
13. При старте Catalog UI кэш `excalidraw_in` очищается, чтобы сцены пересобирались на текущем коде.
14. Локальные env-переопределения (включая шаблоны ссылок) лежат в `config/catalog/env.local`.

В карточках и деталях каталога отображается `updated_at`;.
