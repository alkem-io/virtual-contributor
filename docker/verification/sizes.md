# Image size / digest evidence (US5-AS1, SC-001)

Baseline: `alkemio/virtual-contributor:v0.1.2` (pre-distroless, local Docker Hub
pull pinned in dev-orchestration), measured both via `docker save | wc -c` and
`docker inspect --format '{{.Size}}'` (the two agree to the byte — no
buildx-attestation-manifest skew on this baseline tag).

| Image | Digest (`docker inspect --format '{{.Id}}'`) | Size (bytes) | Reduction vs baseline |
|---|---|---|---|
| Baseline (`alkemio/virtual-contributor:v0.1.2`, pre-distroless) | `sha256:133a9d5d37468ba3babce678ba1fb10f0859b31746af353d48eb946d25b13513` | 195,118,141 | — |
| Pre-CVE-fix distroless (`026-distroless-rc1` — matched Python 3.13 pair, 20 HIGH/0 CRITICAL, 3 fixable) | `sha256:230a1f6f4d18dbc81524d3cf332750d8ab9f2ad51398a0e636d864c03cd98762` | 155,156,837 | 20.48% |
| **CVE-fix pass (this pass — `026-distroless-local`, 17 HIGH/0 CRITICAL, 0 fixable)** | `sha256:d748228d71cf0f11660d1a25010ed30d23943ddf7841cfbc7eb9971ac42a8984` | **85,182,827** | **56.34%** |

Comfortably clears the SC-001 40% floor even after the CVE-fix pass — the
reduction actually *improved* in this pass (20.48% → 56.34%), because the
fix for the `ragas` finding (see `US5-AS1-cve-assessment.md`) was to move
`ragas`/`click` out of `[tool.poetry.dependencies]` into the `dev` group:
`evaluation/` (the only code that imports `ragas`) is never copied into the
Docker runtime image, so `ragas` and its heavy transitive tree (scipy,
networkx, scikit-network, pillow, instructor, rich, typer) were pure dead
weight in every distroless build to date. Excluding them via the
Dockerfile's existing `poetry install --only main --no-root` shed ~70MB in
addition to the CVE fix itself. `click` and `docstring-parser` are *not* part
of this reduction — both remain in the shipped image via unrelated
`main`-group transitive paths (`langchain-mistralai`/`langchain-anthropic`);
see `US5-AS1-cve-assessment.md` for the reachability trace.

## Base image digests (this pass, unchanged from the original distroless build)

| Base | Tag | Digest |
|---|---|---|
| Builder | `python:3.13.7-slim-trixie` | `sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689` |
| Runtime | `gcr.io/distroless/python3-debian13:nonroot` | `sha256:0e52dfee02b1aba142e77b004f6ea11210b79456b51f10d70e9bd631cbc21d98` |

No base-image migration was needed this pass (contrast with `server`, which
had to move Debian 12 → 13 to clear its `libssl3` findings) — the VC
Dockerfile was already on the Debian 13/trixie pair from its initial build.

## Reproduce

```bash
docker build -t alkemio/virtual-contributor:026-distroless-local .
docker inspect alkemio/virtual-contributor:026-distroless-local --format '{{.Id}}'
docker inspect alkemio/virtual-contributor:026-distroless-local --format '{{.Size}}'
bash docker/image-verify.sh alkemio/virtual-contributor:026-distroless-local
```
