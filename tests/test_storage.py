from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from bot_sports_pro.storage.json_store import JsonSnapshotStore


class JsonSnapshotStoreTests(unittest.TestCase):
    def test_saves_source_metadata_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonSnapshotStore(Path(directory))
            moment = datetime(2026, 7, 23, 18, 0, tzinfo=UTC)
            output = store.save("API Football", {"fixtures": [1, 2]}, moment)

            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["source"], "API Football")
            self.assertEqual(document["payload"]["fixtures"], [1, 2])
            self.assertIn("api_football", output.name)

    def test_rejects_naive_datetime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonSnapshotStore(Path(directory))
            with self.assertRaises(ValueError):
                store.save("source", {}, datetime(2026, 7, 23, 18, 0))


if __name__ == "__main__":
    unittest.main()
