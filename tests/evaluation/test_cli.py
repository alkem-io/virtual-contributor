"""Frozen CLI authority and evaluation-identity contracts."""

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


def _run_real_expert_cli(monkeypatch, tmp_path, ambient_plugin: str) -> None:
    """Drive Click, the real evaluation setup, and Expert construction end to end."""
    from core.container import Container
    from core.ports.knowledge_store import KnowledgeStorePort
    from core.ports.llm import LLMPort
    from evaluation.cli import cli
    from plugins.expert.plugin import ExpertPlugin
    from tests.conftest import MockKnowledgeStorePort, MockLLMPort

    class Scorer:
        def __init__(self, _metrics) -> None:
            pass
        async def score(self, **_kwargs):
            return {
                "faithfulness": 0.5, "answer_relevancy": 0.5,
                "context_precision": 0.5, "context_recall": 0.5,
            }

    def adapters(_config, container: Container, *_args) -> None:
        llm = MockLLMPort(response="answer")
        llm._llm = object()
        container.register(LLMPort, llm)
        container.register(KnowledgeStorePort, MockKnowledgeStorePort())

    class Embeddings:
        def __init__(self, **_kwargs) -> None:
            pass

    test_set = tmp_path / "cases.jsonl"
    test_set.write_text(
        '{"question":"q","expected_answer":"a","relevant_documents":["d"]}\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUGIN_TYPE", ambient_plugin)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://local")
    monkeypatch.setattr("main._create_adapters", adapters)
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda *_: ExpertPlugin)
    monkeypatch.setattr("evaluation.runner.Scorer", Scorer)
    monkeypatch.setattr("evaluation.metrics.create_metrics", lambda *_args: [])
    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings", Embeddings)
    result = CliRunner().invoke(
        cli,
        ["run", "--plugin", "EXPERT", "--corpus-revision", "r1", "--test-set", str(test_set)],
    )
    assert result.exit_code == 0, result.output
    raw = next((tmp_path / "evaluations").glob("*.json")).read_text()
    assert '"plugin_type": "expert"' in raw


def test_expert_cli_selection_overrides_blank_plugin_identity(monkeypatch, tmp_path) -> None:
    _run_real_expert_cli(monkeypatch, tmp_path, "")


def test_expert_cli_selection_overrides_generic_plugin_identity(monkeypatch, tmp_path) -> None:
    _run_real_expert_cli(monkeypatch, tmp_path, "generic")


def test_expert_cli_selection_overrides_conflicting_plugin_identity(
    monkeypatch, tmp_path,
) -> None:
    _run_real_expert_cli(monkeypatch, tmp_path, "guidance")


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


# ---------------------------------------------------------------------------
# --category scoping
# ---------------------------------------------------------------------------


def test_run_rejects_unknown_category_before_test_set_load(monkeypatch) -> None:
    """Click's Choice type must fail before _run_evaluation (and thus the
    test set and pipeline) is ever touched."""
    called = False

    async def record(*_args):
        nonlocal called
        called = True

    monkeypatch.setattr("evaluation.cli._run_evaluation", record)
    result = CliRunner().invoke(
        cli, ["run", "--plugin", "guidance", "--category", "not-a-real-category"]
    )
    assert result.exit_code != 0
    assert "documentation" in result.output
    assert "building-alkemio" in result.output
    assert "design-thinker" in result.output
    assert called is False


def test_run_category_selecting_zero_cases_fails_fast_before_pipeline_boot(
    tmp_path, monkeypatch
) -> None:
    """A known category that matches nothing in this test set is a distinct,
    dataset-shaped failure — not the same message as an unknown category —
    and must exit before any pipeline construction."""
    test_set = tmp_path / "cases.jsonl"
    test_set.write_text(
        '{"question":"q1","expected_answer":"a1","category":"documentation"}\n'
    )

    def boot_guard(*_args, **_kwargs):
        raise AssertionError("pipeline must not be constructed on zero-case scope")

    monkeypatch.setattr("evaluation.pipeline_invoker.PipelineInvoker", boot_guard)
    result = CliRunner().invoke(
        cli,
        [
            "run",
            "--plugin",
            "guidance",
            "--test-set",
            str(test_set),
            "--category",
            "design-thinker",
        ],
    )
    assert result.exit_code != 0
    assert "design-thinker" in result.output
    assert "zero cases" in result.output


def test_run_category_flows_through_to_evaluation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def record(*args):
        captured["category"] = args[5]

    def consume(coro):
        try:
            coro.send(None)
        except StopIteration:
            pass

    monkeypatch.setattr("evaluation.cli._run_evaluation", record)
    monkeypatch.setattr("evaluation.cli.asyncio.run", consume)
    result = CliRunner().invoke(
        cli, ["run", "--plugin", "guidance", "--category", "documentation"]
    )
    assert result.exit_code == 0, result.output
    assert captured["category"] == "documentation"


def test_run_omitting_category_defaults_to_none(monkeypatch) -> None:
    """Omitting --category MUST run all categories, preserving current
    behaviour."""
    captured: dict[str, object] = {}

    async def record(*args):
        captured["category"] = args[5]

    def consume(coro):
        try:
            coro.send(None)
        except StopIteration:
            pass

    monkeypatch.setattr("evaluation.cli._run_evaluation", record)
    monkeypatch.setattr("evaluation.cli.asyncio.run", consume)
    result = CliRunner().invoke(cli, ["run", "--plugin", "guidance"])
    assert result.exit_code == 0, result.output
    assert captured["category"] is None


def test_category_scope_reaches_evaluation_runner_run(monkeypatch, tmp_path) -> None:
    """The tests above only pin that --category reaches _run_evaluation's own
    argument. They never exercise what _run_evaluation does with it, so a
    typo that drops the value before EvaluationRunner.run(category_scope=...)
    would leave the suite green. Drive the real _run_evaluation body and
    assert the value actually lands on the runner call."""
    from core.container import Container
    from core.ports.knowledge_store import KnowledgeStorePort
    from core.ports.llm import LLMPort
    from plugins.guidance.plugin import GuidancePlugin
    from tests.conftest import MockKnowledgeStorePort, MockLLMPort
    from tests.evaluation.test_report import _make_run

    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, pipeline_invoker, scorer, *args, **kwargs) -> None:
            pass

        async def run(self, *_args, **kwargs):
            captured["category_scope"] = kwargs.get("category_scope")
            return _make_run("run", plugin_type="guidance")

    def adapters(_config, container: Container, *_args) -> None:
        llm = MockLLMPort(response="answer")
        llm._llm = object()
        container.register(LLMPort, llm)
        container.register(KnowledgeStorePort, MockKnowledgeStorePort())

    class Embeddings:
        def __init__(self, **_kwargs) -> None:
            pass

    test_set = tmp_path / "cases.jsonl"
    test_set.write_text(
        '{"question":"q","expected_answer":"a","category":"documentation"}\n'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://local")
    monkeypatch.setattr("main._create_adapters", adapters)
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda *_: GuidancePlugin)
    monkeypatch.setattr("evaluation.runner.EvaluationRunner", FakeRunner)
    monkeypatch.setattr("evaluation.metrics.create_metrics", lambda *_args: [])
    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings", Embeddings)

    result = CliRunner().invoke(
        cli,
        [
            "run",
            "--plugin",
            "guidance",
            "--test-set",
            str(test_set),
            "--category",
            "documentation",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["category_scope"] == "documentation"
