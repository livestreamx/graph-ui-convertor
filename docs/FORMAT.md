# Format & Mapping

This project converts CJM markup JSON <-> Excalidraw scenes while preserving identifiers through metadata.

## Markup (input)

```json
{
  "finedog_unit_id": 12345,
  "markup_type": "service",
  "finedog_unit_meta": {
    "service_name": "Support Flow"
  },
  "procedures": [
    {
      "proc_id": "intake",
      "start_block_ids": ["block_a"],
      "end_block_ids": ["block_c::exit"],
      "branches": { "block_a": ["block_b"], "block_b": ["block_c"] }
    }
  ]
}
```

- `proc_id` – swimlane.
- `start_block_ids` – blocks with incoming START marker.
- `end_block_ids` – blocks with outgoing arrow to END marker. Suffixes:
  - `::end` (or no suffix): return to parent procedure.
  - `::exit`: terminate the whole process.
  - `::all`: end + exit.
  - `::intermediate`: same as `all`, but the block can still branch further.
- `branches` – adjacency: key = source block, values = target blocks.
- `finedog_unit_meta.service_name` – markup display name.

## Excalidraw (output)

- Frame per procedure (`type=frame`, `name=procedure_id`).
- Rectangle per block with text overlay.
- Blocks with `end_block_type=intermediate` use an orange fill.
- Ellipse markers for START/END.
- END markers are placed as separate nodes in the grid (like branch targets).
- END marker fill color varies by `end_type` for visual distinction.
- Arrows:
  - START -> block (label `start`, `edge_type=start`)
  - block -> END (label `end`, `edge_type=end`, `end_type=end|exit|all|intermediate`)
  - `all`/`intermediate` in markup render a single END marker labeled `END & EXIT`.
  - branch arrows block -> block (label `branch`, `edge_type=branch`)
- Deterministic layout: grid per procedure, left-to-right, top-to-bottom.

## Metadata (`customData.cjm`)

Stored on every shape/arrow/text:

- `schema_version`: `"1.0"`
- `finedog_unit_id`, `markup_type`
- `service_name` (if present)
- `procedure_id`
- `block_id` (when applicable)
- `role`: `frame|block|block_label|start_marker|end_marker|edge`
- `edge_type`: `start|end|branch` (edges only)
- `end_type`: `end|exit|all|intermediate` (end markers and end edges)
- `end_block_type`: `end|exit|all|intermediate` (original markup type for the block)

This metadata enables round-trip even if elements are moved in UI.

## Best-effort ingestion from UI

- Rectangles/text inside a frame with label like `block_id_x` become blocks.
- Arrows with `edge_type=branch` in metadata, or label `branch`, become branch edges.
- START/END detected via metadata or arrows bound to marker ellipses.
- Procedure inferred from metadata, frame binding, or first seen block.

## Files & Extensions

- Markup inputs: `*.json` in `data/markup/`.
- Excalidraw scenes: `.excalidraw` or `.json` in `data/excalidraw_in` (export to `data/excalidraw_out` from UI).
- Round-trip outputs: `data/roundtrip/*.json`.

## Versioning

- Current metadata schema: `1.0`. Backward-compatible reads ignore unknown fields; forward-incompatible schema should bump this value.
