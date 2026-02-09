# Конфигурация каталога

Catalog UI по умолчанию читает настройки из `config/catalog/app.s3.yaml` (или из пути, переданного через
`--config` / `CJM_CONFIG_PATH`). Все пути относительны рабочей директории процесса, если не указаны
абсолютные.

## Схема

```yaml
catalog:
  title: "CJM Catalog"
  s3:
    bucket: "cjm-markup"
    prefix: "markup/"
    region: "us-east-1"
    endpoint_url: ""
    access_key_id: ""
    secret_access_key: ""
    session_token: ""
    use_path_style: false
  diagram_format: "excalidraw"
  excalidraw_in_dir: "data/excalidraw_in"
  excalidraw_out_dir: "data/excalidraw_out"
  unidraw_in_dir: "data/unidraw_in"
  unidraw_out_dir: "data/unidraw_out"
  roundtrip_dir: "data/roundtrip"
  index_path: "data/catalog/index.json"
  auto_build_index: true
  rebuild_index_on_start: false
  generate_excalidraw_on_demand: true
  cache_excalidraw_on_demand: true
  invalidate_excalidraw_cache_on_start: true
  group_by:
    - "markup_type"
    - "custom.domain"
  title_field: "service_name"
  tag_fields:
    - "tags"
    - "custom.labels"
  sort_by: "title"
  sort_order: "asc"
  unknown_value: "unknown"
  ui_text_overrides:
    markup_type: "Тип разметки"
    service: "Услуга"
  excalidraw_base_url: "/excalidraw"
  excalidraw_proxy_upstream: "http://localhost:5010"
  excalidraw_proxy_prefix: "/excalidraw"
  excalidraw_max_url_length: 8000
  unidraw_base_url: ""
  unidraw_proxy_upstream: ""
  unidraw_proxy_prefix: "/unidraw"
  unidraw_max_url_length: 8000
  rebuild_token: ""
  procedure_link_path: ""
  block_link_path: ""
  service_link_path: ""
  team_link_path: ""
```

## Примечания к полям

- `s3.*`: настройки подключения к S3. Обязателен `bucket`. В `prefix` используйте завершающий слэш
  (например `markup/`), чтобы не захватывать лишние ключи. Для MinIO или кастомных endpoint используйте
  `endpoint_url` + `use_path_style: true`. Префикс также влияет на вычисление относительных путей в индексе.
- `auto_build_index`: строить индекс каталога при старте, если он отсутствует.
- `rebuild_index_on_start`: принудительная пересборка индекса при старте (полезно для S3).
- `diagram_format`: какой формат диаграмм обслуживает Catalog UI (`excalidraw` или `unidraw`).
- `generate_excalidraw_on_demand`: генерировать сцены из markup, если файл диаграммы отсутствует.
- `cache_excalidraw_on_demand`: сохранять сгенерированные сцены в активную `*_in_dir`.
- `invalidate_excalidraw_cache_on_start`: очищать активную `*_in_dir` при старте (только если включен
  `generate_excalidraw_on_demand`), чтобы сцены пересобирались на новом коде.
- `group_by`: список dot-path для группировки в списке каталога.
- `title_field`: dot-path для заголовка карточки. Иначе используется `service_name` или имя файла.
- `tag_fields`: dot-path, используемые для тегов.
- `criticality_level` / `team_id` / `team_name`: читаются из `finedog_unit_meta` для фильтров каталога;
  остальные ключи `finedog_unit_meta` показываются в метаданных карточки.
- `sort_by`: `title`, `updated_at`, `markup_type`, `finedog_unit_id` или любое настроенное поле.
- В элементах индекса хранится только `updated_at`.
- `unknown_value`: заглушка для отсутствующих полей.
- `ui_text_overrides`: опциональный словарь для подмены значений/ключей в Catalog UI.
  При установке через переменные окружения используйте JSON-объект.
- `rebuild_token`: пустое значение отключает `/api/rebuild-index`. Задайте секрет для включения.
- `procedure_link_path`: шаблон URL для ссылок на процедуры в Excalidraw/Unidraw (используйте `{procedure_id}`).
- `block_link_path`: шаблон URL для ссылок на блоки в Excalidraw/Unidraw (используйте `{block_id}` либо
  `{procedure_id}` + `{block_id}`).
- `service_link_path`: базовый URL для ссылок на сервисы в Excalidraw/Unidraw; параметр `unit_id`
  добавляется из `finedog_unit_id`.
- `team_link_path`: базовый URL для ссылок на команды в Excalidraw/Unidraw; параметр `team_id`
  добавляется из `finedog_unit_meta.team_id`.
- `excalidraw_base_url`: URL или путь Excalidraw UI (например `/excalidraw`). При same-origin с Catalog
  сцена может быть внедрена через localStorage (рекомендуется для больших диаграмм). В противном случае
  используется `#json`, если URL достаточно короткий.
