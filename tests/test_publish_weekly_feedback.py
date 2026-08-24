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

    def test_confirmed_preview_snapshot_freezes_teacher_text_not_old_ai_draft(self):
        fixture = json.loads((ROOT / "tests/fixtures/student_ops/week_v1.json").read_text(encoding="utf-8"))
        result = run_workflow("all", fixture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "all_result.json"
            result_path.write_text(json.dumps({"result": result}, ensure_ascii=False), encoding="utf-8")
            payload = result["weekly_payload"]["payload"]
            payload["反馈状态"] = "已确认"
            drafts = dict(result["weekly_drafts"]["payload"]["drafts"])
            drafts["智育师修改稿"] = "老师确认后的总体说明"
            preview = root / "confirmed_preview.json"
            preview.write_text(json.dumps({"payload": payload, "drafts": drafts}, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run([
                sys.executable, str(ROOT / "pipeline/publish_weekly_feedback.py"),
                "--result", str(result_path), "--drafts-file", str(preview), "--approved-at", "2026-09-05 18:00", "--version", "v1",
                "--storage-dir", str(root / "public"), "--public-base-url", "https://feedback.example", "--token", "teachertext",
            ], check=True, capture_output=True, text=True)
            output = json.loads(completed.stdout)
            snapshot = json.loads(Path(output["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(snapshot["drafts"]["智育师修改稿"], "老师确认后的总体说明")
            self.assertIn("老师确认后的总体说明", Path(output["html"]).read_text(encoding="utf-8"))

    def test_unconfirmed_preview_snapshot_cannot_publish(self):
        fixture = json.loads((ROOT / "tests/fixtures/student_ops/week_v1.json").read_text(encoding="utf-8"))
        result = run_workflow("all", fixture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "all_result.json"
            result_path.write_text(json.dumps({"result": result}, ensure_ascii=False), encoding="utf-8")
            preview = root / "draft_preview.json"
            preview.write_text(json.dumps({"payload": result["weekly_payload"]["payload"], "drafts": result["weekly_drafts"]["payload"]["drafts"]}, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run([
                sys.executable, str(ROOT / "pipeline/publish_weekly_feedback.py"),
                "--result", str(result_path), "--drafts-file", str(preview), "--approved-at", "2026-09-05 18:00", "--version", "v1",
                "--storage-dir", str(root / "public"), "--public-base-url", "https://feedback.example", "--token", "notconfirmed",
            ], check=False, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("preview_drafts_not_confirmed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
