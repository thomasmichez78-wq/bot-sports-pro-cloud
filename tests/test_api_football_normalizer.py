from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from bot_sports_pro.core.enums import Sport
from bot_sports_pro.normalizers.api_football import normalize_fixtures


class ApiFootballNormalizerTests(unittest.TestCase):
    def test_normalizes_recorded_fixture(self) -> None:
        fixture_file = Path(__file__).parent / "fixtures" / "api_football_fixtures.json"
        payload = json.loads(fixture_file.read_text(encoding="utf-8"))

        events, rejected = normalize_fixtures(payload, datetime.now(UTC))

        self.assertEqual(rejected, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "api-football:123456")
        self.assertEqual(events[0].sport, Sport.FOOTBALL)
        self.assertEqual(events[0].home_name, "Équipe A")
        self.assertEqual(events[0].metadata["provider_league_id"], 2)
        self.assertEqual(events[0].metadata["home_team_id"], 10)
        self.assertEqual(events[0].metadata["away_team_id"], 20)

    def test_rejects_incomplete_item_without_stopping_batch(self) -> None:
        events, rejected = normalize_fixtures({"response": [{}]}, datetime.now(UTC))
        self.assertEqual(events, [])
        self.assertEqual(len(rejected), 1)


if __name__ == "__main__":
    unittest.main()
