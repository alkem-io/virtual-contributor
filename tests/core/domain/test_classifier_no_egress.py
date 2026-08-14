"""The classifier must stay local and free — this is what keeps it worth having.

An LLM-based classifier would cost a network round trip on **every** query,
including all the simple ones it exists to make faster. At a 350ms classifier
call, 39% of all traffic would have to hit the cheap path just to break even on
latency; nobody has measured that share for Alkemio, and the call would go to
Mistral or Scaleway over the public internet, not to a local model.

Both retrieval plugins already hold an `LLMPort`, so turning this into that
version is a two-line change someone could make in good faith. These tests make
it fail loudly instead.
"""

from __future__ import annotations

import ast
import socket
import time
from pathlib import Path

import pytest

from core.domain.rule_classifier import RuleQueryClassifier

_REPO_ROOT = Path(__file__).resolve().parents[3]

_CLASSIFIER_MODULES = (
    "core/ports/query_router.py",
    "core/domain/rule_classifier.py",
)

_FORBIDDEN_IMPORTS = frozenset({
    "httpx", "requests", "aiohttp", "openai", "socket", "urllib",
    "http", "http.client", "asyncio", "ssl", "importlib",
    "core.adapters", "plugins", "core.ports.llm",
    "core.ports.knowledge_store",
})


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _module_path(dotted: str) -> Path | None:
    candidate = _REPO_ROOT / (dotted.replace(".", "/") + ".py")
    if candidate.is_file():
        return candidate
    package = _REPO_ROOT / dotted.replace(".", "/") / "__init__.py"
    return package if package.is_file() else None


def _reachable_modules() -> dict[str, Path]:
    """Walk first-party imports outward from the classifier.

    Transitive rather than a fixed list: a helper module added later and
    imported from the classifier would pass a three-file scan while making the
    network call this whole test file exists to prevent.
    """
    found: dict[str, Path] = {}
    queue = [_REPO_ROOT / m for m in _CLASSIFIER_MODULES]
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


class TestStaticNoNetworkImport:
    def test_the_scan_reaches_the_whole_path(self) -> None:
        """Guard the guard — a truncated walk would pass vacuously."""
        reachable = _reachable_modules()
        for entry in _CLASSIFIER_MODULES:
            assert entry in reachable

    def test_no_module_on_the_path_can_perform_io(self) -> None:
        for module, path in _reachable_modules().items():
            for name in _imported_names(path):
                root = name.split(".")[0]
                assert name not in _FORBIDDEN_IMPORTS, f"{module} imports {name}"
                assert root not in _FORBIDDEN_IMPORTS, f"{module} imports {name}"
                assert not name.startswith("core.adapters"), f"{module}: {name}"
                assert not name.startswith("plugins"), f"{module}: {name}"

    def test_classify_is_synchronous(self) -> None:
        """An async signature would invite exactly the call this forbids."""
        import inspect

        assert not inspect.iscoroutinefunction(RuleQueryClassifier().classify)


class TestEveryImplementationIsLocal:
    """The guarantee belongs to the SEAM, not to one module.

    Scanning only the shipped classifier proves the shipped classifier is
    clean — it says nothing about which implementation gets injected. A
    sibling module implementing the same port and POSTing each question to
    Mistral would satisfy `QueryRouterPort`, be accepted by both plugins, and
    pass a module-pinned scan without a single test failing. So the scan is
    applied to every implementation of the port that exists in the tree.
    """

    @staticmethod
    def _port_implementations() -> dict[str, Path]:
        """Every module under core/ defining a class with a `classify` method."""
        found: dict[str, Path] = {}
        for path in (_REPO_ROOT / "core").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = {
                    b.name for b in node.body
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                if "classify" in methods:
                    found[str(path.relative_to(_REPO_ROOT))] = path
        return found

    def test_the_shipped_classifier_is_discovered(self) -> None:
        """Guard the guard — an empty sweep would pass vacuously."""
        assert "core/domain/rule_classifier.py" in self._port_implementations()

    def test_no_port_implementation_can_perform_io(self) -> None:
        for module, path in self._port_implementations().items():
            for name in _imported_names(path):
                root = name.split(".")[0]
                assert name not in _FORBIDDEN_IMPORTS, f"{module} imports {name}"
                assert root not in _FORBIDDEN_IMPORTS, f"{module} imports {name}"

    def test_main_injects_the_rule_classifier(self) -> None:
        """The injection point itself, so substitution is a visible change."""
        source = (_REPO_ROOT / "main.py").read_text(encoding="utf-8")
        assert 'deps["query_router"] = RuleQueryClassifier()' in source


class TestRuntimeNoEgress:
    def test_classification_completes_with_sockets_poisoned(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _no_sockets(*args: object, **kwargs: object) -> None:
            raise AssertionError("classification attempted to open a socket")

        monkeypatch.setattr(socket, "socket", _no_sockets)
        monkeypatch.setattr(socket, "create_connection", _no_sockets)

        classifier = RuleQueryClassifier()
        for message in ("hi", "what is the mission?", "compare A and B",
                        "explain how callouts work"):
            assert classifier.classify(message).route is not None


class TestCostIsNegligible:
    def test_classification_is_sub_millisecond(self) -> None:
        """The whole argument for rules over an LLM is that this is ~free.

        If it ever stops being ~free, the break-even arithmetic that justified
        this design stops holding — so it is asserted, not assumed.
        """
        classifier = RuleQueryClassifier()
        messages = [
            "hi", "what is the mission of this space?",
            "compare the goals of subspace A and subspace B",
            "explain how callouts work in detail please",
        ]
        start = time.perf_counter()
        for _ in range(500):
            for message in messages:
                classifier.classify(message)
        per_call_ms = (time.perf_counter() - start) * 1000 / (500 * len(messages))
        assert per_call_ms < 1.0, f"{per_call_ms:.4f}ms per classification"
