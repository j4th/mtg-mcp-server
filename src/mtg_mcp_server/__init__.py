"""MTG MCP Server — Magic: The Gathering data for AI assistants."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("mtg-mcp-server")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
