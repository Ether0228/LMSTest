import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from sync_weekly_feedback_base import load_result


class NonLiveArtifactGuardTests(unittest.TestCase):
    def test_metadata_is_preserved_when_loading_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps({"run_metadata": {"ai_mode": "fixture"}, "result": {"weekly_payload": {"payload": {}}, "weekly_drafts": {}}}), encoding="utf-8")
            _, _, metadata = load_result(path)
            self.assertEqual(metadata["ai_mode"], "fixture")

    def test_publish_rejects_nonlive_artifact_before_writing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "result.json"
            path.write_text(json.dumps({"run_metadata": {"ai_mode": "fixture"}, "result": {}}), encoding="utf-8")
            command = [sys.executable, str(ROOT / "pipeline/publish_weekly_feedback.py"), "--result", str(path), "--approved-at", "2026-09-05 18:00", "--version", "v1", "--storage-dir", str(root / "public"), "--public-base-url", "https://feedback.example"]
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("non_live_ai_artifact", completed.stderr)


if __name__ == "__main__":
    unittest.main()
