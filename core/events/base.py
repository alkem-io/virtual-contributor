"""Base event model with camelCase wire-format defaults."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class EventBase(BaseModel):
    """Base class for all event models.

    Provides camelCase alias serialization by default and enum-value
    coercion so that wire payloads stay compatible with the existing
    RabbitMQ / REST contracts.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("by_alias", True)
        return super().model_dump_json(**kwargs)
