"""Frozen CLI authority and evaluation-identity contracts (C-23/C-27)."""
from __future__ import annotations

from click.testing import CliRunner
from evaluation.cli import cli


def _run_command(monkeypatch, plugin: str, *extra: str) -> dict[str, object]:
    captured: dict[str, object] = {}
    async def record(*args):
        captured.update(plugin=args[0], corpus_revision=args[4])
    def consume(coro):
        try:
            coro.send(None)
        except StopIteration:
            pass
    monkeypatch.setattr("evaluation.cli._run_evaluation", record)
    monkeypatch.setattr("evaluation.cli.asyncio.run", consume)
    result = CliRunner().invoke(cli, ["run", "--plugin", plugin, *extra])
    assert result.exit_code == 0, result.output
    return captured


def test_expert_cli_selection_overrides_blank_plugin_identity(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_TYPE", "")
    assert _run_command(monkeypatch, "expert", "--corpus-revision", "r1")["plugin"] == "expert"


def test_expert_cli_selection_overrides_generic_plugin_identity(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_TYPE", "generic")
    assert _run_command(monkeypatch, "expert", "--corpus-revision", "r1")["plugin"] == "expert"


def test_expert_cli_selection_overrides_conflicting_plugin_identity(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_TYPE", "guidance")
    assert _run_command(monkeypatch, "EXPERT", "--corpus-revision", "r1")["plugin"] == "expert"


def test_expert_run_requires_safe_corpus_revision() -> None:
    result = CliRunner().invoke(cli, ["run", "--plugin", "expert"])
    assert result.exit_code != 0 and "requires --corpus-revision" in result.output


def test_guidance_run_does_not_claim_expert_pairing_identity(monkeypatch) -> None:
    assert _run_command(monkeypatch, "guidance") == {"plugin": "guidance", "corpus_revision": None}
