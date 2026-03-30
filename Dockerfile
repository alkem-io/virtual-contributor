# Multi-stage Dockerfile — PLUGIN_TYPE selected at runtime, not build time
# Build: docker build -t alkemio/virtual-contributor .
# Run:   docker run -e PLUGIN_TYPE=generic alkemio/virtual-contributor

# --- Builder stage ---
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir poetry==2.3.3

WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY core/ ./core/
COPY plugins/ ./plugins/
COPY main.py ./

ENV PLUGIN_TYPE=generic
ENV HEALTH_PORT=8080

EXPOSE 8080

CMD ["python", "main.py"]
