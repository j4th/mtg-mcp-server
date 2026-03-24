# Contributing to MTG MCP Server

Thank you for your interest in contributing to the MTG MCP Server. This guide covers everything you need to get started.

## Prerequisites

- [mise](https://mise.jdx.dev) (manages Python, uv, ruff, ty)
- Python 3.12+
- Git

## Quick Start

```bash
git clone https://github.com/j4th/mtg-mcp-server.git
cd mtg-mcp-server
mise install       # Installs Python, uv, ruff, ty
mise run setup     # Creates venv, installs dependencies
```

Verify everything works:

```bash
mise run check     # Lint + typecheck + full test suite
```

## Development Workflow

This project follows test-driven development (TDD):

1. **Write a failing test** against a fixture or mock
2. **Implement the code** to make the test pass
3. **Iterate** with `mise run test:quick` (pytest-testmon -- only re-runs affected tests)
4. **Run the full gate** with `mise run check` before opening a PR

### Useful Commands

| Command              | Purpose                                      |
|----------------------|----------------------------------------------|
| `mise run test:quick`| Fast feedback -- only tests affected by edits |
| `mise run test`      | Full test suite with coverage                |
| `mise run check`     | Lint + typecheck + test (the quality gate)   |
| `mise run lint`      | ruff check + ruff format --check             |
| `mise run typecheck` | ty check                                     |
| `mise run fix`       | Auto-fix lint and format issues              |
| `mise run dev`       | MCP Inspector on :6274                       |
| `mise run serve`     | Run server via stdio transport                |

## Code Style

- **Linting and formatting**: ruff (replaces black, isort, flake8, pylint)
- **Type checking**: ty (Astral, 10-60x faster than mypy/pyright)
- **Logging**: structlog with bound context. All logging to stderr (stdout is MCP transport in stdio mode)
- **Modern typing**: use `list[str]` not `List[str]`, `str | None` not `Optional[str]`
- **No `Any` type**: use `Unknown` or proper types instead
- **Optional numeric fields**: use `is not None` checks, not truthiness -- `0` and `0.0` are valid values

## Testing

- **Services**: use [respx](https://github.com/lundberg/respx) to mock httpx. Never hit live APIs
- **Providers**: use `fastmcp.Client(transport=server)` for in-memory MCP testing
- **Workflows**: use `unittest.mock.AsyncMock` since workflows are pure functions
- **Fixtures**: captured JSON from real API responses, stored in `tests/fixtures/`
- **Coverage**: 80% minimum, enforced by CI

### Writing a Service Test

```python
# tests/services/test_example.py
import respx
from httpx import Response

@respx.mock
async def test_get_card(scryfall_client):
    respx.get("/cards/named").mock(
        return_value=Response(200, json=fixture_data)
    )
    card = await scryfall_client.get_card_by_name("Sol Ring")
    assert card.name == "Sol Ring"
```

### Writing a Workflow Test

```python
# tests/workflows/test_example.py
from unittest.mock import AsyncMock

async def test_commander_overview():
    scryfall = AsyncMock()
    scryfall.get_card_by_name.return_value = mock_card
    result = await commander_overview("Muldrotha", scryfall=scryfall)
    assert "Muldrotha" in result
```

## Project Structure

```
src/mtg_mcp_server/
  services/    -- Pure async API clients (no MCP awareness)
  providers/   -- FastMCP sub-servers (one per backend)
  workflows/   -- Composed tools calling multiple services
  server.py    -- Orchestrator that mounts everything
  types.py     -- Shared Pydantic models
  config.py    -- Settings from env vars (MTG_MCP_ prefix)
```

For full architecture details, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with tests
3. Run `mise run check` -- all checks must pass
4. Open a PR with:
   - A summary of what changed and why
   - A test plan describing how to verify the changes
   - Confirmation that `mise run check` passes and coverage is maintained

## Error Handling Conventions

- **Services** raise typed exceptions (e.g. `CardNotFoundError`, `ScryfallError`)
- **Providers** catch service exceptions and raise `ToolError` from `fastmcp.exceptions`
- **Workflows** handle partial failures -- if one backend is down, return what you can
- Always use `from exc` in except blocks (`raise ToolError(...) from exc`)

## Questions?

Open an issue on GitHub or check the existing documentation in `docs/`.
