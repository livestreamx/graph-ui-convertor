# CJM UI Convertor

Round-trip converter between CJM markup graphs and Excalidraw scenes with deterministic layout and metadata for lossless reconstruction.

## Quick start

```bash
make bootstrap             # create .venv, install Poetry + deps
open Docker Desktop or start Colima
cp examples/markup/*.json data/markup/
make demo                  # convert markup -> Excalidraw + start UIs
# In browser: open Catalog (http://localhost:8080/catalog) and Excalidraw proxy (http://localhost:8080/excalidraw)
# Import from data/excalidraw_in, edit, export to data/excalidraw_out
make convert-from-ui       # rebuild markup from exported Excalidraw

# Catalog UI (local)
cjm pipeline build-all
cjm catalog serve --config config/catalog/app.yaml
# Open http://localhost:8080/catalog
```

## Commands (Typer CLI)

- `cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in`
- `cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip`
- `cjm validate <path>` to sanity-check markup or Excalidraw JSON.
- `cjm catalog build-index --config config/catalog/app.yaml`
- `cjm catalog serve --host 0.0.0.0 --port 8080 --config config/catalog/app.yaml`
- `cjm pipeline build-all` (convert + index build; config defaults to `config/catalog/app.yaml`)

## Project layout

- `app/` – CLI entrypoint (Typer).
- `domain/` – models, ports, use-cases (hexagonal core).
- `adapters/filesystem/` – JSON IO for markup/Excalidraw.
- `adapters/layout/` – deterministic grid layout engine.
- `examples/markup/` – sample markup JSON inputs.
- `docs/FORMAT.md` – mapping + metadata schema.
- `docs/CONFIG.md` – catalog configuration schema and examples.
- `docs/K8S.md` – Kubernetes deployment notes and manifests.
- `config/catalog/` – catalog config variants (local/docker/k8s).
- `docker/catalog/` – Catalog UI Dockerfile.
- `docker/compose.demo.yaml` – local demo composition (catalog + excalidraw).
- `data/` – default runtime IO folders (created by `make dirs`).
- `tests/` – pytest suite (round-trip, metadata checks).

## Architecture (hexagonal)

- Domain = pure conversion logic and data models.
- Ports = `domain/ports/*` contracts for layout and repositories.
- Adapters = filesystem IO + Excalidraw scene + layout implementation.
- App = wiring only (CLI), no business logic.

## Round-trip contract

- All Excalidraw elements carry `customData.cjm` metadata.
- Stable IDs are derived via uuid5; do not change without a migration plan.
- Layout is deterministic; manual UI moves are preserved but not re-applied on rebuild.
- Start/End markers have fixed sizes (180x90), labels and edge bindings.

## Development

- Python `>=3.14,<3.15`, Poetry `2.2.x`.
- Lint/format/typecheck: `make fmt` / `make lint`.
- Tests: `make test`.
- Pre-commit: `pre-commit install` (config in `.pre-commit-config.yaml`).
- E2E (Playwright): `poetry run playwright install` to fetch browsers; tests skip if browsers are missing.

## Conversion notes

- Layout: per-procedure grid with topological ordering; start markers left with extra offset, end markers right (or below if no space); blocks within a level reordered to reduce crossings; procedures placed left→right in JSON order and connected with arrows if no explicit cross-procedure edges.
- Metadata: stored under `customData.cjm` with `schema_version`, `procedure_id`, `block_id`, `edge_type`, `role`, `markup_type`. See `docs/FORMAT.md`.
- Arrows: bound to blocks/markers/frames (startBinding/endBinding) so they follow elements; branch arrows get slight vertical offsets to reduce overlap.
- Text fit: block/marker labels auto-shrink to stay within shapes; single start → `START`, multiple → global `START #N`.
- Best effort: user-added blocks/text inside a frame become new blocks; arrows labeled/metadata as `branch` are ingested into `branches`.

## Contributor workflow (LLM-friendly)

1. Update domain logic first, keep adapters thin.
2. Add/adjust tests for any behavioral changes.
3. Run `pytest` (or `make test`) immediately after edits.
4. Update `docs/FORMAT.md` if metadata shape changes.

## Limitations

- Relies on Excalidraw JSON export/import; no network services.
- Uses deterministic layout; manual repositioning in UI is preserved but not re-applied on rebuild.

## Catalog UI workflow

1. Build scenes + index: `cjm pipeline build-all`.
2. Open the catalog: `cjm catalog serve` and visit `/catalog`.
3. Download `.excalidraw`, edit in Excalidraw UI, export `.excalidraw`.
4. Upload via the Catalog detail page, then click “Convert back”.
