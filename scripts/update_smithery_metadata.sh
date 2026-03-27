#!/usr/bin/env bash
# Update Smithery registry metadata for mtg-mcp-server.
# Reads description from pyproject.toml (single source of truth).
# Requires SMITHERY_API_KEY env var (get via: npx @smithery/cli auth token)
set -euo pipefail
: "${SMITHERY_API_KEY:?Set SMITHERY_API_KEY (run: npx @smithery/cli auth token)}"
SERVER="j4th/mtg-mcp-server"
API="https://api.smithery.ai/servers/${SERVER}"

# Build JSON payload from pyproject.toml (single source of truth for PyPI, MCP Registry, Smithery)
PAYLOAD=$(python3 -c "
import json, tomllib
proj = tomllib.load(open('pyproject.toml', 'rb'))['project']
print(json.dumps({
    'displayName': 'MTG MCP Server',
    'description': proj['description'],
    'homepage': proj['urls']['Homepage'],
}))
")

echo "Updating metadata for ${SERVER}..."
echo "  Payload: ${PAYLOAD}"

# PATCH display name, description, homepage
HTTP_CODE=$(curl -sS -o /tmp/smithery_resp.json -w "%{http_code}" -X PATCH "$API" \
  -H "Authorization: Bearer $SMITHERY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
if [[ "$HTTP_CODE" != 2* ]]; then
  echo "ERROR: PATCH metadata failed with HTTP $HTTP_CODE:" >&2
  cat /tmp/smithery_resp.json >&2
  echo >&2
  exit 1
fi
echo "  ✓ Metadata updated"

# Upload icon
[[ -f icon.svg ]] || { echo "ERROR: icon.svg not found in $(pwd)" >&2; exit 1; }
HTTP_CODE=$(curl -sS -o /tmp/smithery_resp.json -w "%{http_code}" -X PUT "$API/icon" \
  -H "Authorization: Bearer $SMITHERY_API_KEY" \
  -F "icon=@icon.svg;type=image/svg+xml")
if [[ "$HTTP_CODE" != 2* ]]; then
  echo "ERROR: PUT icon failed with HTTP $HTTP_CODE:" >&2
  cat /tmp/smithery_resp.json >&2
  echo >&2
  exit 1
fi
echo "  ✓ Icon uploaded"

echo "Done. Check https://smithery.ai/server/j4th/mtg-mcp-server"
