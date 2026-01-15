# Catalog configuration

The Catalog UI reads settings from `config/catalog/app.s3.yaml` by default (or a custom path passed with
`--config` / `CJM_CONFIG_PATH`). All paths are relative to the process working directory unless
absolute.

## Schema

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
    markup_type: "Type"
    service: "Service"
  excalidraw_base_url: "/excalidraw"
  excalidraw_proxy_upstream: "http://localhost:5010"
  excalidraw_proxy_prefix: "/excalidraw"
  excalidraw_max_url_length: 8000
  unidraw_base_url: "/unidraw"
  unidraw_proxy_upstream: ""
  unidraw_proxy_prefix: "/unidraw"
  unidraw_max_url_length: 8000
  rebuild_token: ""
  procedure_link_template: ""
  block_link_template: ""
```

## Field notes

- `s3.*`: S3 connection settings. `bucket` is required. Use a trailing slash in `prefix`
  (for example `markup/`) to avoid matching unrelated keys. Use
  `endpoint_url` + `use_path_style: true` for MinIO or custom S3 endpoints.
  The prefix is also used to compute relative paths in the index.
- `auto_build_index`: Build the catalog index on startup if it is missing.
- `rebuild_index_on_start`: Force rebuilding the catalog index on startup (useful for S3).
- `diagram_format`: Choose which diagram flavor the Catalog UI serves (`excalidraw` or `unidraw`).
- `generate_excalidraw_on_demand`: Generate scenes from markup when a diagram file is missing.
- `cache_excalidraw_on_demand`: Persist generated scenes into the active `*_in_dir` for reuse.
- `invalidate_excalidraw_cache_on_start`: Remove cached scenes from the active `*_in_dir` on startup
  (only when `generate_excalidraw_on_demand` is enabled) so fresh diagrams are generated with the
  current code.
- `group_by`: List of dot-paths used to build nested groupings in the catalog list.
- `title_field`: Dot-path used for the card title. Falls back to `service_name` or file stem.
- `tag_fields`: Dot-paths used to populate tag pills.
- `criticality_level` / `team_id` / `team_name`: Read from `finedog_unit_meta` for catalog filters; other
  `finedog_unit_meta` keys are shown in the catalog metadata panel.
- `sort_by`: Can be `title`, `updated_at`, `markup_type`, `finedog_unit_id`, or any configured field.
- Catalog index items include `updated_at`.
- `unknown_value`: Placeholder when a field is missing.
- `ui_text_overrides`: Optional mapping used to replace raw field keys/values in the Catalog UI.
  When set via environment variables, pass a JSON object.
- `rebuild_token`: Empty disables `/api/rebuild-index`. Set to a shared secret to enable.
- `procedure_link_template`: URL template for procedure links in Excalidraw (use `{procedure_id}`).
- `block_link_template`: URL template for block links in Excalidraw (use `{block_id}`).
- `excalidraw_base_url`: Excalidraw UI URL or path (e.g. `/excalidraw`). When same-origin with the
  Catalog, the app can inject scenes via local storage (recommended for large diagrams). Otherwise
  it falls back to URL fragments when short enough.
- `excalidraw_proxy_upstream`: Optional upstream for proxying Excalidraw through the Catalog
  service. Enables same-origin flow in local demo (`/excalidraw` path). When set, the catalog
  also proxies Excalidraw static assets (for example `/assets/*`, `/manifest.webmanifest`).
- `excalidraw_proxy_prefix`: Path prefix used for proxying Excalidraw.
- `excalidraw_max_url_length`: Max URL length for `#json` fallback before switching to manual import.
- `unidraw_base_url`: Unidraw UI URL or path (e.g. `/unidraw`).
- `unidraw_proxy_upstream`: Optional upstream for proxying Unidraw through the Catalog service.
- `unidraw_proxy_prefix`: Path prefix used for proxying Unidraw.
- `unidraw_max_url_length`: Reserved for parity with Excalidraw URLs (currently unused).

## Large diagrams

- Same-origin Excalidraw allows scene injection via localStorage, bypassing URL length limits.
- Cross-origin Excalidraw uses `#json` only while the URL is short enough; otherwise users should download and import the `.excalidraw` file.
- Very large scenes can exceed browser localStorage limits (often ~5MB) or be slow to render; rely on the manual import flow in that case.

## Catalog UI

- Detail view includes downloads for `.excalidraw`/`.unidraw` and the original `markup.json`.

## Dot-path resolution

Dot paths traverse nested objects in the raw markup JSON. Examples:

- `custom.domain` resolves `{ "custom": { "domain": "payments" } }`
- `finedog_unit_meta.unit_id` resolves `{ "finedog_unit_meta": { "unit_id": "fd-01" } }`

If a path is missing, `unknown_value` is used.

## Environment overrides

Every setting can be overridden with environment variables using the prefix `CJM_` and `__` as the
nesting delimiter. Example:

```bash
export CJM_CATALOG__EXCALIDRAW_BASE_URL="https://draw.example.com"
export CJM_CATALOG__DIAGRAM_FORMAT="unidraw"
export CJM_CATALOG__S3__BUCKET="cjm-markup"
export CJM_CATALOG__S3__PREFIX="markup/"
export CJM_CATALOG__UI_TEXT_OVERRIDES='{"markup_type":"Type","service":"Service"}'
export CJM_CONFIG_PATH="config/catalog/app.s3.yaml"
```

## Local env files

Local demo overrides live in `config/catalog/env.local` and are loaded by `make demo` / `make catalog-up`.
When running the app directly (without Docker), source the file before starting:

```bash
set -a
source config/catalog/env.local
set +a
cjm catalog serve --config config/catalog/app.s3.yaml
```

## Bundled configs

- `config/catalog/app.s3.yaml` – local S3 demo (MinIO on `localhost:9000`).
- `config/catalog/app.docker.s3.yaml` – Docker demo config using S3 stub in the `cjm-demo` network.
- `config/catalog/app.k8s.yaml` – Kubernetes example paths.
