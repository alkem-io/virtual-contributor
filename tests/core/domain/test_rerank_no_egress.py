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

#: Every module on the re-ranking path.
_RERANK_MODULES = (
    "core/ports/reranker.py",
    "core/domain/rerank.py",
    "core/domain/lexical_score.py",
)

#: Anything that could open a connection, plus the layers that own one.
_FORBIDDEN_IMPORTS = frozenset({
    "httpx", "requests", "aiohttp", "openai", "socket", "urllib",
    "http", "http.client", "ftplib", "smtplib", "telnetlib",
    "core.adapters", "plugins", "core.ports.knowledge_store",
})

#: Re-ranking vendors whose APIs the story disqualifies.
_FORBIDDEN_VENDORS = ("cohere", "jina", "voyageai", "rerank_api")


def _imported_names(path: Path) -> set[str]:
    """Every module name imported by a file, via AST — not a text search.

    A regex over source would trip on the word "socket" in a docstring and
    would miss `from x import y`. The parse tree is the actual import graph.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestStaticNoNetworkImport:
    """US4-AS1 — nothing on this path can even reach the network."""

    @pytest.mark.parametrize("module", _RERANK_MODULES)
    def test_module_imports_nothing_that_can_perform_io(self, module: str) -> None:
        imported = _imported_names(_REPO_ROOT / module)
        for name in imported:
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

    def test_pyproject_and_lockfile_are_untouched(self) -> None:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/develop", "--",
             "pyproject.toml", "poetry.lock"],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert not result.stdout.strip(), (
            f"re-ranking must add no dependency; changed: {result.stdout.strip()}"
        )
