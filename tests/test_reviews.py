from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.radarlib import load_reviews, save_reviews


class ReviewNormalizationTests(unittest.TestCase):
    def test_props_metadata_survives_load_and_save(self) -> None:
        source = {
            "62494": {
                "status": "committed",
                "reason": "Landed",
                "notes": "Verified",
                "updated_at": "2026-06-19T22:21:31.662Z",
                "received_props": True,
                "props_recorded_at": "2026-06-19T22:21:31.662Z",
                "changeset": "62494",
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(source), encoding="utf-8")

            reviews = load_reviews(path)
            save_reviews(reviews, path)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(saved["62494"]["received_props"])
        self.assertEqual(saved["62494"]["props_recorded_at"], source["62494"]["props_recorded_at"])
        self.assertEqual(saved["62494"]["changeset"], "62494")


if __name__ == "__main__":
    unittest.main()
