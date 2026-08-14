"""The story's binding privacy constraint, made mechanical.

vc#23 states: "no user content leaves the infrastructure boundary. Any
re-ranking solution must run locally", and disqualifies the Cohere/Jina rerank
APIs on exactly that basis. A comment saying so would decay; these tests fail
the build instead.

Scope note, stated plainly because it matters: this proves the *re-ranking
step* performs no I/O. It does not — and cannot — claim the service as a whole
keeps content on-box. Embeddings and generation already call third-party
endpoints (Scaleway, Mistral) on every query. Re-ranking adds no new egress;
eliminating the existing egress is a platform-level question, not this
feature's.
"""

from __future__ import annotations

import ast
import socket
import subprocess
from pathlib import Path

import pytest

from core.domain.rerank import LexicalReranker

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Entry points to the re-ranking path. The scan walks outward from these
#: through first-party imports, so a module added later is covered without
#: anyone remembering to list it here — the failure mode a fixed list has.
_RERANK_ENTRY_MODULES = (
    "core/ports/reranker.py",
    "core/domain/rerank.py",
    "core/domain/lexical_score.py",
)

#: Anything that could open a connection, plus the layers that own one.
_FORBIDDEN_IMPORTS = frozenset({
    "httpx", "requests", "aiohttp", "openai", "socket", "urllib",
    "http", "http.client", "ftplib", "smtplib", "telnetlib",
    "asyncio", "ssl", "importlib",
    "core.adapters", "plugins", "core.ports.knowledge_store",
})

#: Re-ranking vendors whose APIs the story disqualifies.
_FORBIDDEN_VENDORS = ("cohere", "jina", "voyageai", "rerank_api")


def _imported_names(path: Path) -> set[str]:
    """Every module name imported by a file, via AST — not a text search.

    A regex over source would trip on the word "socket" in a docstring and
    would miss `from x import y`. The parse tree is the actual import graph.

    ``from pkg import name`` yields **both** ``pkg`` and ``pkg.name``. Keeping
    only ``pkg`` was a hole in the transitive walk: ``from core.domain import
    helper`` resolved to ``core/domain/__init__.py`` and the walk stopped
    there, so ``core/domain/helper.py`` — which could import httpx and send
    member content off-box — was never scanned.

    Relative imports are resolved against the importing file's own package,
    since ``node.module`` alone discards the level and a `from . import x`
    would otherwise vanish from the graph entirely.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_base(path, node)
            if base is None:
                continue
            if base:
                names.add(base)
            # The imported members themselves may be submodules, not just
            # attributes. Emitting both lets _module_path decide which.
            names.update(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
                if alias.name != "*"
            )
    return names


def _absolute_base(path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve an ``ImportFrom`` to an absolute dotted package.

    ``level`` is the number of leading dots; it must be walked up from the
    importing file's own package or a relative import silently leaves the
    scan. Returns ``None`` when the import escapes the repo root.
    """
    if not node.level:
        return node.module or ""
    package = path.parent
    for _ in range(node.level - 1):
        package = package.parent
    try:
        rel = package.relative_to(_REPO_ROOT)
    except ValueError:
        return None
    prefix = ".".join(rel.parts)
    if node.module:
        return f"{prefix}.{node.module}" if prefix else node.module
    return prefix


def _module_path(dotted: str) -> Path | None:
    """Map a first-party dotted name to a file, if it is one of ours."""
    candidate = _REPO_ROOT / (dotted.replace(".", "/") + ".py")
    if candidate.is_file():
        return candidate
    package = _REPO_ROOT / dotted.replace(".", "/") / "__init__.py"
    return package if package.is_file() else None


def _reachable_modules() -> dict[str, Path]:
    """Every first-party module reachable from the re-ranking entry points.

    Transitive on purpose. A scan of three hardcoded files proves only that
    *those three* are clean — someone adding a helper module that performs I/O
    and importing it from `rerank.py` would pass such a scan while sending
    member content off-box. Walking the graph means new modules are covered
    the moment they join the path.
    """
    found: dict[str, Path] = {}
    queue = [_REPO_ROOT / m for m in _RERANK_ENTRY_MODULES]
    while queue:
        path = queue.pop()
        key = str(path.relative_to(_REPO_ROOT))
        if key in found:
            continue
        found[key] = path
        for name in _imported_names(path):
            resolved = _module_path(name)
            if resolved is not None:
                queue.append(resolved)
    return found


class TestTheScanResolvesMemberAndRelativeImports:
    """The walk is only a privacy guard if it cannot be stepped around.

    Both cases below are ways a module that performs I/O could join the
    re-ranking path while the scan reported it clean — which is worse than no
    scan, because the green test is what stops anyone looking.
    """

    def test_member_imports_yield_the_submodule_not_just_the_package(
        self, tmp_path: Path,
    ) -> None:
        """`from core.domain import helper` must reach helper.py.

        Retaining only `node.module` resolved this to `core/domain/__init__.py`
        and stopped: the helper itself was never scanned.
        """
        probe = tmp_path / "probe.py"
        probe.write_text("from core.domain import lexical_score\n", encoding="utf-8")
        names = _imported_names(probe)
        assert "core.domain.lexical_score" in names

    def test_relative_imports_keep_their_package_level(self) -> None:
        """`from . import x` inside core/domain must resolve to core.domain.x.

        Dropping the level made these vanish from the graph entirely.
        """
        probe = _REPO_ROOT / "core" / "domain" / "_probe_relative.py"
        probe.write_text(
            "from . import lexical_score\nfrom .lexical_score import lexical_scores\n",
            encoding="utf-8",
        )
        try:
            names = _imported_names(probe)
        finally:
            probe.unlink()
        assert "core.domain.lexical_score" in names

    def test_a_member_imported_helper_is_actually_walked(self) -> None:
        """End to end: a helper reached only via `from pkg import member`
        must appear in the reachable set, so its own imports get checked."""
        helper = _REPO_ROOT / "core" / "domain" / "_probe_helper.py"
        helper.write_text("VALUE = 1\n", encoding="utf-8")
        entry = _REPO_ROOT / "core" / "domain" / "_probe_entry.py"
        entry.write_text(
            "from core.domain import _probe_helper\n", encoding="utf-8",
        )
        try:
            found: dict[str, Path] = {}
            queue = [entry]
            while queue:
                path = queue.pop()
                key = str(path.relative_to(_REPO_ROOT))
                if key in found:
                    continue
                found[key] = path
                for name in _imported_names(path):
                    resolved = _module_path(name)
                    if resolved is not None:
                        queue.append(resolved)
        finally:
            entry.unlink()
            helper.unlink()
        assert "core/domain/_probe_helper.py" in found


