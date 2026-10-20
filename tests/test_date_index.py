import json
import tempfile
import unittest
from pathlib import Path

from core.date_index import build_date_index, file_date_record


class DateIndexTests(unittest.TestCase):
    def test_file_date_record_prefers_filename_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dance_recital_2026-09-09.txt"
            path.write_text("date proof", encoding="utf-8")

            record = file_date_record(path)

            self.assertEqual(record["filename_date"], "2026-09-09")
            self.assertEqual(record["chosen_date"], "2026-09-09")
            self.assertEqual(record["chosen_source"], "filename")

    def test_build_date_index_saves_reviewable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            docs = Path(tmp) / "docs"
            root.mkdir()
            (root / "family.png").write_bytes(b"not really a png")

            result = build_date_index(str(root), str(docs), recursive=False, limit=10)
            saved = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))

            self.assertEqual(result["mutation"], "none")
            self.assertEqual(saved["record_count"], 1)
            self.assertEqual(saved["records"][0]["name"], "family.png")


if __name__ == "__main__":
    unittest.main()
