"""MTG MCP provider sub-servers."""

from mcp.types import ToolAnnotations

TOOL_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)

# Tag sets for tool categorization
TAGS_LOOKUP = {"lookup", "stable"}
TAGS_SEARCH = {"search", "stable"}
TAGS_COMMANDER = {"commander", "analysis", "stable"}
TAGS_DRAFT = {"draft", "analysis", "stable"}
TAGS_COMBO = {"combo", "stable"}
TAGS_PRICING = {"pricing", "stable"}
TAGS_BETA = {"beta"}
