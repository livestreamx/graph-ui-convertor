# CJM UI Convertor

Round-trip converter between CJM markup graphs and Excalidraw scenes with deterministic layout and metadata for lossless reconstruction.

## Quick start

```bash
make bootstrap             # create .venv, install Poetry + deps
open Docker Desktop or start Colima
cp examples/markup/*.json data/markup/
make demo                  # convert markup -> Excalidraw + start UI (default: http://localhost:5010)
# In browser: import from data/excalidraw_in, edit, export to data/excalidraw_out
make convert-from-ui       # rebuild markup from exported Excalidraw
```

## Commands (Typer CLI)

- `cjm convert to-excalidraw --input-dir data/markup --output-dir data/excalidraw_in`
- `cjm convert from-excalidraw --input-dir data/excalidraw_out --output-dir data/roundtrip`
- `cjm validate <path>` to sanity-check markup or Excalidraw JSON.

## Project layout

- `app/` – CLI entrypoint (Typer).
- `domain/` – models, ports, use-cases (hexagonal core).
- `adapters/filesystem/` – JSON IO for markup/Excalidraw.
- `adapters/layout/` – deterministic grid layout engine.
- `examples/markup/` – sample markup JSON inputs.
- `docs/FORMAT.md` – mapping + metadata schema.
- `data/` – default runtime IO folders (created by `make dirs`).
- `tests/` – pytest suite (round-trip, metadata checks).

## Development

- Python `>=3.14,<3.15`, Poetry `2.2.x`.
- Lint/format/typecheck: `make fmt` / `make lint`.
- Tests: `make test`.
- Pre-commit: `pre-commit install` (config in `.pre-commit-config.yaml`).

## Conversion notes

- Layout: per-procedure grid with topological ordering; start markers left with extra offset, end markers right (or below if no space); blocks within a level reordered to reduce crossings; procedures placed left→right in JSON order and connected with arrows if no explicit cross-procedure edges.
- Metadata: stored under `customData.cjm` with `schema_version`, `procedure_id`, `block_id`, `edge_type`, `role`, `finedog_unit_id`, `markup_type`. See `docs/FORMAT.md`.
- Arrows: bound to blocks/markers/frames (startBinding/endBinding) so they follow elements; branch arrows get slight vertical offsets to reduce overlap.
- Text fit: block/marker labels auto-shrink to stay within shapes; single start → `START`, multiple → global `START #N`.
- Best effort: user-added blocks/text inside a frame become new blocks; arrows labeled/metadata as `branch` are ingested into `branches`.

## Limitations

- Relies on Excalidraw JSON export/import; no network services.
- Uses deterministic layout; manual repositioning in UI is preserved but not re-applied on rebuild.
