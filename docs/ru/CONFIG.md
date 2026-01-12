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
  excalidraw_in_dir: "data/excalidraw_in"
  excalidraw_out_dir: "data/excalidraw_out"
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
  rebuild_token: ""
```

## Примечания к полям

- `s3.*`: настройки подключения к S3. Обязателен `bucket`. В `prefix` используйте завершающий слэш
  (например `markup/`), чтобы не захватывать лишние ключи. Для MinIO или кастомных endpoint используйте
  `endpoint_url` + `use_path_style: true`. Префикс также влияет на вычисление относительных путей в индексе.
- `auto_build_index`: строить индекс каталога при старте, если он отсутствует.
- `rebuild_index_on_start`: принудительная пересборка индекса при старте (полезно для S3).
- `generate_excalidraw_on_demand`: генерировать сцены Excalidraw из markup, если файл сцены отсутствует.
- `cache_excalidraw_on_demand`: сохранять сгенерированные сцены в `excalidraw_in_dir` для повторного использования.
- `invalidate_excalidraw_cache_on_start`: очищать `excalidraw_in_dir` при старте (только если включен
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
- `excalidraw_base_url`: URL или путь Excalidraw UI (например `/excalidraw`). При same-origin с Catalog
  сцена может быть внедрена через localStorage (рекомендуется для больших диаграмм). В противном случае
  используется `#json`, если URL достаточно короткий.
- `excalidraw_proxy_upstream`: опциональный upstream для проксирования Excalidraw через Catalog.
  Включает same-origin для локального демо (`/excalidraw`). При включении также проксируются статические
  ассеты Excalidraw (например `/assets/*`, `/manifest.webmanifest`).
- `excalidraw_proxy_prefix`: префикс пути для прокси Excalidraw.
- `excalidraw_max_url_length`: максимальная длина URL для `#json`, после чего требуется ручной импорт.

## Большие диаграммы

- Same-origin Excalidraw позволяет внедрение сцены через localStorage, обходя лимиты длины URL.
- Cross-origin Excalidraw использует `#json` только пока URL достаточно короткий; иначе пользователю нужно скачать и импортировать `.excalidraw`.
- Очень большие сцены могут превышать лимиты localStorage (часто ~5MB) или медленно рендериться; в этом случае используйте ручной импорт.

## Catalog UI

- В деталях диаграммы доступны скачивания `.excalidraw` и оригинального `markup.json`.

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
export CJM_CATALOG__S3__BUCKET="cjm-markup"
export CJM_CATALOG__S3__PREFIX="markup/"
export CJM_CATALOG__UI_TEXT_OVERRIDES='{"markup_type":"Тип разметки","service":"Услуга"}'
export CJM_CONFIG_PATH="config/catalog/app.s3.yaml"
```

## Бандл конфигов

- `config/catalog/app.s3.yaml` – локальный S3 демо (MinIO на `localhost:9000`).
- `config/catalog/app.docker.s3.yaml` – Docker демо конфиг, использующий S3 stub в сети `cjm-demo`.
- `config/catalog/app.k8s.yaml` – пример конфигурации для Kubernetes.
