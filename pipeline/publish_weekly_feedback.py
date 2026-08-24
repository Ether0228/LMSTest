#!/usr/bin/env python3
"""Freeze a human-approved weekly feedback payload into versioned web/PDF files.

Files are placed under a high-entropy token directory so Nginx can serve them
read-only.  The companion Base update must use the emitted manifest; changing
the draft record later never changes these files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from student_ops.publishing import render_pdf, render_weekly_html
from student_ops.weekly_feedback_drafts import apply_feedback_record
from student_ops.weekly_feedback_base import build_publication_fields


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True, help="student_ops all_result.json")
    parser.add_argument("--approved-at", required=True, help="teacher-confirmed YYYY-MM-DD HH:mm")
    parser.add_argument("--version", required=True)
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--public-base-url", required=True, help="e.g. https://zy.queenscanada.com")
    parser.add_argument("--token", help="optional pre-generated publication token")
    parser.add_argument("--drafts-file", type=Path, help="teacher-preview snapshot or JSON text overrides; freezes these current drafts")
    args = parser.parse_args()
    raw = json.loads(args.result.read_text(encoding="utf-8"))
    result = raw.get("result", raw)
    payload = result["weekly_payload"]["payload"]
    drafts = result["weekly_drafts"]["payload"]["drafts"]
    if args.drafts_file:
        override = json.loads(args.drafts_file.read_text(encoding="utf-8"))
        if "payload" in override and "drafts" in override:
            payload, drafts = override["payload"], override["drafts"]
            if payload.get("反馈状态") not in ("已确认", "已发布"):
                raise SystemExit("preview_drafts_not_confirmed")
        else:
            payload, drafts = apply_feedback_record(payload, drafts, override)
    blocked = [name for name, status in payload.get("data_integrity", {}).items() if status == "blocked"]
    if blocked:
        raise SystemExit(f"critical_modules_blocked:{','.join(blocked)}")
    token = args.token or secrets.token_urlsafe(24)
    if not token.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("invalid_publication_token")
    directory = args.storage_dir / token
    if directory.exists():
        raise SystemExit("publication_token_already_exists")
    directory.mkdir(parents=True)
    html = render_weekly_html(payload, drafts)
    html_path = directory / "weekly_feedback.html"
    pdf_path = directory / "weekly_feedback.pdf"
    snapshot_path = directory / "weekly_feedback_snapshot.json"
    html_path.write_text(html, encoding="utf-8")
    render_pdf(html_path, pdf_path)
    base_url = args.public_base_url.rstrip("/") + f"/weekly-feedback/{token}"
    publication_fields = build_publication_fields(
        version=args.version, published_at=args.approved_at,
        html_url=base_url + "/weekly_feedback.html", pdf_url=base_url + "/weekly_feedback.pdf",
    )
    manifest = {
        "反馈唯一键": payload["反馈唯一键"], "version": args.version, "approved_at": args.approved_at,
        "token": token, "payload_hash": stable_hash(payload), "drafts_hash": stable_hash(drafts),
        "publication_fields": publication_fields,
    }
    snapshot_path.write_text(json.dumps({"manifest": manifest, "payload": payload, "drafts": drafts}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(snapshot_path), "html": str(html_path), "pdf": str(pdf_path), "publication_fields": publication_fields}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
