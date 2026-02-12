# CJM UI Convertor Documentation

This directory contains the detailed technical documentation for the CJM markup <-> Excalidraw/Unidraw round-trip converter.

## Scope

The repository includes:

- Domain conversion logic with deterministic layout.
- CLI pipelines for conversion and validation.
- Catalog UI for browsing, opening, and exporting diagrams.
- S3-backed catalog indexing flow.

## Local Workflow

### 1. Bootstrap

```bash
make bootstrap
```

### 2. Convert markup to scenes

```bash
make convert-to-ui          # alias for make convert-to-excalidraw
make convert-to-unidraw
```

### 3. Run demo stack

```bash
EXCALIDRAW_PORT=5010 make demo
# Catalog: http://localhost:8080/catalog
```

### 4. Convert exported Excalidraw back to markup

```bash
make convert-from-ui
```

## CLI Reference

Primary commands:

- `cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in`
- `cjm convert to-unidraw --input-dir data/markup --output-dir data/unidraw_in`
- `cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip`
- `cjm validate <path>`
- `cjm catalog build-index --config config/catalog/app.s3.yaml`
- `cjm catalog serve --host 0.0.0.0 --port 8080 --config config/catalog/app.s3.yaml`
- `cjm pipeline build-all --config config/catalog/app.s3.yaml`

## Architecture Rules

- `domain/`: pure models and business logic, no direct IO.
- `domain/ports/`: interfaces for repositories/layout.
- `adapters/`: concrete implementations (filesystem, excalidraw, layout, s3).
- `app/`: wiring and entrypoints (CLI/web), no domain logic.

Keep converters in `domain/services/` independent from filesystem/network APIs.

## Round-Trip Contract

- Excalidraw metadata lives in `customData.cjm`.
- Unidraw metadata lives in `cjm`.
- Stable IDs are derived via `uuid5`; changing ID strategy requires migration.
- Start/End markers and arrow bindings are part of round-trip guarantees.

For full field-level mapping, see `docs/en/FORMAT.md`.

## Catalog UI Notes

- Catalog supports dual download (`.excalidraw` and `.unidraw`) and optional `Open Excalidraw`.
- UI localization supports `en` and `ru` via `lang` query parameter + cookie.
- Cross-team graph builder, large-diagram behavior, and feature flags are documented in `docs/en/CONFIG.md`.

## Quality Gates

Run after code changes:

```bash
make test
make lint
make fmt
```

When conversion metadata or behavior changes, update:

- `docs/en/FORMAT.md`
- `docs/ru/FORMAT.md`
- relevant tests under `tests/`

## Documentation Map

- `docs/en/FORMAT.md`: file formats, mapping, metadata, versioning
- `docs/en/CONFIG.md`: configuration schema, env overrides, Catalog behavior
- `docs/en/K8S.md`: deployment examples for Kubernetes
- `docs/en/c4/`: C4 architecture diagrams
- `docs/ru/README.md`: Russian entrypoint
