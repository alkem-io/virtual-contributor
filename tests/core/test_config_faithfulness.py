"""Faithfulness config — off by default, and absent when off."""

from __future__ import annotations

from core.config import BaseConfig
from core.domain.faithfulness import ContextSufficiencyValidator


def _config(**overrides: object) -> BaseConfig:
    return BaseConfig(llm_api_key="test-key", **overrides)  # type: ignore[arg-type]


class TestDefault:
    def test_validation_is_off_by_default(self) -> None:
        """Asserted structurally so the default cannot drift unnoticed."""
        field = BaseConfig.model_fields["faithfulness_validation_enabled"]
        assert field.default is False
        assert _config().faithfulness_validation_enabled is False

    def test_it_can_be_enabled(self) -> None:
        assert _config(faithfulness_validation_enabled=True).faithfulness_validation_enabled


class TestInjection:
    def test_validator_not_constructed_when_disabled(self) -> None:
        """Disabled is a structural absence, not a branch inside the check.

        Mirrors main.py's injection rule: with the flag off, the plugins
        receive `None` and no validation code is reachable at all.
        """
        config = _config()
        injected = (
            ContextSufficiencyValidator()
            if config.faithfulness_validation_enabled
            else None
        )
        assert injected is None

    def test_validator_constructed_when_enabled(self) -> None:
        config = _config(faithfulness_validation_enabled=True)
        injected = (
            ContextSufficiencyValidator()
            if config.faithfulness_validation_enabled
            else None
        )
        assert isinstance(injected, ContextSufficiencyValidator)
