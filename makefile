SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON_BOOTSTRAP ?= python3.14
POETRY_VERSION ?= 2.2.0

PROJECT ?= cjm_ui_convertor

# ---- UI (Excalidraw) ----
EXCALIDRAW_CONTAINER ?= excalidraw
EXCALIDRAW_PORT ?= 5010
EXCALIDRAW_URL ?= http://localhost:$(EXCALIDRAW_PORT)
ALLOW_DOCKER_FAILURE ?= 0
CATALOG_CONTAINER ?= cjm-catalog
CATALOG_IMAGE ?= cjm-catalog:latest
CATALOG_PORT ?= 8080
CATALOG_URL ?= http://localhost:$(CATALOG_PORT)
CATALOG_CONFIG ?= config/catalog/app.s3.yaml
CATALOG_DOCKER_CONFIG ?= config/catalog/app.docker.s3.yaml
CATALOG_DOCKERFILE ?= docker/catalog/Dockerfile
CATALOG_ENV_FILE ?= config/catalog/env.local
CATALOG_ENV_EXTRA ?= $(strip \
	$(if $(CJM_CATALOG__DIAGRAM_FORMAT),-e CJM_CATALOG__DIAGRAM_FORMAT=$(CJM_CATALOG__DIAGRAM_FORMAT),) \
	$(if $(CJM_CATALOG__UNIDRAW_BASE_URL),-e CJM_CATALOG__UNIDRAW_BASE_URL=$(CJM_CATALOG__UNIDRAW_BASE_URL),) \
)
DEMO_NETWORK ?= cjm-demo
S3_CONTAINER ?= cjm-s3
S3_PORT ?= 9000
S3_CONSOLE_PORT ?= 9001
S3_URL ?= http://localhost:$(S3_PORT)
S3_ACCESS_KEY ?= minioadmin
S3_SECRET_KEY ?= minioadmin
S3_BUCKET ?= cjm-markup
S3_PREFIX ?= markup/
S3_DATA_DIR ?= data/s3
S3_SEED_SOURCE ?= $(MARKUP_DIR)

# ---- Docs / diagrams ----
C4_DIRS ?= docs/en/c4 docs/ru/c4
C4_OUT_DIRS ?= docs/en/c4/rendered docs/ru/c4/rendered
C4_IMAGE ?= minlag/mermaid-cli
C4_UID ?= $(shell id -u)
C4_GID ?= $(shell id -g)

# ---- Paths ----
DATA_DIR ?= data
MARKUP_DIR ?= $(DATA_DIR)/markup
EXCALIDRAW_IN_DIR ?= $(DATA_DIR)/excalidraw_in
EXCALIDRAW_OUT_DIR ?= $(DATA_DIR)/excalidraw_out
UNIDRAW_IN_DIR ?= $(DATA_DIR)/unidraw_in
UNIDRAW_OUT_DIR ?= $(DATA_DIR)/unidraw_out
ROUNDTRIP_DIR ?= $(DATA_DIR)/roundtrip
CATALOG_DIR ?= $(DATA_DIR)/catalog
VENV_DIR ?= .venv
VENV_BIN ?= $(VENV_DIR)/bin
VENV_PYTHON ?= $(VENV_BIN)/python
POETRY_BIN ?= $(VENV_BIN)/poetry

# CLI entrypoints
CLI ?= $(VENV_BIN)/cjm

.PHONY: catalog-build-index
catalog-build-index:
	@$(CLI) catalog build-index --config "$(CATALOG_CONFIG)"

.PHONY: pipeline-build-all
pipeline-build-all:
	@$(CLI) pipeline build-all --config "$(CATALOG_CONFIG)"


.PHONY: help
help:
	@echo ""
	@echo "Targets:"
	@echo "  make bootstrap        - create .venv, install poetry, install deps"
	@echo "  make install          - install python deps (poetry install)"
	@echo "  make update           - update lock + install"
	@echo "  make test             - run tests"
	@echo "  make lint             - run linters"
	@echo "  make fmt              - format code"
	@echo "  make excalidraw-up    - start Excalidraw UI in Docker on $(EXCALIDRAW_URL)"
	@echo "  make excalidraw-down  - stop Excalidraw UI"
	@echo "  make s3-up            - start local S3 stub on $(S3_URL)"
	@echo "  make s3-down          - stop local S3 stub"
	@echo "  make s3-seed          - upload markup files into local S3 stub"
	@echo "  make catalog-up       - start Catalog UI in Docker on $(CATALOG_URL)"
	@echo "  make catalog-down     - stop Catalog UI"
	@echo "  make catalog-build-index - build catalog index with $(CATALOG_CONFIG)"
	@echo "  make pipeline-build-all  - convert + index build with $(CATALOG_CONFIG)"
	@echo "  make convert-to-ui    - convert markup json -> excalidraw json"
	@echo "  make convert-to-excalidraw - convert markup json -> excalidraw json"
	@echo "  make convert-to-unidraw - convert markup json -> unidraw json"
	@echo "  make convert-from-ui  - convert excalidraw json -> markup json"
	@echo "  make c4-render        - render C4 diagrams to $(C4_OUT_DIRS)"
	@echo "  make demo             - seed S3 + start UIs (on-demand conversion)"
	@echo "  make demo-smoke       - verify demo services are responding"
	@echo "  make down             - stop demo services"
	@echo "    (set ALLOW_DOCKER_FAILURE=0 to fail if Docker/Colima unavailable)"
	@echo ""

