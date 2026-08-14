from __future__ import annotations

import inspect
import logging
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

logger = logging.getLogger(__name__)


def _port_of(annotation: Any) -> Any:
    """Unwrap ``Port | None`` to ``Port``; pass anything else through.

    An optional port is still a request for that port — the ``None`` only says
    the plugin can run without it. Looking the union itself up in the bindings
    always misses, so before this the only way to supply an optional port was
    to bypass the container, which is how ``reranker`` came to be wired by
    hand in ``main.py``.

    Unions of two or more real types are left alone: there is no single port
    to resolve, so the caller gets the same miss it did before.
    """
    if get_origin(annotation) not in (Union, types.UnionType):
        return annotation
    non_none = [a for a in get_args(annotation) if a is not type(None)]
    return non_none[0] if len(non_none) == 1 else annotation


def _describe(annotation: Any) -> str:
    """Name an annotation for an error message.

    ``types.UnionType`` has no ``__name__``, so the unresolvable-port error
    used to die with an ``AttributeError`` that hid the real problem.
    """
    return getattr(annotation, "__name__", None) or str(annotation)


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
        construction of the plugin. Parameters with default values are
        skipped if no adapter is registered for their type.
        """
        hints = get_type_hints(plugin_class.__init__)
        sig = inspect.signature(plugin_class.__init__)
        resolved: dict[str, Any] = {}
        for param_name, param_type in hints.items():
            if param_name in ("self", "return"):
                continue
            # `Port | None` is a request for Port; the None only marks it
            # optional. Resolve the underlying port rather than the union.
            adapter = self._bindings.get(_port_of(param_type))
            if adapter is not None:
                resolved[param_name] = adapter
            elif sig.parameters[param_name].default is inspect.Parameter.empty:
                raise ContainerError(
                    f"Plugin {getattr(plugin_class, 'name', plugin_class.__name__)} "
                    f"requires port {_describe(param_type)} but no adapter "
                    f"is registered"
                )
        return resolved
