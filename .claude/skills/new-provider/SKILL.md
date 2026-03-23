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
from mtg_mcp_server.services.base import DEFAULT_USER_AGENT, BaseClient, ServiceError

log = structlog.get_logger(service="<name>")

class <Name>Error(ServiceError): ...
class <Name>NotFoundError(<Name>Error): ...

class <Name>Client(BaseClient):
    """<Name> API client."""

    def __init__(
        self,
        base_url: str = "...",  # from Settings
        rate_limit_rps: float = ...,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit_rps=rate_limit_rps,
            user_agent=user_agent,
        )
```

### 2. Provider sub-server: `src/mtg_mcp_server/providers/<name>.py`

```python
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from fastmcp.exceptions import ToolError

from mtg_mcp_server.config import Settings
from mtg_mcp_server.providers import TOOL_ANNOTATIONS
from mtg_mcp_server.services.<name> import <Name>Client

_client: <Name>Client | None = None

@lifespan
async def <name>_lifespan(server: FastMCP):
    global _client
    settings = Settings()
    client = <Name>Client(base_url=settings.<name>_base_url)
    async with client:
        _client = client
        yield {}
    _client = None

<name>_mcp = FastMCP("<DisplayName>", lifespan=<name>_lifespan)

def _get_client() -> <Name>Client:
    if _client is None:
        raise RuntimeError("<Name>Client not initialized — server lifespan not running")
    return _client

# Tools go here — each uses:
#   annotations=TOOL_ANNOTATIONS
#   client = _get_client()
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
- Service clients via lifespan + module-level `_client`, never instantiate per call
- After scaffolding, remind the user to mount on the orchestrator in `server.py`
