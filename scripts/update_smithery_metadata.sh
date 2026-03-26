#!/usr/bin/env bash
# Update Smithery registry metadata for mtg-mcp-server.
# Requires SMITHERY_API_KEY env var (get via: npx @smithery/cli auth token)
set -euo pipefail
: "${SMITHERY_API_KEY:?Set SMITHERY_API_KEY (run: npx @smithery/cli auth token)}"
SERVER="j4th/mtg-mcp-server"
API="https://api.smithery.ai/servers/${SERVER}"

echo "Updating metadata for ${SERVER}..."

# PATCH display name, description, homepage
curl -sf -X PATCH "$API" \
  -H "Authorization: Bearer $SMITHERY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "displayName": "MTG MCP Server",
    "description": "Magic: The Gathering data for AI — cards, combos, draft analytics, and Commander tools.",
    "homepage": "https://github.com/j4th/mtg-mcp-server"
  }'
echo "  ✓ Metadata updated"

# Upload icon
curl -sf -X PUT "$API/icon" \
  -H "Authorization: Bearer $SMITHERY_API_KEY" \
  -H "Content-Type: image/svg+xml" \
  --data-binary @icon.svg
echo "  ✓ Icon uploaded"

echo "Done. Check https://smithery.ai/server/j4th/mtg-mcp-server"
