import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops import run_workflow


class PublicationFreezeTests(unittest.TestCase):
    def test_publisher_freezes_same_html_pdf_and_manifest(self):
        fixture = json.loads((ROOT / "tests/fixtures/student_ops/week_v1.json").read_text(encoding="utf-8"))
        result = run_workflow("all", fixture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "all_result.json"
            result_path.write_text(json.dumps({"result": result}, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run([
                sys.executable, str(ROOT / "pipeline/publish_weekly_feedback.py"),
                "--result", str(result_path), "--approved-at", "2026-09-05 18:00", "--version", "v1",
                "--storage-dir", str(root / "public"), "--public-base-url", "https://feedback.example", "--token", "testtoken",
            ], check=True, capture_output=True, text=True)
            output = json.loads(completed.stdout)
            manifest_path = Path(output["manifest"])
            snapshot = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["manifest"]["publication_fields"]["反馈状态"], ["已发布"])
            self.assertTrue(Path(output["html"]).read_text(encoding="utf-8").startswith("<!doctype html>"))
            self.assertTrue(Path(output["pdf"]).read_bytes().startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
