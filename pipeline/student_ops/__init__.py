"""Fixture-first student learning operations workflows.

This package deliberately has no Feishu or Schoology writes.  Adapters return
dry-run write plans until the business owners approve a production adapter.
"""

from .engine import WORKFLOWS, run_workflow

__all__ = ["WORKFLOWS", "run_workflow"]
