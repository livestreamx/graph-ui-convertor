# CJM UI Convertor

Round-trip converter between CJM markup graphs and Excalidraw/Unidraw scenes.

The project focuses on deterministic layout, lossless reconstruction, and a hexagonal architecture that keeps domain logic isolated from IO.

## Features

- Markup -> Excalidraw conversion with deterministic `GridLayoutEngine`.
- Excalidraw -> Markup reconstruction with metadata-driven round-trip.
- Unidraw export pipeline for parallel diagram workflows.
- Catalog UI for browsing, opening, and downloading generated diagrams.

## Quick Start

Prerequisites: Python `3.14`, Poetry `2.2.x`, Docker Desktop (or Colima) for demo services.

```bash
make bootstrap
make demo
# Open http://localhost:8080/catalog
# Export edited .excalidraw files to data/excalidraw_out
make convert-from-ui
```

For local Catalog UI without full demo stack:

```bash
make s3-up && make s3-seed
cjm catalog serve --config config/catalog/app.s3.yaml
```

## CLI (at a glance)

```bash
cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in
cjm convert to-unidraw --input-dir data/markup --output-dir data/unidraw_in
cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip
cjm validate <path>
cjm catalog build-index --config config/catalog/app.s3.yaml
cjm catalog serve --host 0.0.0.0 --port 8080 --config config/catalog/app.s3.yaml
cjm pipeline build-all --config config/catalog/app.s3.yaml
```

## Documentation

Detailed docs live in `docs/`:

- `docs/en/README.md` - full technical guide (architecture, workflows, commands)
- `docs/en/FORMAT.md` - format mapping and metadata contract
- `docs/en/CONFIG.md` - Catalog configuration and UI behavior
- `docs/en/K8S.md` - Kubernetes deployment examples
- `docs/ru/README.md` - Russian documentation index

## For LLM Agents

Agent-specific repository workflow and guardrails are in `AGENTS.md`.

## Development

```bash
make test
make lint
make fmt
```

## Security

See `SECURITY.md`.