- `excalidraw_proxy_upstream`: опциональный upstream для проксирования Excalidraw через Catalog.
  Включает same-origin для локального демо (`/excalidraw`). При включении также проксируются статические
  ассеты Excalidraw (например `/assets/*`, `/manifest.webmanifest`).
- `excalidraw_proxy_prefix`: префикс пути для прокси Excalidraw.
- `excalidraw_max_url_length`: максимальная длина URL для `#json`, после чего требуется ручной импорт.
- `unidraw_base_url`: абсолютный URL внешнего Unidraw UI. Обязателен при `diagram_format=unidraw`
  и задаётся через `CJM_CATALOG__UNIDRAW_BASE_URL`.
- `unidraw_proxy_upstream`: опциональный upstream для проксирования Unidraw через Catalog.
- `unidraw_proxy_prefix`: префикс пути для прокси Unidraw.
- `unidraw_max_url_length`: параметр для паритета с Excalidraw URL (пока не используется).

## Большие диаграммы

- Same-origin Excalidraw позволяет внедрение сцены через localStorage, обходя лимиты длины URL.
- Open-роут также использует cache-busting query-параметры и `fetch(..., { cache: "no-store" })`, чтобы снизить риск показа устаревшей сцены.
- Cross-origin Excalidraw использует `#json` только пока URL достаточно короткий; иначе пользователю нужно скачать и импортировать `.excalidraw`.
- Очень большие сцены могут превышать лимиты localStorage (часто ~5MB) или медленно рендериться; в этом случае используйте ручной импорт.

## Catalog UI

- В деталях диаграммы доступны скачивания `.excalidraw`/`.unidraw` и оригинального `markup.json`.
- На странице каталога есть отдельный раздел для кросс-командных диаграмм: можно выбрать несколько
  команд и открыть общий граф процедур на основе `procedure_graph` (`/catalog/teams/graph`,
  `/api/teams/graph`, `team_ids` поддерживает значения через запятую). В билдере доступен параметр
  `excluded_team_ids` для исключения команд из аналитики и расчета merge-nodes. На Step 4 действия
  теперь разбиты на два подраздела: диаграмма по процедурам (слева) и диаграмма по услугам (справа).
- В сборщике кросс-командного графа детали выбора доступны через подсказку рядом с заголовком;
  процедуры подсвечиваются по услугам, пересечения выделяются светло-красным.
- В Step 1 добавлен подраздел "Disable teams from analytics": отключенные команды полностью
  исключаются из метрик, расчета merge-nodes и внешних пересечений. Значения по умолчанию
  задаются через `catalog.builder_excluded_team_ids`
  (`CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS`: список через запятую, JSON-массив
  или bracket-формат вида `[team-forest]`).
  Если отключенная команда явно выбрана в "Teams to merge", для построения графа приоритет у выбора.
- В сборщике кросс-командного графа есть секция Feature flags: каждый флаг оформлен отдельной
  карточкой с кнопкой Enable/Disable; карточки имеют оконтовку как подразделы, при включении
  получают легкий зеленый оттенок, а кнопка переключается в темный стиль.
  Над карточками флагов добавлен отдельный подраздел настройки merge-узлов со слайдером
  `merge_node_min_chain_size` (`0..10`, шаг `1`, по умолчанию `1`).
  При построении графа автоматически выбрасываются промежуточные процедуры, если одновременно
  выполнены условия: нет START/END-маркеров (включая `postpone`), ровно одна входящая и одна
  исходящая связь, и узел не является merge-node.
  `merge_node_min_chain_size=0` полностью отключает поиск/подсветку узлов слияния.
  `merge_node_min_chain_size=1` оставляет текущее поведение (достаточно одной общей процедуры).
  Значения `>1` требуют непересекающиеся цепочки из как минимум `N` подряд идущих общих процедур;
  каждая такая цепочка считается/отображается как один merge-узел-репрезентант.
  Циклы не считаются merge-цепочками. Узлы-развилки/схлопывания (общая исходящая степень > 1 или
  входящая степень > 1) считаются границами и в цепочки для `N>1` не включаются.
  `merge_selected_markups` выключен по умолчанию и управляет режимом отображения выбранных
  разметок: при `true` графы мержатся по общим `procedure_id`, при `false` рендерятся as is
  отдельными компонентами. `merge_nodes_all_markups` включает расчет узлов слияния по всем
  доступным разметкам, при этом рисуются только выбранные команды.
  Счетчики графов в dashboard (`Graphs`, группировки графов) считаются по тому же merged
  procedure graph, который открывается/скачивается как итоговая командная диаграмма.
