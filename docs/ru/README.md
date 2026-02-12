# Документация CJM UI Convertor

В этом каталоге собрана подробная техническая документация по round-trip конвертеру CJM markup <-> Excalidraw/Unidraw.

## Что покрывает документация

Проект включает:

- доменную логику конвертации с детерминированным layout;
- CLI-пайплайны для конвертации и валидации;
- Catalog UI для просмотра, открытия и скачивания диаграмм;
- индексирование каталога на основе S3.

## Локальный workflow

### 1. Bootstrap

```bash
make bootstrap
```

### 2. Конвертация markup в сцены

```bash
make convert-to-ui          # alias для make convert-to-excalidraw
make convert-to-unidraw
```

### 3. Запуск demo-стека

```bash
EXCALIDRAW_PORT=5010 make demo
# Catalog: http://localhost:8080/catalog
```

### 4. Обратная конвертация Excalidraw в markup

```bash
make convert-from-ui
```

## CLI команды

Основные команды:

- `cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in`
- `cjm convert to-unidraw --input-dir data/markup --output-dir data/unidraw_in`
- `cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip`
- `cjm validate <path>`
- `cjm catalog build-index --config config/catalog/app.s3.yaml`
- `cjm catalog serve --host 0.0.0.0 --port 8080 --config config/catalog/app.s3.yaml`
- `cjm pipeline build-all --config config/catalog/app.s3.yaml`

## Архитектурные правила

- `domain/`: чистые модели и бизнес-логика, без прямого IO.
- `domain/ports/`: интерфейсы для репозиториев и layout.
- `adapters/`: реализации портов (filesystem, excalidraw, layout, s3).
- `app/`: wiring и entrypoints (CLI/web), без доменной логики.

Конвертеры в `domain/services/` должны оставаться независимыми от filesystem/network API.

## Контракт round-trip

- Метаданные Excalidraw хранятся в `customData.cjm`.
- Метаданные Unidraw хранятся в `cjm`.
- Stable ID строятся через `uuid5`; смена схемы ID требует миграции.
- Маркеры Start/End и bindings стрелок входят в контракт round-trip.

Полное сопоставление полей см. в `docs/ru/FORMAT.md`.

## Catalog UI

- Доступно скачивание `.excalidraw` и `.unidraw`, плюс опциональный `Open Excalidraw`.
- Локализация UI поддерживает `en` и `ru` через query-параметр `lang` + cookie.
- Поведение для больших диаграмм, cross-team builder и feature flags описано в `docs/ru/CONFIG.md`.

## Качество и проверки

После изменений в коде запускайте:

```bash
make test
make lint
make fmt
```

Если меняется поведение конвертации или метаданные, обновляйте:

- `docs/en/FORMAT.md`
- `docs/ru/FORMAT.md`
- соответствующие тесты в `tests/`

## Карта документации

- `docs/ru/FORMAT.md`: форматы, mapping, метаданные, версионирование
- `docs/ru/CONFIG.md`: схема конфига, env overrides, поведение Catalog UI
- `docs/ru/K8S.md`: примеры деплоя в Kubernetes
- `docs/ru/c4/`: C4-диаграммы
- `docs/en/README.md`: английская точка входа
