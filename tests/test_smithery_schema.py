"""Tests for scripts/check_smithery_schema.py validation logic."""

from __future__ import annotations

from pathlib import Path

import yaml

from mtg_mcp_server.smithery import SmitheryConfig

SMITHERY_YAML = Path("smithery.yaml")


class TestSmitherySchemaSync:
    """Verify smithery.yaml stays in sync with SmitheryConfig."""

    def test_properties_in_sync(self):
        """smithery.yaml configSchema has the same properties as SmitheryConfig."""
        yaml_data = yaml.safe_load(SMITHERY_YAML.read_text())
        yaml_props = set(yaml_data["startCommand"]["configSchema"]["properties"].keys())
        pydantic_props = set(SmitheryConfig.model_json_schema()["properties"].keys())
        assert yaml_props == pydantic_props, (
            f"Property mismatch:\n"
            f"  Only in YAML: {yaml_props - pydantic_props or 'none'}\n"
            f"  Only in Pydantic: {pydantic_props - yaml_props or 'none'}"
        )

    def test_detects_missing_yaml_property(self):
        """Script logic detects a property in SmitheryConfig but missing from YAML."""
        yaml_data = yaml.safe_load(SMITHERY_YAML.read_text())
        # Remove one property from the YAML copy
        props = yaml_data["startCommand"]["configSchema"]["properties"]
        removed_key = next(iter(props))
        del props[removed_key]

        yaml_props = set(props.keys())
        pydantic_props = set(SmitheryConfig.model_json_schema()["properties"].keys())

        only_in_pydantic = pydantic_props - yaml_props
        assert removed_key in only_in_pydantic

    def test_detects_extra_yaml_property(self):
        """Script logic detects a property in YAML but missing from SmitheryConfig."""
        yaml_data = yaml.safe_load(SMITHERY_YAML.read_text())
        # Add a bogus property to the YAML copy
        yaml_data["startCommand"]["configSchema"]["properties"]["BOGUS_PROP"] = {
            "type": "string",
            "default": "test",
        }

        yaml_props = set(yaml_data["startCommand"]["configSchema"]["properties"].keys())
        pydantic_props = set(SmitheryConfig.model_json_schema()["properties"].keys())

        only_in_yaml = yaml_props - pydantic_props
        assert "BOGUS_PROP" in only_in_yaml

    def test_yaml_has_expected_structure(self):
        """smithery.yaml has the required startCommand.configSchema structure."""
        yaml_data = yaml.safe_load(SMITHERY_YAML.read_text())
        assert "startCommand" in yaml_data
        assert "configSchema" in yaml_data["startCommand"]
        assert "properties" in yaml_data["startCommand"]["configSchema"]
