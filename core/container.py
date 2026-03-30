from __future__ import annotations

import logging
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)


class ContainerError(Exception):
    """Raised when a port cannot be resolved from the container."""


class Container:
    """Lightweight IoC container mapping port protocols to adapter instances."""

    def __init__(self) -> None:
        self._bindings: dict[type, Any] = {}

    def register(self, port: type, adapter: Any) -> None:
        """Register an adapter instance for a port protocol."""
        self._bindings[port] = adapter
        logger.info(
            "Registered adapter %s for port %s",
            type(adapter).__name__,
            port.__name__,
        )

    def resolve(self, port: type) -> Any:
        """Resolve an adapter for a given port protocol."""
        adapter = self._bindings.get(port)
        if adapter is None:
            raise ContainerError(f"No adapter registered for port {port.__name__}")
        return adapter

    def resolve_for_plugin(self, plugin_class: type) -> dict[str, Any]:
        """Resolve only the ports declared in the plugin's ``__init__`` parameters.

        Introspects type-hints on *plugin_class.__init__* and returns a
        ``dict[param_name, adapter_instance]`` suitable for ``**kwargs``
        construction of the plugin.
        """
        hints = get_type_hints(plugin_class.__init__)
        resolved: dict[str, Any] = {}
        for param_name, param_type in hints.items():
            if param_name in ("self", "return"):
                continue
            adapter = self._bindings.get(param_type)
            if adapter is None:
                raise ContainerError(
                    f"Plugin {getattr(plugin_class, 'name', plugin_class.__name__)} "
                    f"requires port {param_type.__name__} but no adapter is registered"
                )
            resolved[param_name] = adapter
        return resolved
