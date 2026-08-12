"""Evaluation remains independent of runtime tracing."""

import ast
from pathlib import Path


def test_evaluation_does_not_import_runtime_tracing() -> None:
    for source in Path("evaluation").glob("*.py"):
        tree = ast.parse(source.read_text())
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == "core.tracing"
            for node in ast.walk(tree)
        )
