# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it through
[GitHub Security Advisories](https://github.com/j4th/mtg-mcp-server/security/advisories/new).

**Do not open a public issue for security vulnerabilities.**

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours of report submission
- **Assessment**: Within 1 week
- **Fix**: Depends on severity; critical issues prioritized

## Scope

### In Scope

- Dependency vulnerabilities (outdated packages with known CVEs)
- Environment variable exposure (e.g., `.env` files committed to version control)
- Input validation issues in tool parameters
- Logging of sensitive data to stderr

### Out of Scope

All upstream APIs used by this server are public and require no authentication tokens:

- Scryfall (public API, requires only User-Agent header)
- Commander Spellbook (public API)
- 17Lands (public data endpoints)
- EDHREC (public JSON endpoints)
- MTGJSON (public file downloads)

There are no API keys, OAuth tokens, or credentials stored or transmitted by this server.

## Dependency Auditing

This project uses `pip-audit` to check for known vulnerabilities in dependencies.
Run it locally (requires dev dependencies, installed by default with `uv sync`):

```bash
uv run pip-audit
```
