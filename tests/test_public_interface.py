"""AT-design: публичный интерфейс существующих MCP-инструментов не меняется (NFR-1).

Покрывает NFR-1 (единственное AC): снимок имён и обязательных параметров пяти
существующих MCP-инструментов до/после эпика.

Это регрессионный снимок, не проверка новой функциональности — в отличие от остальных
файлов этого пакета он ЗЕЛЁНЫЙ уже сегодня (все пять инструментов существуют с этими
именами/параметрами в server.py) и должен ОСТАВАТЬСЯ зелёным после переезда в
tools_recordings.py (client-modules-spec.md §1) и после добавления новых инструментов.
Работает как guard: если Dev в процессе рефакторинга случайно переименует инструмент
или сделает опциональный параметр обязательным, этот тест покраснеет.

Ожидаемые значения ниже сняты прогоном на текущем сервере (снимок "before" эпика,
2026-08-13); .parameters — JSON-схема входа инструмента (fastmcp FunctionTool.parameters).
"""

from __future__ import annotations

EXPECTED_TOOLS = {
    "ktalk_list_recordings": set(),
    "ktalk_get_recording": {"recording_key"},
    "ktalk_get_transcript": {"recording_key"},
    "ktalk_get_summary": {"recording_key"},
    "ktalk_get_summary_by_type": {"recording_key", "summary_type"},
}


async def test_nfr1_five_existing_tool_names_and_required_params_unchanged():
    """AC NFR-1: имена и обязательные параметры пяти существующих инструментов не
    меняются; новые параметры допускаются только опциональными с дефолтами."""
    from ktalk_mcp.server import mcp

    tools = await mcp.list_tools()
    tools_by_name = {t.name: t for t in tools}

    for name, required in EXPECTED_TOOLS.items():
        assert name in tools_by_name, f"MCP-инструмент {name} отсутствует"
        schema = tools_by_name[name].parameters
        actual_required = set(schema.get("required", []))
        assert actual_required == required, (
            f"{name}: обязательные параметры изменились "
            f"(было {required}, стало {actual_required})"
        )
