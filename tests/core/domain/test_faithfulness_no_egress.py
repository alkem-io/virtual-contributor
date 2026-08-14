"""Validation must stay local and free.

The story's own acceptance criterion asks for local validation. Two of its
three recommended mechanisms would not be: an LLM judge calls Mistral or
Scaleway, and a local NLI model needs a GPU that does not exist here. What
ships instead performs no I/O at all — and these tests keep it that way,
because "add a judge behind the port" is a small and well-intentioned change.

Scope, stated plainly: this proves the *validation step* performs no I/O. It is
not a claim that the service keeps content on-box. Generation itself already
calls a third-party API with the same answer and context.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from core.domain.faithfulness import ContextSufficiencyValidator

_REPO_ROOT = Path(__file__).resolve().parents[3]

_ENTRY_MODULES = (
    "core/ports/faithfulness.py",
    "core/domain/faithfulness.py",
)

#: An ALLOW-list, not a deny-list. A deny-list can only name the clients
#: someone has already thought of — review demonstrated a bypass using
#: `langchain_openai`, which is how this repo's own LLM adapters reach
#: Mistral, and which no plausible deny-list would have contained. Permitting
#: a tiny set instead means an unknown future client fails by construction.
_ALLOWED_IMPORTS = frozenset({
    "__future__", "re", "dataclasses", "typing", "enum", "math", "string",
    "core.ports.faithfulness", "core.domain.faithfulness",
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
    """Walk first-party imports outward — transitive, not a fixed list.

    A helper module added later and imported from the validator would pass a
    two-file scan while making the call this file exists to prevent.
    """
    found: dict[str, Path] = {}
    queue = [_REPO_ROOT / m for m in _ENTRY_MODULES]
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


def _port_implementations() -> dict[str, Path]:
    """Every class under core/ defining `validate`.

    The guarantee belongs to the SEAM. Pinning the shipped module would leave a
    sibling implementation — an LLM judge, say — completely unguarded, while
    both plugins would accept it.
    """
    found: dict[str, Path] = {}
    # The whole repo, not just core/. Injection imposes no location
    # constraint, so review showed the same class in plugins/ was invisible to
    # a core/-only sweep while importing httpx outright.
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in {"tests", ".venv", "__pycache__"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                b.name for b in node.body
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if "validate" in methods:
                found[str(path.relative_to(_REPO_ROOT))] = path
    return found


class TestStaticNoNetworkImport:
    def test_the_scan_reaches_the_whole_path(self) -> None:
        """Guard the guard — a truncated walk would pass vacuously."""
        reachable = _reachable_modules()
        for entry in _ENTRY_MODULES:
            assert entry in reachable

    def test_no_module_on_the_path_can_perform_io(self) -> None:
        for module, path in _reachable_modules().items():
            for name in _imported_names(path):
                assert name in _ALLOWED_IMPORTS, (
                    f"{module} imports {name}, which is not on the allow-list; "
                    f"the validation path must stay pure"
                )

    def test_the_shipped_validator_is_discovered(self) -> None:
        assert "core/domain/faithfulness.py" in _port_implementations()

    def test_no_port_implementation_can_perform_io(self) -> None:
        for module, path in _port_implementations().items():
            for name in _imported_names(path):
                assert name in _ALLOWED_IMPORTS, (
                    f"{module} implements the validator port and imports "
                    f"{name}, which is not on the allow-list"
                )


class TestRuntimeNoEgress:
    def test_validation_completes_with_sockets_poisoned(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _no_sockets(*args: object, **kwargs: object) -> None:
            raise AssertionError("validation attempted to open a socket")

        monkeypatch.setattr(socket, "socket", _no_sockets)
        monkeypatch.setattr(socket, "create_connection", _no_sockets)

        validator = ContextSufficiencyValidator()
        for answer, context in (
            ("a fabrication", ""),
            ("I don't know.", ""),
            ("a real answer", "some context"),
        ):
            assert validator.validate(answer=answer, context=context) is not None


class TestNoNewDependency:
    def test_no_ml_dependency_was_added(self) -> None:
        """No NLI model, no torch — there is no GPU and the image has a floor.

        Reads the manifest directly so it cannot pass vacuously in a shallow
        CI checkout, unlike a git-diff-based guard.
        """
        manifest = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for package in ("torch", "sentence-transformers", "transformers",
                        "nli", "scikit-learn"):
            assert f'\n{package} ' not in manifest, f"{package} was added"
            assert f'"{package}"' not in manifest, f"{package} was added"
