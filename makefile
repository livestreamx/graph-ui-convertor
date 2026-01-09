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
CATALOG_CONFIG ?= config/catalog/app.yaml
CATALOG_DOCKER_CONFIG ?= config/catalog/app.docker.yaml
CATALOG_DOCKERFILE ?= docker/catalog/Dockerfile
DEMO_NETWORK ?= cjm-demo

# ---- Paths ----
DATA_DIR ?= data
MARKUP_DIR ?= $(DATA_DIR)/markup
EXCALIDRAW_IN_DIR ?= $(DATA_DIR)/excalidraw_in
EXCALIDRAW_OUT_DIR ?= $(DATA_DIR)/excalidraw_out
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
	@echo "  make catalog-up       - start Catalog UI in Docker on $(CATALOG_URL)"
	@echo "  make catalog-down     - stop Catalog UI"
	@echo "  make catalog-build-index - build catalog index with $(CATALOG_CONFIG)"
	@echo "  make pipeline-build-all  - convert + index build with $(CATALOG_CONFIG)"
	@echo "  make convert-to-ui    - convert markup json -> excalidraw json"
	@echo "  make convert-from-ui  - convert excalidraw json -> markup json"
	@echo "  make demo             - convert-to-ui + start UIs"
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
	@mkdir -p $(MARKUP_DIR) $(EXCALIDRAW_IN_DIR) $(EXCALIDRAW_OUT_DIR) $(ROUNDTRIP_DIR) $(CATALOG_DIR)

# -------- Quality --------

.PHONY: test
test:
	@$(VENV_BIN)/pytest

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
convert-to-ui: dirs
	@echo "Converting markup -> excalidraw..."
	@$(CLI) convert to-excalidraw \
		--input-dir "$(MARKUP_DIR)" \
		--output-dir "$(EXCALIDRAW_IN_DIR)"

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
		-v $(PWD)/$(DATA_DIR):/data \
		-v $(PWD)/$(CATALOG_DOCKER_CONFIG):/config/app.yaml:ro \
		$(CATALOG_IMAGE)
	@echo "Catalog started on $(CATALOG_URL)"

.PHONY: catalog-down
catalog-down:
	@docker rm -f $(CATALOG_CONTAINER) >/dev/null 2>&1 || true
	@echo "Catalog stopped."

.PHONY: demo
demo: pipeline-build-all excalidraw-up catalog-up
	@echo ""
	@echo "Next steps (manual in UI):"
	@echo "  1) Open $(EXCALIDRAW_URL)"
	@echo "  2) Import .excalidraw/.json from: $(EXCALIDRAW_IN_DIR)"
	@echo "  3) Edit, then Export as .excalidraw into: $(EXCALIDRAW_OUT_DIR)"
	@echo "  4) Open catalog: $(CATALOG_URL)/catalog"
	@echo "  5) Upload edited .excalidraw and click Convert back"
	@echo ""

.PHONY: down
down: catalog-down excalidraw-down