class TestStaticNoNetworkImport:
    """US4-AS1 — nothing on this path can even reach the network."""

    def test_the_scan_actually_reaches_the_whole_path(self) -> None:
        """Guard the guard: an empty or truncated walk would pass vacuously."""
        reachable = _reachable_modules()
        for entry in _RERANK_ENTRY_MODULES:
            assert entry in reachable
        # rerank.py imports lexical_score.py — if the walk is not transitive,
        # this is the first thing that stops being true.
        assert "core/domain/lexical_score.py" in reachable

    def test_no_module_on_the_path_can_perform_io(self) -> None:
        for module, path in _reachable_modules().items():
            for name in _imported_names(path):
                root = name.split(".")[0]
                assert name not in _FORBIDDEN_IMPORTS, f"{module} imports {name}"
                assert root not in _FORBIDDEN_IMPORTS, f"{module} imports {name}"
                assert not name.startswith("core.adapters"), f"{module} imports {name}"
                assert not name.startswith("plugins"), f"{module} imports {name}"


class TestRuntimeNoEgress:
    """US4-AS2 / SC-005 — a static scan can miss a dynamic import.

    So prove it at runtime: break sockets outright and re-rank anyway.
    """

    def test_rerank_completes_with_sockets_poisoned(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _no_sockets(*args: object, **kwargs: object) -> None:
            raise AssertionError("re-ranking attempted to open a socket")

        monkeypatch.setattr(socket, "socket", _no_sockets)
        monkeypatch.setattr(socket, "create_connection", _no_sockets)

        order = LexicalReranker().rerank(
            "how do I invite members to a space",
            ["a generic page about spaces", "how to invite members to a space"],
            [0.9, 0.55],
        )
        assert sorted(order) == [0, 1]


class TestVendorsStayDisqualified:
    """US4-AS3 — Option A must not creep back in later."""

    @pytest.mark.parametrize("vendor", _FORBIDDEN_VENDORS)
    def test_no_rerank_vendor_is_imported_or_called(self, vendor: str) -> None:
        """Match usage, not the letters.

        A bare substring search flags the word "coherence" in an unrelated
        prompt template, which is noise that would train people to ignore this
        test. Anchor on how a vendor SDK actually appears in code: an import,
        an attribute access, or a client construction.
        """
        pattern = (
            rf"(^|[^A-Za-z_]){vendor}\s*\.|"
            rf"\bimport\s+{vendor}\b|"
            rf"\bfrom\s+{vendor}[\s.]"
        )
        result = subprocess.run(
            ["grep", "-rEil", "--include=*.py", pattern, "core", "plugins"],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert not result.stdout.strip(), (
            f"{vendor} is used in: {result.stdout.strip()} — the story "
            f"disqualifies third-party rerank APIs"
        )


class TestNoNewDependency:
    """The distroless image contract: re-ranking must add no runtime dep.

    There is no GPU in this deployment and the runtime image has a size floor,
    so torch/sentence-transformers cannot ship here. Guarded mechanically
    because "restore fidelity to the story by adding the real model" is a
    plausible and well-intentioned future change.
    """

    def test_no_model_dependency_is_locked(self) -> None:
        """Asserted against the lock's CONTENT, not against a diff.

        A whole-file diff to origin/develop fails on any integration branch
        where a sibling feature legitimately touched the lock (observability
        added its OTLP exporter), and passes vacuously on a shallow checkout.
        What re-ranking must guarantee is narrower and checkable directly: no
        model runtime is in the dependency set.
        """
        lock = (_REPO_ROOT / "poetry.lock").read_text(encoding="utf-8")
        for package in (
            "torch", "sentence-transformers", "transformers", "onnxruntime",
            "xgboost", "lightgbm",
        ):
            assert f'name = "{package}"' not in lock, (
                f"re-ranking must not pull in {package}: no GPU exists in this "
                f"deployment and the runtime image has a size floor"
            )

    def test_no_heavy_ml_dependency_declared(self) -> None:
        """A base-ref-independent backstop for the guard above.

        This one cannot pass vacuously: it reads the manifest directly, so it
        holds in a shallow checkout where the diff cannot run. Re-ranking must
        stay stdlib-only — there is no GPU here and the runtime image has a
        size floor.
        """
        manifest = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for package in ("torch", "sentence-transformers", "transformers",
                        "rank_bm25", "scikit-learn", "faiss"):
            assert f'\n{package} ' not in manifest, f"{package} was added"
            assert f'"{package}"' not in manifest, f"{package} was added"
