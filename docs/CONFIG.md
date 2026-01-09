# Catalog configuration

The Catalog UI reads settings from `config/catalog/app.yaml` (or a custom path passed with
`--config` / `CJM_CONFIG_PATH`). All paths are relative to the process working directory unless
absolute.

## Schema

```yaml
catalog:
  title: "CJM Catalog"
  markup_dir: "data/markup"
  excalidraw_in_dir: "data/excalidraw_in"
  excalidraw_out_dir: "data/excalidraw_out"
  roundtrip_dir: "data/roundtrip"
  index_path: "data/catalog/index.json"
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
  excalidraw_base_url: "http://localhost:5010"
  excalidraw_proxy_upstream: ""
  excalidraw_proxy_prefix: "/excalidraw"
  excalidraw_max_url_length: 8000
  rebuild_token: ""
```

## Field notes

- `group_by`: List of dot-paths used to build nested groupings in the catalog list.
- `title_field`: Dot-path used for the card title. Falls back to `service_name` or file stem.
- `tag_fields`: Dot-paths used to populate tag pills.
- `sort_by`: Can be `title`, `updated_at`, `markup_type`, `finedog_unit_id`, or any configured field.
- `unknown_value`: Placeholder when a field is missing.
- `rebuild_token`: Empty disables `/api/rebuild-index`. Set to a shared secret to enable.
- `excalidraw_base_url`: Excalidraw UI URL or path (e.g. `/excalidraw`). When same-origin with the
  Catalog, the app can inject scenes via local storage (recommended for large diagrams). Otherwise
  it falls back to URL fragments when short enough.
- `excalidraw_proxy_upstream`: Optional upstream for proxying Excalidraw through the Catalog
  service. Enables same-origin flow in local demo (`/excalidraw` path). When set, the catalog
  also proxies Excalidraw static assets (for example `/assets/*`, `/manifest.webmanifest`).
- `excalidraw_proxy_prefix`: Path prefix used for proxying Excalidraw.
- `excalidraw_max_url_length`: Max URL length for `#json` fallback before switching to manual import.

## Dot-path resolution

Dot paths traverse nested objects in the raw markup JSON. Examples:

- `custom.domain` resolves `{ "custom": { "domain": "payments" } }`
- `finedog_unit_meta.unit_id` resolves `{ "finedog_unit_meta": { "unit_id": "fd-01" } }`

If a path is missing, `unknown_value` is used.

## Environment overrides

Every setting can be overridden with environment variables using the prefix `CJM_` and `__` as the
nesting delimiter. Example:

```bash
export CJM__CATALOG__EXCALIDRAW_BASE_URL="https://draw.example.com"
export CJM_CONFIG_PATH="config/catalog/app.yaml"
```

## Bundled configs

- `config/catalog/app.yaml` – local defaults (data/ paths).
- `config/catalog/app.docker.yaml` – Docker demo paths (`/data`).
- `config/catalog/app.k8s.yaml` – Kubernetes example paths.
