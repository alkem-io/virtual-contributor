# Distroless runtime — PLUGIN_TYPE selected at runtime, not build time
# Build: docker build -t alkemio/virtual-contributor .
# Run:   docker run -e PLUGIN_TYPE=generic alkemio/virtual-contributor
#
# Matched Python 3.13 pair (workspace#026-distroless-runtime-images):
#   builder  python:3.13.7-slim-trixie@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689
#   runtime  gcr.io/distroless/python3-debian13:nonroot@sha256:0e52dfee02b1aba142e77b004f6ea11210b79456b51f10d70e9bd631cbc21d98
# Both resolve to interpreter major.minor 3.13 (builder 3.13.7, distroless
# runtime 3.13.5 at pin time) — the ABI-relevant tag (cp313) matches, which is
# what the compiled extensions in poetry.lock are built against. Re-verify
# with docker/image-verify.sh whenever either pin is bumped.
#
# Dependencies are installed exclusively from the committed, lock-checked
# poetry.lock into a relocatable /venv, then copied verbatim into the
# distroless runtime and exposed via PYTHONPATH — no pip/poetry/shell exists
# in the runtime image.

# --- Builder stage (glibc/Debian, matches the distroless runtime's libc) ---
FROM python:3.13.7-slim-trixie@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689 AS builder

RUN pip install --no-cache-dir poetry==2.3.3

# Build a relocatable venv independent of the builder's own site-packages.
RUN python -m venv /venv
ENV VIRTUAL_ENV=/venv \
    PATH="/venv/bin:${PATH}" \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Exact filenames (no glob): the build FAILS here if poetry.lock is missing,
# which is the point — no install may happen without a committed lock.
# README.md is required too — `[tool.poetry.readme]` points at it and
# `poetry check --lock` fails fast if the declared readme is absent.
COPY pyproject.toml poetry.lock README.md ./

# Fails the build if poetry.lock is stale relative to pyproject.toml.
RUN poetry check --lock

# Installs into the already-activated /venv (POETRY_VIRTUALENVS_CREATE=false
# + VIRTUAL_ENV) using only what's pinned in poetry.lock; --no-root skips
# installing this project itself (source is copied directly, below).
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Record the exact builder interpreter version for the runtime match check
# performed by docker/image-verify.sh (US3-AS1).
RUN python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" > /venv/PYTHON_VERSION

# --- Runtime stage (distroless, non-root, no shell/package manager) ---
FROM gcr.io/distroless/python3-debian13:nonroot@sha256:0e52dfee02b1aba142e77b004f6ea11210b79456b51f10d70e9bd631cbc21d98

WORKDIR /app

COPY --from=builder /venv /venv
COPY core/ ./core/
COPY plugins/ ./plugins/
COPY main.py ./

ENV PYTHONPATH=/venv/lib/python3.13/site-packages \
    PLUGIN_TYPE=generic \
    HEALTH_PORT=8080

EXPOSE 8080

# Distroless python3 image's ENTRYPOINT is the python3 interpreter itself;
# CMD supplies the script argument only (no shell involved).
CMD ["main.py"]
