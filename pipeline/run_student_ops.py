#!/usr/bin/env python3
"""Run fixture-first Student Learning Operations workflows without live writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from student_ops import WORKFLOWS, run_workflow
from student_ops.ai import AIAdapterError, FixtureAIAdapter, OpenAICompatibleAdapter
from student_ops.engine import write_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", choices=WORKFLOWS, default="all")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/student_ops"))
    parser.add_argument("--dry-run", action="store_true", default=True, help="required for V1; no external writes exist")
    parser.add_argument("--ai-mode", choices=("fixture", "live"), default="fixture")
    args = parser.parse_args()
    data = json.loads(args.fixture.read_text(encoding="utf-8"))
    try:
        adapter = FixtureAIAdapter() if args.ai_mode == "fixture" else OpenAICompatibleAdapter.from_environment()
    except AIAdapterError as error:
        # Configuration failure is explicit but never prints secret values.
        print(json.dumps({"workflow": args.workflow, "dry_run": args.dry_run, "ai_mode": args.ai_mode, "status": "ai_configuration_failed", "error": str(error)}, ensure_ascii=False))
        return 2
    result = run_workflow(args.workflow, data, ai_adapter=adapter)
    paths = write_artifacts(result, args.output_dir, args.workflow, args.dry_run, run_metadata={"ai_mode": args.ai_mode})
    # Do not emit fixture content: it can include student data in a real run.
    print(json.dumps({"workflow": args.workflow, "dry_run": args.dry_run, "ai_mode": args.ai_mode, "artifacts": [str(p) for p in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
