# Format & Mapping

This project converts CJM markup JSON <-> Excalidraw/Unidraw scenes while preserving identifiers through metadata.

## Markup (input)

```json
{
  "markup_type": "service",
  "finedog_unit_id": "fd-01",
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
  - `::postpone`: issue is postponed (handoff between bot/agents/support lines).
  - `::turn_out`: unplanned exit (normally implicit from `branches` sources).
- `branches` – adjacency: key = source block, values = target blocks.
- `finedog_unit_meta.service_name` – markup display name.
- `finedog_unit_id` – external unit identifier for service links (string or integer; integers are coerced to strings).
- `procedure_graph` – adjacency between procedures.
- `block_graph` – adjacency between block ids; when provided, it becomes the primary source of block
  transitions and branch arrows are not rendered.
  - `branches` is used only to place implicit `turn_out` END markers based on its keys.

## Excalidraw (output)

- Frame per procedure (`type=frame`, `name=procedure_id`).
- Rectangle per block with text overlay.
- Blocks with `end_block_type=intermediate` use an orange fill.
- Ellipse markers for START/END.
- END markers are placed as separate nodes in the grid (like branch targets).
- END marker fill color varies by `end_type` for visual distinction (`postpone` is gray);
  `intermediate` END markers use a dashed outline.
- Arrows:
  - START -> block (label `start`, `edge_type=start`)
  - block -> END (label `end`, `edge_type=end`, `end_type=end|exit|all|intermediate|postpone|turn_out`)
  - `all`/`intermediate` in markup render a single END marker labeled `END & EXIT`.
  - `postpone` in markup renders an END marker labeled `POSTPONE`.
  - `turn_out` renders an END marker labeled `TURN OUT`.
  - branch arrows block -> block (label `branch`, `edge_type=branch`, used when no `block_graph`)
  - block graph arrows block -> block (label `graph`, `edge_type=block_graph`)
  - block graph cycles use `edge_type=block_graph_cycle` (dashed red, reverse arrow)
- Service name is rendered as a composite title header above the graph.
- Deterministic layout: grid per procedure, left-to-right, top-to-bottom.
- Cross-team graphs (`procedure_graph` with `is_intersection`) add a red "Merge nodes" panel.
  Group headers use the format `> [Team] Service x [Team] Service:`, followed by numbered lines
  `(N) Procedure name`. Merge nodes are highlighted with a red dashed oval and a numbered badge;
  in Unidraw the merge number circle also uses a dashed outline.

## Color scheme (tags, blocks, arrows)

Colors are consistent across Excalidraw and Unidraw outputs. Human-friendly cues are listed first,
hex values are shown for exact matching.

- Tags (end types): tags like `#end`, `#exit`, `#all`, `#intermediate`, `#postpone`, `#turn_out`
  (also accepted as `::end`, `::exit`, etc.) map to END marker fills and are used for best-effort
  import.
  - `end` -> red `#ff6b6b`
  - `exit` -> yellow `#ffe08a`
  - `all` -> orange `#ffb347`
  - `intermediate` -> orange `#ffb347` (dashed outline)
  - `postpone` -> neutral gray `#d9d9d9`
  - `turn_out` -> pale blue `#cfe3ff`
- Blocks: default block fill is light blue `#cce5ff` with a dark outline; blocks with
  `end_block_type=intermediate` use warm orange `#ffb347` to stand out.
- Arrows: default stroke is near-black `#1e1e1e` (solid); cycle arrows (`branch_cycle`,
  `procedure_cycle`, `block_graph_cycle`) are dashed red `#d32f2f` to emphasize loops (block cycles use
  width 1, procedure cycles use width 2).

## Unidraw (output)

- Scene header uses `type=unidraw` and `version=1`.
- Geometry is stored under `position`/`size` instead of flat `x`/`y`/`width`/`height`.
- Rectangles/ellipses are `type=shape` with `shape=1` (rectangle) or `shape=5` (ellipse).
- Arrows/lines are `type=line` with empty `points` and `tipPoints={start,end}` bindings.
- Styles are stored in a compact `style` dict (`fc`, `sc`, `tff`, `tfs`, `ta`, etc.).
- Text content is HTML (`<p>...</p>`).
- Metadata is stored under `cjm` on each element.
- Procedure intersections in Unidraw keep frame fill transparent; visual emphasis is done by
  red dashed merge highlighting.
- Service zones in Unidraw use a black dashed outer border; zone titles are rendered in black
  text inside a filled header rectangle that keeps the original zone color.

## Metadata

Excalidraw stores metadata under `customData.cjm`; Unidraw stores metadata under `cjm`.

Stored on every shape/arrow/text:

- `schema_version`: `"1.0"`
- `markup_type`
- `finedog_unit_id` (if present)
- `service_name` (if present)
- `criticality_level` (if present)
- `team_id` (if present)
- `team_name` (if present)
- `procedure_id`
- `block_id` (when applicable)
- `role`: `frame|block|block_label|start_marker|end_marker|edge`
- `role` (title header): `diagram_title_panel|diagram_title|diagram_title_rule`
- `edge_type`: `start|end|branch|block_graph|block_graph_cycle` (edges only)
- `end_type`: `end|exit|all|intermediate|postpone|turn_out` (end markers and end edges)
- `end_block_type`: `end|exit|all|intermediate|postpone|turn_out` (original markup type for the block)

This metadata enables round-trip even if elements are moved in UI.

## Best-effort ingestion from UI

- Rectangles/text inside a frame with label like `block_id_x` become blocks.
- Arrows with `edge_type=branch` in metadata, or label `branch`, become branch edges.
- START/END detected via metadata or arrows bound to marker ellipses.
- Procedure inferred from metadata, frame binding, or first seen block.

## Files & Extensions

- Markup inputs: `*.json` in `data/markup/`.
- Excalidraw scenes: `.excalidraw` or `.json` in `data/excalidraw_in` (export to `data/excalidraw_out` from UI).
- Unidraw scenes: `.unidraw` in `data/unidraw_in`.
- Round-trip outputs: `data/roundtrip/*.json`.

## Versioning

- Current metadata schema: `1.0`. Backward-compatible reads ignore unknown fields; forward-incompatible schema should bump this value.
