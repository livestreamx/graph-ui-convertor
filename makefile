SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON_BOOTSTRAP ?= python3.14
POETRY_VERSION ?= 2.2.0
POETRY_BIN ?= $(HOME)/.local/bin/poetry

PROJECT ?= cjm_ui_convertor

# ---- UI (Excalidraw) ----
EXCALIDRAW_CONTAINER ?= excalidraw
EXCALIDRAW_PORT ?= 5000
EXCALIDRAW_URL ?= http://localhost:$(EXCALIDRAW_PORT)

# ---- Paths ----
DATA_DIR ?= data
MARKUP_DIR ?= $(DATA_DIR)/markup
EXCALIDRAW_IN_DIR ?= $(DATA_DIR)/excalidraw_in
EXCALIDRAW_OUT_DIR ?= $(DATA_DIR)/excalidraw_out
ROUNDTRIP_DIR ?= $(DATA_DIR)/roundtrip
VENV_DIR ?= .venv
VENV_BIN ?= $(VENV_DIR)/bin

# CLI entrypoints (to be implemented in MVP)
CLI ?= $(VENV_BIN)/cjm_ui_convertor

.PHONY: help
help:
	@echo ""
	@echo "Targets:"
	@echo "  make bootstrap        - install poetry, create venv for Python 3.14, install deps"
	@echo "  make install          - install python deps (poetry install)"
	@echo "  make update           - update lock + install"
	@echo "  make test             - run tests"
	@echo "  make lint             - run linters"
	@echo "  make fmt              - format code"
	@echo "  make excalidraw-up    - start Excalidraw UI in Docker on $(EXCALIDRAW_URL)"
	@echo "  make excalidraw-down  - stop Excalidraw UI"
	@echo "  make convert-to-ui    - convert markup json -> excalidraw json"
	@echo "  make convert-from-ui  - convert excalidraw json -> markup json"
	@echo "  make demo             - convert-to-ui + start UI"
	@echo ""

# -------- Bootstrap / Poetry --------

.PHONY: poetry-install
poetry-install:
	@if [ -x "$(POETRY_BIN)" ]; then \
		echo "Poetry already installed at $(POETRY_BIN)"; \
	else \
		echo "Installing Poetry $(POETRY_VERSION) via official installer..."; \
		curl -sSL https://install.python-poetry.org | $(PYTHON_BOOTSTRAP) - --version $(POETRY_VERSION); \
	fi
	@$(POETRY_BIN) --version

.PHONY: venv
venv: poetry-install
	@echo "Configuring Poetry venv in-project..."
	@$(POETRY_BIN) config virtualenvs.in-project true --local
	@echo "Using Python: $(PYTHON_BOOTSTRAP)"
	@$(POETRY_BIN) env use $(PYTHON_BOOTSTRAP)

.PHONY: install
install: venv
	@echo "Installing dependencies..."
	@$(POETRY_BIN) install

.PHONY: update
update: venv
	@$(POETRY_BIN) lock
	@$(POETRY_BIN) install

.PHONY: bootstrap
bootstrap: install dirs

.PHONY: dirs
dirs:
	@mkdir -p $(MARKUP_DIR) $(EXCALIDRAW_IN_DIR) $(EXCALIDRAW_OUT_DIR) $(ROUNDTRIP_DIR)

# -------- Quality --------

.PHONY: test
test:
	@$(VENV_BIN)/pytest -q

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
	@docker rm -f $(EXCALIDRAW_CONTAINER) >/dev/null 2>&1 || true
	@docker run --rm -d --name $(EXCALIDRAW_CONTAINER) -p $(EXCALIDRAW_PORT):80 excalidraw/excalidraw:latest
	@echo "Open: $(EXCALIDRAW_URL)"

.PHONY: excalidraw-down
excalidraw-down:
	@docker rm -f $(EXCALIDRAW_CONTAINER) >/dev/null 2>&1 || true
	@echo "Excalidraw stopped."

.PHONY: demo
demo: convert-to-ui excalidraw-up
	@echo ""
	@echo "Next steps (manual in UI):"
	@echo "  1) Open $(EXCALIDRAW_URL)"
	@echo "  2) Import .excalidraw/.json from: $(EXCALIDRAW_IN_DIR)"
	@echo "  3) Edit, then Export as .excalidraw into: $(EXCALIDRAW_OUT_DIR)"
	@echo "  4) Run: make convert-from-ui"
	@echo ""
