"""Frozen CLI authority and evaluation-identity contracts (C-23/C-27)."""

from __future__ import annotations

from click.testing import CliRunner
import pytest
from evaluation.cli import cli


def test_cli_never_renders_missing_required_metric_as_zero(tmp_path, monkeypatch):
    """The real list command labels unavailable evidence instead of zeroing it."""
    import json

    directory = tmp_path / "evaluations"
    directory.mkdir()
    (directory / "malformed.json").write_text("{")
    (directory / "partial.json").write_text(json.dumps({
        "id": "partial", "plugin_type": "expert", "test_case_count": 1,
        "success_count": 1, "failure_count": 0,
        "aggregate": {"faithfulness": {"mean": 0.2}},
    }))
    (directory / "failed.json").write_text(json.dumps({
        "id": "failed", "plugin_type": "expert", "test_case_count": 1,
        "success_count": 0, "failure_count": 1, "aggregate": {},
    }))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "invalid" in result.output
    assert "incomplete" in result.output
    assert "N/A" in result.output
    assert "0.000" not in result.output


@pytest.mark.parametrize("bad_statistic", [float("nan"), float("inf"), -0.1, 1.1, True, "0.5"])
def test_cli_never_marks_invalid_aggregate_statistics_complete(
    tmp_path, monkeypatch, bad_statistic
) -> None:
    import json

    directory = tmp_path / "evaluations"
    directory.mkdir()
    aggregate = {
        metric: {"mean": 0.5, "median": 0.5, "min": 0.5, "max": 0.5}
        for metric in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    }
    aggregate["faithfulness"]["median"] = bad_statistic
    (directory / "invalid.json").write_text(json.dumps({
        "id": "invalid", "plugin_type": "expert", "test_case_count": 1,
        "success_count": 1, "failure_count": 0, "aggregate": aggregate,
    }))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "complete" not in result.output
    assert "invalid" in result.output
    assert result.output.count("N/A") == 4


def test_cli_accepts_exact_metric_boundaries_and_honest_all_failed_run() -> None:
    from evaluation.cli import _list_run_state

    aggregate = {
        metric: {"mean": 0, "median": 1, "min": 0, "max": 1}
        for metric in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    }
    assert _list_run_state({
        "test_case_count": 1, "success_count": 1, "failure_count": 0,
        "aggregate": aggregate,
    }) == ("complete", ("0.000",) * 4)
    assert _list_run_state({
        "test_case_count": 1, "success_count": 0, "failure_count": 1,
        "aggregate": {},
    }) == ("N/A", ("N/A",) * 4)


def test_cli_rejects_zero_success_nonempty_aggregate(tmp_path, monkeypatch) -> None:
    """A report cannot claim aggregate evidence when no case succeeded."""
    import json

    directory = tmp_path / "evaluations"
    directory.mkdir()
    aggregate = {
        metric: {"mean": 0.5, "median": 0.5, "min": 0.5, "max": 0.5}
        for metric in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    }
    (directory / "zero-success.json").write_text(json.dumps({
        "id": "zero-success", "plugin_type": "expert", "test_case_count": 1,
        "success_count": 0, "failure_count": 1, "aggregate": aggregate,
    }))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "complete" not in result.output
    assert "0.500" not in result.output
    assert result.output.count("N/A") == 4


def test_cli_handles_arbitrary_size_json_integer_as_invalid(tmp_path, monkeypatch) -> None:
    """Display-only parsing must not overflow on a syntactically valid JSON int."""
    import json

    directory = tmp_path / "evaluations"
    directory.mkdir()
    giant_integer = "1" + ("0" * 400)
    metric_names = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    aggregate = ",".join(
        f'{json.dumps(metric)}:{{"mean":{giant_integer if metric == "faithfulness" else "0.5"},'
        '"median":0.5,"min":0.5,"max":0.5}'
        for metric in metric_names
    )
    (directory / "giant-integer.json").write_text(
        "{"
        '\"id\":\"giant-integer\",\"plugin_type\":\"expert\",'
        '\"test_case_count\":1,\"success_count\":1,\"failure_count\":0,'
        f'\"aggregate\":{{{aggregate}}}'
        "}"
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "error reading" not in result.output
    assert "complete" not in result.output
    assert "invalid" in result.output
    assert result.output.count("N/A") == 4


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
    assert (
        _run_command(monkeypatch, "expert", "--corpus-revision", "r1")["plugin"]
        == "expert"
    )


def test_expert_cli_selection_overrides_generic_plugin_identity(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_TYPE", "generic")
    assert (
        _run_command(monkeypatch, "expert", "--corpus-revision", "r1")["plugin"]
        == "expert"
    )


def test_expert_cli_selection_overrides_conflicting_plugin_identity(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PLUGIN_TYPE", "guidance")
    assert (
        _run_command(monkeypatch, "EXPERT", "--corpus-revision", "r1")["plugin"]
        == "expert"
    )


def test_expert_run_requires_safe_corpus_revision() -> None:
    result = CliRunner().invoke(cli, ["run", "--plugin", "expert"])
    assert result.exit_code != 0 and "requires --corpus-revision" in result.output


def test_guidance_run_does_not_claim_expert_pairing_identity(monkeypatch) -> None:
    assert _run_command(monkeypatch, "guidance") == {
        "plugin": "guidance",
        "corpus_revision": None,
    }


def test_cli_rejects_contradictory_persisted_evaluation_reports(
    tmp_path, monkeypatch
) -> None:
    """The public compare boundary fails closed before it can emit a delta."""
    directory = tmp_path / "evaluations"
    directory.mkdir()
    # Valid Pydantic shape, contradictory inventory (zero cases, one success).
    payload = {
        "id": "flat",
        "timestamp": "t",
        "plugin_type": "expert",
        "composition_identity_version": 5,
        "hierarchy_mode": "flat",
        "test_set_digest": "a" * 64,
        "body_of_knowledge_digest": "b" * 64,
        "corpus_revision": "r",
        "successful_case_digests": [],
        "invariant_composition_fingerprint": "c" * 64,
        "full_composition_fingerprint": "d" * 64,
        "test_set_path": "x",
        "test_case_count": 0,
        "success_count": 1,
        "failure_count": 0,
        "duration_seconds": 0,
        "aggregate": {},
        "cases": [],
    }
    (directory / "flat.json").write_text(__import__("json").dumps(payload))
    payload["id"] = "on"
    payload["hierarchy_mode"] = "hierarchical"
    payload["full_composition_fingerprint"] = "e" * 64
    (directory / "on.json").write_text(__import__("json").dumps(payload))
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(cli, ["compare", "flat", "on"]).exit_code != 0


def test_nominal_v5_fixture_is_self_consistent(tmp_path, monkeypatch) -> None:
    from tests.evaluation.test_report import _make_run

    directory = tmp_path / "evaluations"
    directory.mkdir()
    flat, on = _make_run("flat"), _make_run("current")
    (directory / "flat.json").write_text(flat.model_dump_json())
    (directory / "on.json").write_text(on.model_dump_json())
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(cli, ["compare", "flat", "on"]).exit_code == 0
