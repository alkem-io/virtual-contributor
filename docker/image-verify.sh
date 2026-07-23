#!/usr/bin/env bash
# Persisted regression for the vc-runtime-image contract (US3, workspace#026).
#
# Asserts, against a built image, in order:
#   1. Structure: runs as UID 65532, Cmd == ["main.py"], no shell present.
#   2. Interpreter match: builder (recorded in /venv/PYTHON_VERSION) and
#      runtime python3 major.minor are both 3.13 and identical.
#   3. Native-extension import gate: every module derived by
#      docker/native-imports.py from poetry.lock imports cleanly.
#   4. Six-plugin start matrix: expert, generic, guidance, openai-assistant,
#      ingest_website, ingest_space each start against a live RabbitMQ (+
#      ChromaDB) and answer /healthz 200 + /readyz 200.
#   5. Evidence: emits IMAGE_DIGEST=/IMAGE_SIZE_BYTES= lines and, when a
#      baseline image is available locally, a size-reduction check.
#
# Usage: docker/image-verify.sh <image> [baseline-image]
#   VC_BASELINE_IMAGE env var overrides the default baseline
#   (alkemio/virtual-contributor:v0.1.2).

set -euo pipefail

IMAGE="${1:?Usage: docker/image-verify.sh <image> [baseline-image]}"
BASELINE_IMAGE="${2:-${VC_BASELINE_IMAGE:-alkemio/virtual-contributor:v0.1.2}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RUN_ID="$$-$RANDOM"
NETWORK_NAME="vc-verify-net-${RUN_ID}"
RABBITMQ_NAME="vc-verify-rabbitmq-${RUN_ID}"
CHROMA_NAME="vc-verify-chroma-${RUN_ID}"
declare -a PLUGIN_CONTAINERS=()
TMP_LOG="$(mktemp)"