- На Step 3 после Merge рендерится dashboard из трех секций:
  `Graphs info` (распределение `markup_type`, уникальные графы, уникальные процедуры, покрытие bot/multi),
  `Service Integrity` (внутренние/внешние пересечения услуг, расщепления, доля целевого состояния)
  и `Risk Hotspots` (топ связывающих процедур и перегруженных услуг по узлам слияния/циклам/процедурам/блокам).
  Визуально это карточки, чтобы метрики было удобно скринить и разбирать на встречах.
  Drilldown по графам и пересечениям использует единый формат `team / service` с цветовой маркировкой
  команд, включая `Multi graphs` и табличную детализацию `Top linking procedures` по конкретным графам
  (`cross-entity`, `inbound deps`, `outbound deps`).
  В `Top overloaded entities` детализация выводит те же колонки по процедурам в порядке графа и
  добавляет breakdown по типам блоков (start/end-типы) с теми же цветами, что на диаграмме.
  Порядок и связи процедур в этой детализации считаются по тому же merged procedure graph payload,
  который используется для построения командной диаграммы.
  В числовых колонках таблиц dashboard доступна клиентская сортировка по клику на заголовок колонки,
  кроме детализации `Procedure-level breakdown (graph order, potential merges)`: в ней порядок
  фиксирован по depth-first проходу графа от стартовых процедур к конечным, а несвязные компоненты
  показываются отдельными группами (`Graph 1`, `Graph 2`, ...) так же, как на диаграмме.
  Для каждой процедуры выводятся оба маркера: порядковый `P#` и уровень `L#` (от вершины графа).
  В подразделах `Risk Hotspots` добавлены пояснения про приоритет ранжирования и источник расчета,
  чтобы метрики было проще интерпретировать и верифицировать.
- В блоке `External team overlaps` на уровне команды показываются четыре счетчика:
  `external → selected`, `selected → external`, `total` и `overlap %`.
  `overlap %` — доля уникальных `procedure_id` текущих выбранных команд, которые пересекаются
  с разметками конкретной внешней команды. Сумма двух направлений всегда равна `total`.
  В детализации команды показываются все услуги без внутреннего скролла. По умолчанию выводится
  топ-10 внешних команд, остальные раскрываются кнопкой `Show N more teams`.
- Скачивание общего графа добавляет выбранные `team_ids` в имя файла (например,
  `team-graph_alpha_beta.excalidraw`).
- Для `/api/teams/graph` и `/catalog/teams/graph/open` поддерживается `graph_level=service`:
  строится верхнеуровневая диаграмма услуг, где узлы агрегируют все выбранные графы одной услуги.
  Настройки merge (`merge_selected_markups`, `merge_nodes_all_markups`,
  `merge_node_min_chain_size`) учитываются на нижнем слое (граф процедур), после чего
  применяется агрегация на уровень услуг.

## Разрешение dot-path

Dot-path проходят по вложенным объектам raw markup JSON. Примеры:

- `custom.domain` соответствует `{ "custom": { "domain": "payments" } }`
- `finedog_unit_meta.unit_id` соответствует `{ "finedog_unit_meta": { "unit_id": "fd-01" } }`

Если путь отсутствует, используется `unknown_value`.

## Переопределение через окружение

Любые настройки можно переопределить переменными окружения с префиксом `CJM_` и `__` как разделителем
вложенности. Пример:

```bash
export CJM_CATALOG__EXCALIDRAW_BASE_URL="https://draw.example.com"
export CJM_CATALOG__DIAGRAM_FORMAT="unidraw"
export CJM_CATALOG__UNIDRAW_BASE_URL="https://unidraw.example.com"
export CJM_CATALOG__S3__BUCKET="cjm-markup"
export CJM_CATALOG__S3__PREFIX="markup/"
export CJM_CATALOG__UI_TEXT_OVERRIDES='{"markup_type":"Тип разметки","service":"Услуга"}'
export CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS="team-alpha,team-beta"
export CJM_CONFIG_PATH="config/catalog/app.s3.yaml"
```

## Локальные env-файлы

Локальные переопределения для демо лежат в `config/catalog/env.local` и подхватываются `make demo` / `make catalog-up`.
Если добавляете новую важную переменную `CJM_*` в конфиг приложения, обязательно прокиньте ее в `makefile` (`CATALOG_ENV_EXTRA` / `docker run -e ...`), иначе значение не попадет в Catalog UI внутри Docker.
Если запускаете приложение напрямую (без Docker), подключите файл перед запуском:

```bash
set -a
source config/catalog/env.local
set +a
cjm catalog serve --config config/catalog/app.s3.yaml
```

## Бандл конфигов

- `config/catalog/app.s3.yaml` – локальный S3 демо (MinIO на `localhost:9000`).
- `config/catalog/app.docker.s3.yaml` – Docker демо конфиг, использующий S3 stub в сети `cjm-demo`.
- `config/catalog/app.k8s.yaml` – пример конфигурации для Kubernetes.
