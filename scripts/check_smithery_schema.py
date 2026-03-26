#!/usr/bin/env python3
"""Verify smithery.yaml configSchema properties match SmitheryConfig Pydantic model.

Catches drift between the YAML manifest (read by Smithery's deployment pipeline)
and the Pydantic model (used by the Python SDK at runtime). CI runs this as a
separate build step (see .github/workflows/ci.yml).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from mtg_mcp_server.smithery import SmitheryConfig

yaml_path = Path("smithery.yaml")
if not yaml_path.exists():
    print(f"::error::smithery.yaml not found in {Path.cwd()}", file=sys.stderr)
    sys.exit(1)

yaml_data = yaml.safe_load(yaml_path.read_text())
try:
    yaml_schema = yaml_data["startCommand"]["configSchema"]
except (KeyError, TypeError) as exc:
    print(
        f"::error::smithery.yaml missing expected key 'startCommand.configSchema': {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

yaml_props = set(yaml_schema.get("properties", {}).keys())

pydantic_schema = SmitheryConfig.model_json_schema()
pydantic_props = set(pydantic_schema.get("properties", {}).keys())

errors: list[str] = []

only_in_yaml = yaml_props - pydantic_props
only_in_pydantic = pydantic_props - yaml_props

if only_in_yaml:
    errors.append(f"In smithery.yaml but not SmitheryConfig: {', '.join(sorted(only_in_yaml))}")
if only_in_pydantic:
    errors.append(f"In SmitheryConfig but not smithery.yaml: {', '.join(sorted(only_in_pydantic))}")

if errors:
    print("::error::smithery.yaml ↔ SmitheryConfig property mismatch:", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)

print(f"OK: {len(yaml_props)} properties in sync between smithery.yaml and SmitheryConfig")
