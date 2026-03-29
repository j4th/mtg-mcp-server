"""Workflow layer — composed tools calling multiple backend services."""

from collections.abc import Mapping
from typing import NamedTuple


class WorkflowResult(NamedTuple):
    """Result from a workflow function: markdown for display + structured data for machines."""

    markdown: str
    data: Mapping[str, object]
