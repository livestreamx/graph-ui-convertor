# Руководство по деплою в Kubernetes (примеры)

Проект включает пример манифестов в `k8s/` для сетапа из двух сервисов:

- Catalog UI (FastAPI + shared storage)
- Excalidraw (официальный контейнер)

## Общий storage (RWX)

Catalog читает/пишет сгенерированные сцены и round-trip результаты из общего тома. Используйте
ReadWriteMany (RWX) PVC и монтируйте его в `/data` во все реплики Catalog.

Пример PVC: `k8s/pvc.yaml`.

## Markup из S3 (обязательно)

Markup JSON в Kubernetes берется из S3. Настройте `catalog.s3` в ConfigMap. При
`generate_excalidraw_on_demand: true` каталог будет собирать сцены Excalidraw напрямую из markup в S3
по запросу (без предварительной генерации).

## Сервис Catalog

`k8s/catalog-deployment.yaml` включает Deployment (replicas=2), Service и Ingress. Ожидается:

- RWX PVC с именем `cjm-shared-data`
- ConfigMap `cjm-catalog-config` с `app.yaml` (см. `config/catalog/app.k8s.yaml`)
- `CJM_CONFIG_PATH=/config/app.yaml`

## Сервис Excalidraw

`k8s/excalidraw-deployment.yaml` запускает официальный образ `excalidraw/excalidraw` с 2 репликами,
плюс Service и Ingress.

## Стратегия Ingress

Выберите один из подходов:

1) Разные хосты: `catalog.example.com` и `excalidraw.example.com`
2) Один хост (рекомендуется для “Open Excalidraw”): направляйте все пути в сервис Catalog и
   проксируйте Excalidraw под `/excalidraw`. Catalog также проксирует `/assets/*` и другие
   статические файлы Excalidraw, чтобы UI грузился корректно.

Один хост позволяет кнопке “Open Excalidraw” внедрять сцену через localStorage (рекомендуется для
больших диаграмм). В этом случае задайте:

- `catalog.excalidraw_base_url: "/excalidraw"`
- `catalog.excalidraw_proxy_upstream: "http://excalidraw:80"`

Можно по-прежнему публиковать Excalidraw отдельным ingress (для прямого доступа), но Catalog должен
использовать прокси-путь для same-origin поведения.

Примечание: localStorage имеет ограничения по размеру. Очень большие сцены могут требовать сценарий
Download + Import в Excalidraw.

## Пример ConfigMap

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
