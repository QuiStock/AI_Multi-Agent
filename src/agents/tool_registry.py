from langchain_core.tools import BaseTool

TOOL_REGISTRY: dict[str, BaseTool] = {}


def get_tool(tool_id: str) -> BaseTool:
    try:
        return TOOL_REGISTRY[tool_id]
    except KeyError as exc:
        raise ValueError(f"Tool not registered: {tool_id}") from exc
