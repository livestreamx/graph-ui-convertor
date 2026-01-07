FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml poetry.lock README.md ./
COPY app ./app
COPY adapters ./adapters
COPY domain ./domain
COPY config ./config

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "app.web_main:app", "--host", "0.0.0.0", "--port", "8080"]
