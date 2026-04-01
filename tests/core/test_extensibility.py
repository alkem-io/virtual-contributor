"""Integration test: echo plugin auto-discovery without core code changes (SC-006)."""

from __future__ import annotations



from core.events.response import Response
from core.registry import PluginRegistry
from core.router import Router
from tests.conftest import make_input


class TestExtensibility:
    def test_echo_plugin_discovery_by_registry(self):
        """Echo plugin is registered without modifying core code."""
        from tests.plugins.echo_plugin.plugin import EchoPlugin

        registry = PluginRegistry()
        registry.register(EchoPlugin)
        assert registry.get("echo") is EchoPlugin
        assert "echo" in registry.list_plugins()

    async def test_echo_plugin_routing(self):
        """Router dispatches to echo plugin without core changes."""
        from tests.plugins.echo_plugin.plugin import EchoPlugin

        router = Router(plugin_type="echo")
        body = {"input": make_input(message="Hello Echo").model_dump()}
        event = router.parse_event(body)

        plugin = EchoPlugin()
        response = await plugin.handle(event)

        assert isinstance(response, Response)
        assert response.result == "Hello Echo"

    async def test_echo_plugin_full_flow(self):
        """Full flow: register, route, handle — zero core modifications."""
        from tests.plugins.echo_plugin.plugin import EchoPlugin

        # Register
        registry = PluginRegistry()
        registry.register(EchoPlugin)

        # Get plugin class
        plugin_class = registry.get("echo")
        assert plugin_class is not None

        # Route
        router = Router(plugin_type="echo")
        body = {"input": make_input(message="Extensibility test").model_dump()}
        event = router.parse_event(body)

        # Handle
        plugin = plugin_class()
        await plugin.startup()
        response = await plugin.handle(event)
        await plugin.shutdown()

        assert response.result == "Extensibility test"

        # Build envelope
        envelope = router.build_response_envelope(response, event)
        assert envelope["response"]["result"] == "Extensibility test"
        assert "original" in envelope
