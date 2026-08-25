"""Fixture-first student learning operations workflows.

This package deliberately has no Feishu or Schoology writes.  Adapters return
dry-run write plans until the business owners approve a production adapter.
"""

from .engine import WORKFLOWS, run_workflow
from .weekly_feedback_base import build_publication_fields, build_weekly_feedback_fields

__all__ = ["WORKFLOWS", "run_workflow", "build_weekly_feedback_fields", "build_publication_fields"]
