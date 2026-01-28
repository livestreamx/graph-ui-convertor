FROM python:3.14-slim

WORKDIR /app

ARG POETRY_VERSION
ARG PYPI_URL

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN python -m venv "$VIRTUAL_ENV"
RUN addgroup --system app && adduser --system --ingroup app app
RUN mkdir -p /data /config && chown -R app:app /data /config /app /opt/venv

COPY pyproject.toml poetry.lock ./
RUN POETRY_VERSION_CLEAN="$(printf '%s' "$POETRY_VERSION" | \
        sed -E 's/[^0-9A-Za-z.+-]/ /g' | \
        awk '{for (i = 1; i <= NF; i++) if ($i ~ /[0-9]/) {gsub(/^[^0-9]+/, "", $i); print $i; exit}}')" \
    && PIP_INDEX_URL_ARG="" \
    && if [ -n "$PYPI_URL" ]; then \
        PIP_INDEX_URL_ARG="--index-url $PYPI_URL"; \
    fi \
    && if [ -z "$POETRY_VERSION_CLEAN" ]; then \
        echo "Invalid POETRY_VERSION: $POETRY_VERSION" >&2; \
        exit 1; \
    fi \
    && pip install --no-cache-dir $PIP_INDEX_URL_ARG --upgrade pip \
    && pip install --no-cache-dir $PIP_INDEX_URL_ARG "poetry==${POETRY_VERSION_CLEAN}" "poetry-plugin-export" \
    && poetry export -f requirements.txt --output /tmp/requirements.txt --without-hashes --only main \
    && pip install --no-cache-dir $PIP_INDEX_URL_ARG -r /tmp/requirements.txt \
    && pip uninstall -y poetry \
    && rm -rf /root/.cache/pip /root/.cache/pypoetry /tmp/requirements.txt

COPY app ./app
COPY adapters ./adapters
COPY domain ./domain
COPY config ./config

ENV PYTHONPATH=/app

USER app

EXPOSE 8080

CMD ["uvicorn", "app.web_main:app", "--host", "0.0.0.0", "--port", "8080"]
