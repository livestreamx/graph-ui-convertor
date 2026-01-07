FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN python -m venv "$VIRTUAL_ENV"
RUN addgroup --system app && adduser --system --ingroup app app
RUN mkdir -p /data /config && chown -R app:app /data /config /app /opt/venv

COPY pyproject.toml poetry.lock README.md ./
COPY app ./app
COPY adapters ./adapters
COPY domain ./domain
COPY config ./config

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

USER app

EXPOSE 8080

CMD ["uvicorn", "app.web_main:app", "--host", "0.0.0.0", "--port", "8080"]
