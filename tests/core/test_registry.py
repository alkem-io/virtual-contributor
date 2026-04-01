"""Unit tests for Plugin Registry."""

from __future__ import annotations

import pytest

from core.events.input import Input
from core.registry import PluginRegistry, RegistryError


class FakePlugin:
    name = "fake"
    event_type = Input

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def handle(self, event, **ports):
        pass


class NoNamePlugin:
    """Plugin class without a name attribute."""

    event_type = Input


class TestPluginRegistry:
    def test_register_and_get(self):
        registry = PluginRegistry()
        registry.register(FakePlugin)
        assert registry.get("fake") is FakePlugin

    def test_get_unknown_returns_none(self):
        registry = PluginRegistry()
        assert registry.get("nonexistent") is None

    def test_list_plugins(self):
        registry = PluginRegistry()
        registry.register(FakePlugin)
        assert "fake" in registry.list_plugins()

    def test_list_plugins_empty(self):
        registry = PluginRegistry()
        assert registry.list_plugins() == []

    def test_register_no_name_raises(self):
        registry = PluginRegistry()
        with pytest.raises(RegistryError, match="no 'name' attribute"):
            registry.register(NoNamePlugin)

    def test_discover_unknown_module_raises(self):
        registry = PluginRegistry()
        with pytest.raises(RegistryError, match="Cannot import"):
            registry.discover("nonexistent-plugin")

    def test_register_multiple_plugins(self):
        class AnotherPlugin:
            name = "another"
            event_type = Input

        registry = PluginRegistry()
        registry.register(FakePlugin)
        registry.register(AnotherPlugin)
        assert sorted(registry.list_plugins()) == ["another", "fake"]

    def test_discover_generic_plugin(self):
        """discover() imports and registers a real plugin from the plugins/ tree."""
        registry = PluginRegistry()
        plugin_class = registry.discover("generic")
        assert plugin_class.name == "generic"
        assert registry.get("generic") is plugin_class

    def test_discover_with_hyphen(self):
        """Hyphens in plugin_type are converted to underscores for import."""
        registry = PluginRegistry()
        plugin_class = registry.discover("openai-assistant")
        assert plugin_class.name == "openai-assistant"

    def test_discover_registers_automatically(self):
        """discover() adds the plugin to list_plugins()."""
        registry = PluginRegistry()
        registry.discover("expert")
        assert "expert" in registry.list_plugins()
