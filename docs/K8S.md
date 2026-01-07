# Kubernetes deployment guide (examples)

This project ships example manifests under `k8s/` for a two-service setup:

- Catalog UI (FastAPI + shared storage)
- Excalidraw (official container)

## Shared storage (RWX)

The catalog service reads/writes markup, scenes, and roundtrip outputs from a shared volume. Use a
ReadWriteMany (RWX) PVC and mount it at `/data` across all catalog replicas.

Example PVC: `k8s/pvc.yaml`.

## Catalog service

`k8s/catalog-deployment.yaml` includes a Deployment (replicas=2), Service, and Ingress. It expects:

- RWX PVC named `cjm-shared-data`
- ConfigMap named `cjm-catalog-config` containing `app.yaml` (see `config/catalog/app.k8s.yaml`)
- `CJM_CONFIG_PATH=/config/app.yaml`

## Excalidraw service

`k8s/excalidraw-deployment.yaml` runs the official `excalidraw/excalidraw` image with 2 replicas,
plus a Service and Ingress.

## Ingress strategy

Choose one of the following approaches:

1) Different hosts: `catalog.example.com` and `excalidraw.example.com`
2) Same host with paths (if supported by your ingress controller):
   - `/catalog` -> catalog service
   - `/excalidraw` -> excalidraw service

## ConfigMap example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cjm-catalog-config
data:
  app.yaml: |
    catalog:
      excalidraw_base_url: "https://excalidraw.example.com"
      markup_dir: "/data/markup"
      excalidraw_in_dir: "/data/excalidraw_in"
      excalidraw_out_dir: "/data/excalidraw_out"
      roundtrip_dir: "/data/roundtrip"
      index_path: "/data/catalog/index.json"
```