cleanup() {
  local c
  for c in "${PLUGIN_CONTAINERS[@]:-}"; do
    [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1 || true
  done
  docker rm -f "$RABBITMQ_NAME" "$CHROMA_NAME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  rm -f "$TMP_LOG"
}
trap cleanup EXIT

echo "== virtual-contributor image-verify: $IMAGE =="

# --- 1. Structure: user / cmd / no shell -----------------------------------
echo "-- [1/5] structure: user / cmd / no shell --"
USER_ID="$(docker inspect "$IMAGE" --format '{{.Config.User}}')"
CMD_JSON="$(docker inspect "$IMAGE" --format '{{json .Config.Cmd}}')"

[ "$USER_ID" = "65532" ] || { echo "FAIL: expected user 65532, got '$USER_ID'"; exit 1; }
[ "$CMD_JSON" = '["main.py"]' ] || { echo "FAIL: expected Cmd [\"main.py\"], got $CMD_JSON"; exit 1; }

if docker run --rm --entrypoint /bin/sh "$IMAGE" -c true >"$TMP_LOG" 2>&1; then
  echo "FAIL: a shell exists in the runtime image (expected /bin/sh to be absent)"
  cat "$TMP_LOG"
  exit 1
fi
echo "OK: user=65532 cmd=[\"main.py\"] no shell"

# --- 2. Interpreter match ----------------------------------------------------
echo "-- [2/5] builder/runtime interpreter match --"
RUNTIME_PYVER="$(docker run --rm --entrypoint /usr/bin/python3 "$IMAGE" -c \
  "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
BUILDER_PYVER_FULL="$(docker run --rm --entrypoint /usr/bin/python3 "$IMAGE" -c \
  "print(open('/venv/PYTHON_VERSION').read().strip())")"
BUILDER_PYVER="${BUILDER_PYVER_FULL%.*}"

[ "$RUNTIME_PYVER" = "3.13" ] || { echo "FAIL: runtime interpreter is $RUNTIME_PYVER, expected 3.13"; exit 1; }
[ "$RUNTIME_PYVER" = "$BUILDER_PYVER" ] || {
  echo "FAIL: builder ($BUILDER_PYVER_FULL) / runtime ($RUNTIME_PYVER) major.minor mismatch"
  exit 1
}
echo "OK: builder=$BUILDER_PYVER_FULL runtime=$RUNTIME_PYVER (major.minor match)"

# --- 3. Native-extension import gate ----------------------------------------
echo "-- [3/5] native-extension import gate --"
if ! command -v poetry >/dev/null 2>&1; then
  echo "FAIL: poetry not found on host — required to derive the native module list"
  exit 1
fi

MODULES="$(cd "$REPO_ROOT" && poetry run python docker/native-imports.py)"
[ -n "$MODULES" ] || { echo "FAIL: native-imports.py produced no modules"; exit 1; }

FAILED_MODULES=()
MODULE_COUNT=0
while IFS= read -r module; do
  [ -z "$module" ] && continue
  MODULE_COUNT=$((MODULE_COUNT + 1))
  if ! docker run --rm --entrypoint /usr/bin/python3 "$IMAGE" -c "import $module" >"$TMP_LOG" 2>&1; then
    FAILED_MODULES+=("$module")
    echo "  FAIL: import $module"
    cat "$TMP_LOG"
  fi
done <<<"$MODULES"

if [ "${#FAILED_MODULES[@]}" -gt 0 ]; then
  echo "FAIL: native import failures: ${FAILED_MODULES[*]}"
  exit 1
fi
echo "OK: all $MODULE_COUNT native modules import cleanly"

# --- 4. Six-plugin start matrix ----------------------------------------------
echo "-- [4/5] six-plugin start matrix --"
docker network create "$NETWORK_NAME" >/dev/null

start_rabbitmq() {
  docker rm -f "$RABBITMQ_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$RABBITMQ_NAME" --network "$NETWORK_NAME" \
    -e RABBITMQ_DEFAULT_USER=alkemio-admin -e RABBITMQ_DEFAULT_PASS='alkemio!' \
    rabbitmq:3-management >/dev/null
}

start_rabbitmq
docker run -d --name "$CHROMA_NAME" --network "$NETWORK_NAME" \
  chromadb/chroma:latest >/dev/null

echo "waiting for rabbitmq to accept connections..."
RABBITMQ_READY=0
RABBITMQ_RESTARTS=0
MAX_RABBITMQ_RESTARTS=3
for _ in $(seq 1 90); do
  if docker exec "$RABBITMQ_NAME" rabbitmq-diagnostics -q ping >/dev/null 2>&1; then
    RABBITMQ_READY=1
    break
  fi
  # The rabbitmq image occasionally races its own .erlang.cookie write on a
  # busy host and exits with "eacces" on first read — restart rather than
  # fail the whole run on transient flakiness (bounded retries).
  status="$(docker inspect -f '{{.State.Status}}' "$RABBITMQ_NAME" 2>/dev/null || echo missing)"
  if [ "$status" != "running" ] && [ "$RABBITMQ_RESTARTS" -lt "$MAX_RABBITMQ_RESTARTS" ]; then
    RABBITMQ_RESTARTS=$((RABBITMQ_RESTARTS + 1))
    echo "  rabbitmq container not running (status=$status) — restart attempt $RABBITMQ_RESTARTS/$MAX_RABBITMQ_RESTARTS"
    start_rabbitmq
  fi
  sleep 2
done
[ "$RABBITMQ_READY" -eq 1 ] || { echo "FAIL: rabbitmq did not become ready"; docker logs "$RABBITMQ_NAME" 2>&1 | tail -30; exit 1; }
echo "OK: rabbitmq ready"

# Exact PLUGIN_TYPE values deployed by dev-orchestration (repos.yaml → forge.contracts.vc-runtime-image)
PLUGIN_TYPES=(expert generic guidance openai-assistant ingest_website ingest_space)

FAILED_PLUGINS=()
for plugin in "${PLUGIN_TYPES[@]}"; do
  cname="vc-verify-${plugin//_/-}-${RUN_ID}"
  env_args=(
    -e "PLUGIN_TYPE=${plugin}"
    -e "RABBITMQ_HOST=${RABBITMQ_NAME}"
    -e "RABBITMQ_USER=alkemio-admin"
    -e "RABBITMQ_PASSWORD=alkemio!"
    -e "RABBITMQ_QUEUE=verify-${plugin}"
    -e "MISTRAL_API_KEY=dummy-key-for-verification"
    -e "MISTRAL_SMALL_MODEL_NAME=mistral-small-latest"
  )
  case "$plugin" in
    expert|guidance|ingest_website|ingest_space)
      env_args+=( -e "VECTOR_DB_HOST=${CHROMA_NAME}" -e "VECTOR_DB_PORT=8000" )
      ;;
  esac
  case "$plugin" in
    ingest_website|ingest_space)
      # The ingest plugins require an EmbeddingsPort adapter to be
      # registered (container.resolve_for_plugin is strict about it) —
      # dummy, non-empty values are enough; the adapter performs no network
      # call at construction time.
      env_args+=(
        -e "EMBEDDINGS_API_KEY=dummy-embeddings-key"
        -e "EMBEDDINGS_ENDPOINT=http://verify-placeholder.invalid/v1"
        -e "EMBEDDINGS_MODEL_NAME=verify-embedding-model"
      )
      ;;
  esac
  if [ "$plugin" = "ingest_space" ]; then
    env_args+=(
      -e "API_ENDPOINT_PRIVATE_GRAPHQL=http://verify-placeholder.invalid/graphql"
      -e "AUTH_ADMIN_EMAIL=verify@example.com"
      -e "AUTH_ADMIN_PASSWORD=verify-placeholder"
    )
  fi

  docker run -d --name "$cname" --network "$NETWORK_NAME" "${env_args[@]}" "$IMAGE" >/dev/null
  PLUGIN_CONTAINERS+=("$cname")

  ready=0
  for _ in $(seq 1 30); do
    if docker exec "$cname" /usr/bin/python3 -c '