# -------- Bootstrap / Poetry --------

.PHONY: poetry-install
poetry-install: venv
	@if [ -x "$(POETRY_BIN)" ]; then \
		echo "Poetry already installed at $(POETRY_BIN)"; \
	else \
		echo "Installing Poetry $(POETRY_VERSION) into $(VENV_DIR)..."; \
		$(VENV_PYTHON) -m pip install --upgrade pip; \
		$(VENV_PYTHON) -m pip install "poetry==$(POETRY_VERSION)"; \
	fi
	@$(POETRY_BIN) config virtualenvs.create false --local
	@$(POETRY_BIN) config virtualenvs.in-project true --local
	@$(POETRY_BIN) --version

.PHONY: venv
venv:
	@if [ -x "$(VENV_PYTHON)" ]; then \
		echo "Venv already exists at $(VENV_DIR)"; \
	else \
		echo "Creating venv in $(VENV_DIR) with $(PYTHON_BOOTSTRAP)..."; \
		$(PYTHON_BOOTSTRAP) -m venv $(VENV_DIR); \
	fi

.PHONY: install
install: poetry-install
	@echo "Installing dependencies..."
	@$(POETRY_BIN) install

.PHONY: update
update: poetry-install
	@$(POETRY_BIN) lock
	@$(POETRY_BIN) install

.PHONY: bootstrap
bootstrap: install dirs

.PHONY: dirs
dirs:
	@mkdir -p $(MARKUP_DIR) $(EXCALIDRAW_IN_DIR) $(EXCALIDRAW_OUT_DIR) $(UNIDRAW_IN_DIR) $(UNIDRAW_OUT_DIR) $(ROUNDTRIP_DIR) $(CATALOG_DIR) $(S3_DATA_DIR)

# -------- Quality --------

.PHONY: test
test:
	@$(VENV_BIN)/pytest -n 3

.PHONY: lint
lint:
	@$(VENV_BIN)/ruff check .
	@$(VENV_BIN)/mypy .

.PHONY: fmt
fmt:
	@$(VENV_BIN)/ruff format .
	@$(VENV_BIN)/ruff check . --fix

# -------- Converters (to be implemented) --------

.PHONY: convert-to-ui
convert-to-ui: convert-to-excalidraw

.PHONY: convert-to-excalidraw
convert-to-excalidraw: dirs
	@echo "Converting markup -> excalidraw..."
	@$(CLI) convert to-excalidraw \
		--input-dir "$(MARKUP_DIR)" \
		--output-dir "$(EXCALIDRAW_IN_DIR)"

.PHONY: convert-to-unidraw
convert-to-unidraw: dirs
	@echo "Converting markup -> unidraw..."
	@$(CLI) convert to-unidraw \
		--input-dir "$(MARKUP_DIR)" \
		--output-dir "$(UNIDRAW_IN_DIR)"

.PHONY: convert-from-ui
convert-from-ui: dirs
	@echo "Converting excalidraw -> markup..."
	@$(CLI) convert from-excalidraw \
		--input-dir "$(EXCALIDRAW_OUT_DIR)" \
		--output-dir "$(ROUNDTRIP_DIR)"

# -------- Excalidraw UI (Docker) --------

.PHONY: excalidraw-up
excalidraw-up:
	@command -v docker >/dev/null 2>&1 || (echo "Docker not found. Install Docker first." && exit 1)
	@echo "Starting Excalidraw at $(EXCALIDRAW_URL) ..."
	@docker ps >/dev/null 2>&1 || (echo "Docker daemon is not accessible (start Docker Desktop or Colima)"; exit 1)
	@docker network inspect $(DEMO_NETWORK) >/dev/null 2>&1 || docker network create $(DEMO_NETWORK)
	@docker rm -f $(EXCALIDRAW_CONTAINER) >/dev/null 2>&1 || true
	@docker run --rm -d --name $(EXCALIDRAW_CONTAINER) \
		--network $(DEMO_NETWORK) --network-alias excalidraw \
		-p $(EXCALIDRAW_PORT):80 excalidraw/excalidraw:latest
	@echo "Open: $(EXCALIDRAW_URL)"

.PHONY: excalidraw-down
excalidraw-down:
	@docker rm -f $(EXCALIDRAW_CONTAINER) >/dev/null 2>&1 || true
	@echo "Excalidraw stopped."

# -------- S3 stub (MinIO) --------

