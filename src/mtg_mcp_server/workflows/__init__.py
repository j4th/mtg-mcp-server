"""Workflow layer — composed tools calling multiple backend services."""

from typing import Any, NamedTuple


class WorkflowResult(NamedTuple):
    """Result from a workflow function: markdown for display + structured data for machines."""

    markdown: str
    data: dict[str, Any]
