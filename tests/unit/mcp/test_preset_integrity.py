from cygnusx.infrastructure.mcp.presets import PRESET_SERVERS, _build_cygnusx_tools_preset


def test_cygnusx_tools_preset_has_unique_tool_names() -> None:
    preset = _build_cygnusx_tools_preset()
    names = [tool["name"] for tool in preset["tools"]]

    assert len(names) == len(set(names))


def test_all_builtin_presets_have_unique_tools_and_handlers() -> None:
    for preset in [*PRESET_SERVERS, _build_cygnusx_tools_preset()]:
        names = [tool["name"] for tool in preset["tools"]]

        assert len(names) == len(set(names)), preset["name"]
        assert set(names) <= set(preset["handlers"]), preset["name"]
