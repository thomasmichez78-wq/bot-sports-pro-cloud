from __future__ import annotations

import unittest
from collections import Counter

from bot_sports_pro.services.football_live_analysis import (
    assess_fixture_readiness,
)


def event(
    home_team_id: int | None = 10,
    away_team_id: int | None = 20,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "provider_fixture_id": "500",
        "provider_league_id": 71,
        "status": "NS",
    }
    if home_team_id is not None:
        metadata["home_team_id"] = home_team_id
    if away_team_id is not None:
        metadata["away_team_id"] = away_team_id
    return {
        "event_id": "api-football:500",
        "starts_at": "2026-07-25T18:00:00+02:00",
        "competition": "Serie A",
        "home_name": "A",
        "away_name": "B",
        "metadata": metadata,
    }


class FootballLiveAnalysisTests(unittest.TestCase):
    def test_fixture_is_ready_only_after_team_and_league_thresholds(self) -> None:
        team_matches = Counter({(71, 10): 5, (71, 20): 5})
        league_matches = Counter({71: 30})

        readiness = assess_fixture_readiness(
            event(),
            team_matches,
            league_matches,
            min_team_matches=5,
            min_league_matches=30,
        )

        self.assertEqual(readiness.reasons, ())
        self.assertEqual(readiness.home_history, 5)
        self.assertEqual(readiness.league_history, 30)

    def test_fixture_lists_every_missing_history_condition(self) -> None:
        readiness = assess_fixture_readiness(
            event(),
            Counter({(71, 10): 4, (71, 20): 2}),
            Counter({71: 12}),
            min_team_matches=5,
            min_league_matches=30,
        )

        self.assertEqual(len(readiness.reasons), 3)
        self.assertIn("league_history_12_below_30", readiness.reasons)
        self.assertIn("home_history_4_below_5", readiness.reasons)
        self.assertIn("away_history_2_below_5", readiness.reasons)

    def test_missing_team_identifier_is_technically_invalid(self) -> None:
        readiness = assess_fixture_readiness(
            event(home_team_id=None),
            Counter(),
            Counter(),
            min_team_matches=5,
            min_league_matches=30,
        )

        self.assertIsNone(readiness.fixture_id)
        self.assertEqual(
            readiness.reasons,
            ("missing_team_or_league_identifiers",),
        )


if __name__ == "__main__":
    unittest.main()