.PHONY: s3-up
s3-up: dirs
	@command -v docker >/dev/null 2>&1 || (echo "Docker not found. Install Docker first." && exit 1)
	@echo "Starting S3 stub on $(S3_URL) ..."
	@docker ps >/dev/null 2>&1 || (echo "Docker daemon is not accessible (start Docker Desktop or Colima)"; exit 1)
	@docker network inspect $(DEMO_NETWORK) >/dev/null 2>&1 || docker network create $(DEMO_NETWORK)
	@docker rm -f $(S3_CONTAINER) >/dev/null 2>&1 || true
	@docker run --rm -d --name $(S3_CONTAINER) \
		--network $(DEMO_NETWORK) --network-alias s3 \
		-p $(S3_PORT):9000 -p $(S3_CONSOLE_PORT):9001 \
		-e MINIO_ROOT_USER=$(S3_ACCESS_KEY) \
		-e MINIO_ROOT_PASSWORD=$(S3_SECRET_KEY) \
		-v $(PWD)/$(S3_DATA_DIR):/data \
		minio/minio:latest server /data --console-address ":9001"
	@echo "S3 stub ready: $(S3_URL)"

.PHONY: s3-down
s3-down:
	@docker rm -f $(S3_CONTAINER) >/dev/null 2>&1 || true
	@echo "S3 stub stopped."

.PHONY: s3-seed
s3-seed:
	@echo "Seeding S3 bucket $(S3_BUCKET) from $(S3_SEED_SOURCE) ..."
	@if [ -d "$(S3_SEED_SOURCE)" ] && [ "$$(find "$(S3_SEED_SOURCE)" -type f | wc -l)" -gt 0 ]; then \
		SOURCE="$(S3_SEED_SOURCE)"; \
	else \
		SOURCE="examples/markup"; \
	fi; \
	$(VENV_PYTHON) scripts/seed_s3.py \
		--endpoint "$(S3_URL)" \
		--access-key "$(S3_ACCESS_KEY)" \
		--secret-key "$(S3_SECRET_KEY)" \
		--bucket "$(S3_BUCKET)" \
		--prefix "$(S3_PREFIX)" \
		--source "$$SOURCE" \
		--path-style

# -------- Catalog UI (Docker) --------

.PHONY: catalog-up
catalog-up: dirs
	@command -v docker >/dev/null 2>&1 || (echo "Docker not found. Install Docker first." && exit 1)
	@echo "Building Catalog image..."
	@docker build -f $(CATALOG_DOCKERFILE) -t $(CATALOG_IMAGE) .
	@docker rm -f $(CATALOG_CONTAINER) >/dev/null 2>&1 || true
	@docker run --rm -d --name $(CATALOG_CONTAINER) \
		--network $(DEMO_NETWORK) \
		-p $(CATALOG_PORT):8080 \
		-e CJM_CONFIG_PATH=/config/app.yaml \
		--env-file $(CATALOG_ENV_FILE) \
		$(CATALOG_ENV_EXTRA) \
		-v $(PWD)/$(DATA_DIR):/data \
		-v $(PWD)/$(CATALOG_DOCKER_CONFIG):/config/app.yaml:ro \
		$(CATALOG_IMAGE)
	@sleep 2
	@docker inspect -f '{{.State.Running}}' $(CATALOG_CONTAINER) >/dev/null 2>&1 || \
		(echo "Catalog container not found after startup." && exit 1)
	@docker inspect -f '{{.State.Running}}' $(CATALOG_CONTAINER) | grep -q true || \
		(echo "Catalog failed to start. Logs:" && docker logs $(CATALOG_CONTAINER) && exit 1)
	@echo "Catalog started on $(CATALOG_URL)"

.PHONY: catalog-down
catalog-down:
	@docker rm -f $(CATALOG_CONTAINER) >/dev/null 2>&1 || true
	@echo "Catalog stopped."

# -------- C4 diagrams --------

.PHONY: c4-render
c4-render:
	@command -v docker >/dev/null 2>&1 || (echo "Docker not found. Install Docker first." && exit 1)
	@for dir in $(C4_DIRS); do \
		echo "Rendering C4 diagrams in $$dir"; \
		mkdir -p $$dir/rendered; \
		docker run --rm -u $(C4_UID):$(C4_GID) \
			-v $(PWD)/$$dir:/docs -w /docs \
			$(C4_IMAGE) -i local.mmd -o rendered/local.svg; \
		docker run --rm -u $(C4_UID):$(C4_GID) \
			-v $(PWD)/$$dir:/docs -w /docs \
			$(C4_IMAGE) -i k8s.mmd -o rendered/k8s.svg; \
	done
	@echo "C4 diagrams rendered to $(C4_OUT_DIRS)"

.PHONY: demo
demo: c4-render s3-up s3-seed excalidraw-up catalog-up demo-smoke
	@echo ""
	@echo "Next steps (manual in UI):"
	@echo "  1) Open $(CATALOG_URL)/catalog"
	@echo "  2) Open a scene in Excalidraw and edit"
	@echo "  3) Export .excalidraw into: $(EXCALIDRAW_OUT_DIR)"
	@echo "  4) Upload edited .excalidraw and click Convert back"
	@echo ""

.PHONY: demo-smoke
demo-smoke:
	@$(VENV_PYTHON) scripts/smoke_demo.py --catalog "$(CATALOG_URL)" --timeout 60

.PHONY: down
down: catalog-down excalidraw-down s3-down
