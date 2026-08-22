"""Static HTML preview and Chromium PDF rendering for confirmed local snapshots."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .report_template import render_weekly_report


class PDFRenderError(RuntimeError):
    pass


def find_chromium() -> str | None:
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if path := shutil.which(name):
            return path
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(mac) if mac.exists() else None


def render_pdf(html_path: Path, pdf_path: Path, binary: str | None = None) -> None:
    chrome = binary or find_chromium()
    if not chrome:
        raise PDFRenderError("chromium_not_available")
    try:
        subprocess.run([
            chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri(),
        ], check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise PDFRenderError("pdf_render_failed") from None
    if not pdf_path.exists() or not pdf_path.read_bytes().startswith(b"%PDF-"):
        raise PDFRenderError("pdf_render_failed")


def render_weekly_html(payload: dict[str, Any], drafts: dict[str, Any]) -> str:
    return render_weekly_report(payload, drafts)
