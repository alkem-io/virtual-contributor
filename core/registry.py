from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)


class RegistryError(Exception):
    """Raised when plugin registration or discovery fails."""


class PluginRegistry:
    """Discovers and registers plugin classes by ``PLUGIN_TYPE``."""

    def __init__(self) -> None:
        self._plugins: dict[str, type] = {}

    def register(self, plugin_class: type) -> None:
        """Register a plugin class.

        The class must expose a ``name`` attribute that serves as the
        unique key inside the registry.
        """
        name = getattr(plugin_class, "name", None)
        if name is None:
            raise RegistryError(
                f"Plugin class {plugin_class.__name__} has no 'name' attribute"
            )
        self._plugins[name] = plugin_class
        logger.info("Registered plugin: %s", name)

    def get(self, name: str) -> type | None:
        """Get a registered plugin class by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        """List all registered plugin names."""
        return list(self._plugins.keys())

    def discover(self, plugin_type: str) -> type:
        """Import and register the plugin for the given *plugin_type*.

        Convention: ``plugins/{plugin_type}/plugin.py`` must contain a class
        with both ``name`` and ``event_type`` attributes.  Hyphens in
        *plugin_type* are replaced with underscores to form a valid Python
        module path.
        """
        module_name = plugin_type.replace("-", "_")
        module_path = f"plugins.{module_name}.plugin"
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise RegistryError(
                f"Cannot import plugin module '{module_path}': {exc}"
            ) from exc

        # Find the plugin class in the module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and hasattr(attr, "name")
                and hasattr(attr, "event_type")
                and attr.__module__ == module.__name__
            ):
                self.register(attr)
                return attr

        raise RegistryError(f"No plugin class found in '{module_path}'")