import sys
import urllib.request
r1 = urllib.request.urlopen("http://localhost:8080/healthz", timeout=2)
assert r1.status == 200, r1.status
r2 = urllib.request.urlopen("http://localhost:8080/readyz", timeout=2)
assert r2.status == 200, r2.status
' >"$TMP_LOG" 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done

  if [ "$ready" -eq 1 ]; then
    echo "OK: $plugin -> /healthz 200, /readyz 200"
  else
    echo "FAIL: $plugin did not become healthy/ready"
    cat "$TMP_LOG"
    echo "  container logs:"
    docker logs "$cname" 2>&1 | tail -40
    FAILED_PLUGINS+=("$plugin")
  fi
  docker rm -f "$cname" >/dev/null 2>&1 || true
done

if [ "${#FAILED_PLUGINS[@]}" -gt 0 ]; then
  echo "FAIL: plugins did not become healthy: ${FAILED_PLUGINS[*]}"
  exit 1
fi
echo "OK: all six PLUGIN_TYPE values reached healthy+ready"

# --- 5. Evidence --------------------------------------------------------------
echo "-- [5/5] evidence --"
DIGEST="$(docker inspect "$IMAGE" --format '{{.Id}}')"
SIZE_BYTES="$(docker inspect "$IMAGE" --format '{{.Size}}')"
echo "IMAGE_DIGEST=${DIGEST}"
echo "IMAGE_SIZE_BYTES=${SIZE_BYTES}"

if docker image inspect "$BASELINE_IMAGE" >/dev/null 2>&1; then
  BASELINE_SIZE="$(docker inspect "$BASELINE_IMAGE" --format '{{.Size}}')"
  echo "BASELINE_IMAGE=${BASELINE_IMAGE}"
  echo "BASELINE_SIZE_BYTES=${BASELINE_SIZE}"
  if [ "$SIZE_BYTES" -ge "$BASELINE_SIZE" ]; then
    echo "FAIL: new image (${SIZE_BYTES} bytes) is not smaller than baseline (${BASELINE_SIZE} bytes)"
    exit 1
  fi
  PCT=$(( (BASELINE_SIZE - SIZE_BYTES) * 100 / BASELINE_SIZE ))
  echo "SIZE_REDUCTION_PCT=${PCT}"
else
  echo "WARN: baseline image ${BASELINE_IMAGE} not present locally — pull it to enable the size-reduction assertion (SC-001)."
fi

echo "== virtual-contributor image-verify: PASS =="
