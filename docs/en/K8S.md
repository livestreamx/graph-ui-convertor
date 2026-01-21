# Kubernetes deployment guide (examples)

This project ships example manifests under `k8s/` for a two-service setup:

- Catalog UI (FastAPI + shared storage)
- Excalidraw (official container)

## Shared storage (RWX)

The catalog service reads/writes generated scenes and roundtrip outputs from a shared volume. Use a
ReadWriteMany (RWX) PVC and mount it at `/data` across all catalog replicas.

Example PVC: `k8s/pvc.yaml`.

## S3-backed markup (required)

Markup JSON files are sourced from S3 in Kubernetes. Configure the `catalog.s3` settings in the
ConfigMap. With `generate_excalidraw_on_demand: true`, the catalog will build Excalidraw scenes
directly from S3 markup when a scene is requested (no pre-generation step required).

## Catalog service

`k8s/catalog-deployment.yaml` includes a Deployment (replicas=2), Service, and Ingress. It expects:

- RWX PVC named `cjm-shared-data`
- ConfigMap named `cjm-catalog-config` containing `app.yaml` (see `config/catalog/app.k8s.yaml`)
- `CJM_CONFIG_PATH=/config/app.yaml`
- Optional env overrides (example link templates):
  - `CJM_CATALOG__PROCEDURE_LINK_PATH`
  - `CJM_CATALOG__BLOCK_LINK_PATH`
  - `CJM_CATALOG__SERVICE_LINK_PATH`
  - `CJM_CATALOG__TEAM_LINK_PATH`

## Excalidraw service

`k8s/excalidraw-deployment.yaml` runs the official `excalidraw/excalidraw` image with 2 replicas,
plus a Service and Ingress.

## Ingress strategy

Choose one of the following approaches:

1) Different hosts: `catalog.example.com` and `excalidraw.example.com`
2) Same host (recommended for “Open Excalidraw”): route all paths to the catalog service, and let
   the catalog proxy Excalidraw under `/excalidraw`. The catalog also proxies `/assets/*` and other
   Excalidraw static files so the UI loads correctly.

Using the same host enables the Catalog “Open Excalidraw” button to inject the selected scene via
local storage (recommended for large diagrams). In that case set:

- `catalog.excalidraw_base_url: "/excalidraw"`
- `catalog.excalidraw_proxy_upstream: "http://excalidraw:80"`

You can still expose Excalidraw with its own ingress (for direct access), but the Catalog should
use the proxy path to keep same-origin behavior.

Note: localStorage has browser-specific size limits. Very large scenes may still require the
Download + Import flow in Excalidraw.

## ConfigMap example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cjm-catalog-config
data:
  app.yaml: |
    catalog:
      excalidraw_base_url: "/excalidraw"
      s3:
        bucket: "cjm-markup"
        prefix: "markup/"
        region: "us-east-1"
      excalidraw_in_dir: "/data/excalidraw_in"
      excalidraw_out_dir: "/data/excalidraw_out"
      roundtrip_dir: "/data/roundtrip"
      index_path: "/data/catalog/index.json"
      excalidraw_proxy_upstream: "http://excalidraw:80"
      excalidraw_proxy_prefix: "/excalidraw"
      excalidraw_max_url_length: 8000
```
