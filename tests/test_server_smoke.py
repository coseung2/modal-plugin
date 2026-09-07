def test_server_registers_expected_tools() -> None:
    from modal_plugin.server import mcp

    assert mcp.name == "modal-plugin"
