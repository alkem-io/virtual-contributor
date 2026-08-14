"""The gate decides whether to make a network call; it must not make one.

`should_rewrite` and `validate_rewrite` run ahead of retrieval on every turn
carrying history. Their entire value is avoiding an LLM round-trip, so an
import that reaches the network would defeat the feature rather than merely
slow it.

`rewrite_query` is the exception and is excluded by name: it exists to *await*
the caller's LLM. It receives that LLM as an argument and imports no client.

Structured as an ALLOW-list. A deny-list can only name the clients someone has
already thought of — review of a sibling feature bypassed one with
`langchain_openai`, which is this repo's own route to Mistral and which no
plausible deny-list would have contained.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _REPO_ROOT / "core/domain/query_rewrite.py"

#: Everything the gate is permitted to import, transitively.
_ALLOWED_IMPORTS = frozenset({"__future__", "logging", "typing"})

#: Names that would let this module reach the network on its own.
_NETWORK_CALLS = ("httpx", "requests", "aiohttp", "socket", "urllib", "openai")


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _reachable_modules() -> dict[str, Path]:
    """Walk first-party imports transitively — a direct-import check is
    bypassed by one level of indirection."""
    seen: dict[str, Path] = {"core.domain.query_rewrite": _MODULE}
    queue = [_MODULE]
    while queue:
        for name in _imported_names(queue.pop()):
            if not name.startswith(("core.", "plugins.")) or name in seen:
                continue
            candidate = _REPO_ROOT / (name.replace(".", "/") + ".py")
            if candidate.exists():
                seen[name] = candidate
                queue.append(candidate)
    return seen


class TestTheGateMakesNoNetworkCall:
    def test_no_module_on_the_gate_path_imports_anything_unexpected(self) -> None:
        for module, path in _reachable_modules().items():
            for name in _imported_names(path):
                assert name in _ALLOWED_IMPORTS, (
                    f"{module} imports {name}, which is not on the allow-list; "
                    f"the gate must stay pure"
                )

    @pytest.mark.parametrize("client", _NETWORK_CALLS)
    def test_no_network_client_appears_anywhere(self, client: str) -> None:
        source = _MODULE.read_text(encoding="utf-8")
        code = "\n".join(
            line.split("#")[0] for line in source.splitlines()
        )
        assert client not in code, f"{client} reached the gate"

    def test_the_decision_functions_are_synchronous(self) -> None:
        """An async signature on the gate would invite a call behind it.

        `rewrite_query` is deliberately async — it awaits the caller's LLM.
        """
        import inspect

        from core.domain import query_rewrite

        assert not inspect.iscoroutinefunction(query_rewrite.should_rewrite)
        assert not inspect.iscoroutinefunction(query_rewrite.validate_rewrite)
        assert inspect.iscoroutinefunction(query_rewrite.rewrite_query)


class TestTheModuleDoesNotBindToTheUnmergedClassifier:
    """C-11 — this feature must build and ship on `develop` alone.

    The classifier that will supply a policy lives on an unmerged PR sitting in
    a seven-way pile-up on the same files. Importing it — at module scope, in a
    function, or under `TYPE_CHECKING` — would make this feature hostage to a
    merge order nobody controls.
    """

    @pytest.mark.parametrize(
        "forbidden",
        ["core.domain.rule_classifier", "core.ports.query_router",
         "RuleQueryClassifier", "RouteClass"],
    )
    def test_the_unmerged_classifier_is_not_referenced(self, forbidden: str) -> None:
        source = _MODULE.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert forbidden not in code, (
            f"{forbidden} is only on the unmerged PR; the gate defines its own "
            f"one-method protocol instead"
        )

    def test_the_module_imports_on_a_bare_develop_checkout(self) -> None:
        """The classifier does not exist on this base at all."""
        import importlib

        assert importlib.import_module("core.domain.query_rewrite") is not None
        with pytest.raises(ImportError):
            importlib.import_module("core.domain.rule_classifier")


class TestThePolicySeamIsPureToo:
    """The guard above proves `query_rewrite.py` is pure — but the policy it
    consults is a duck-typed object injected from `main.py`, which that walk
    never reaches.

    `RewritePolicy` is `@runtime_checkable`, so any object with
    `should_skip_rewrite` is accepted. A future policy doing I/O would satisfy
    the Protocol, pass every test above, and block the event loop inside
    `should_rewrite` — reintroducing exactly the call this gate removes.
    """

    def test_the_shipped_policy_module_imports_no_network_client(self) -> None:
        """`main.py` legitimately imports plenty; what matters is that the
        policy's own logic is a membership test and a delegated classify."""
        import inspect

        import main

        source = inspect.getsource(main._ConversationalSkipPolicy)
        for client in _NETWORK_CALLS:
            assert client not in source, f"{client} reached the policy"

    def test_the_shipped_policy_decides_without_blocking(self) -> None:
        """Timed at the seam, so an I/O-performing policy fails here even if it
        imports nothing this test can name."""
        import time

        import main

        class _Classifier:
            def classify(self, message: str):
                raise RuntimeError("unavailable")

        policy = main._ConversationalSkipPolicy(_Classifier(), object())
        start = time.perf_counter()
        for _ in range(1_000):
            policy.should_skip_rewrite("thanks!")
        per_call_ms = (time.perf_counter() - start) * 1000 / 1_000
        assert per_call_ms < 1.0, f"{per_call_ms:.3f}ms per decision"

    def test_should_skip_rewrite_is_synchronous_on_the_shipped_policy(self) -> None:
        import inspect

        import main

        assert not inspect.iscoroutinefunction(
            main._ConversationalSkipPolicy.should_skip_rewrite
        )
