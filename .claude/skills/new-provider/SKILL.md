---
name: new-provider
description: Scaffold a new backend provider following project patterns (service + provider + tests)
disable-model-invocation: true
---

# New Provider

Scaffold a new backend provider with all required files following project conventions.

## Usage

`/new-provider <name>`

Examples:
- `/new-provider scryfall`
- `/new-provider spellbook`
- `/new-provider seventeen_lands`
- `/new-provider edhrec`

## What Gets Created

Given `/new-provider <name>`:

### 1. Service client: `src/mtg_mcp_server/services/<name>.py`

```python
import structlog
from mtg_mcp_server.services.base import BaseClient

log = structlog.get_logger(service="<name>")

class <Name>Error(Exception): ...
class <Name>NotFoundError(<Name>Error): ...

class <Name>Client(BaseClient):
    """<Name> API client."""

    def __init__(self) -> None:
        super().__init__(
            base_url="...",  # from Settings
            rate_limit=...,
            user_agent="mtg-mcp/0.1.0",
        )
```

### 2. Provider sub-server: `src/mtg_mcp_server/providers/<name>.py`

```python
from fastmcp import FastMCP, Context
from fastmcp.server.lifespan import lifespan
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from mtg_mcp_server.services.<name> import <Name>Client

@lifespan
async def <name>_lifespan(server):
    async with <Name>Client() as client:
        yield {"<name>_client": client}

<name>_mcp = FastMCP("<DisplayName>", lifespan=<name>_lifespan)

def get_client(ctx: Context) -> <Name>Client:
    return ctx.lifespan_context["<name>_client"]

# Tools go here — each uses:
#   annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
#   client: <Name>Client = Depends(get_client)
#   ToolError for error responses
```

### 3. Test files

- `tests/services/test_<name>.py` — Service layer tests with respx mocks
- `tests/providers/test_<name>_provider.py` — Provider tests using FastMCP test client
- `tests/fixtures/<name>/` — Directory for JSON fixtures (empty, user captures separately)

### 4. Pydantic models in `src/mtg_mcp_server/types.py`

Add response models for the service. Use `model_validate()`, not `parse_obj()`.

## Rules

- Follow TDD: write failing tests first, then implement
- Check `docs/SERVICE_CONTRACTS.md` for the service's API details
- Check `docs/TOOL_DESIGN.md` for the tools this provider should expose
- All tools are read-only and idempotent — annotate accordingly
- Use `ToolError` from `fastmcp.exceptions` for error responses
- Service clients via lifespan + `Depends()`, never instantiate per call
- After scaffolding, remind the user to mount on the orchestrator in `server.py`
