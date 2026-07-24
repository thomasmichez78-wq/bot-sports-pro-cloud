from __future__ import annotations

import unittest

from bot_sports_pro.services.football_sports_data import (
    normalize_history,
    normalize_standings,
)


class FootballSportsDataTests(unittest.TestCase):
    def test_normalizes_only_completed_history(self) -> None:
        payload = {
            "response": [
                {
                    "fixture": {
                        "id": 1,
                        "date": "2026-07-20T18:00:00+02:00",
                        "status": {"short": "FT"},
                    },
                    "league": {"id": 39, "season": 2026, "round": "Round 1"},
                    "teams": {
                        "home": {"id": 10, "name": "A"},
                        "away": {"id": 20, "name": "B"},
                    },
                    "goals": {"home": 2, "away": 1},
                },
                {
                    "fixture": {
                        "id": 2,
                        "date": "2026-07-30T18:00:00+02:00",
                        "status": {"short": "NS"},
                    },
                    "league": {"id": 39, "season": 2026, "round": "Round 2"},
                    "teams": {
                        "home": {"id": 10, "name": "A"},
                        "away": {"id": 30, "name": "C"},
                    },
                    "goals": {"home": None, "away": None},
                },
            ]
        }

        history = normalize_history(payload)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["home_team_id"], 10)
        self.assertEqual(history[0]["home_goals"], 2)

    def test_flattens_standing_groups(self) -> None:
        payload = {
            "response": [
                {
                    "league": {
                        "id": 39,
                        "season": 2026,
                        "standings": [
                            [
                                {
                                    "rank": 1,
                                    "team": {"id": 10, "name": "A"},
                                    "points": 12,
                                    "goalsDiff": 8,
                                    "group": "League",
                                    "form": "WWDWW",
                                    "all": {"played": 5},
                                    "home": {"played": 3},
                                    "away": {"played": 2},
                                    "update": "2026-07-20T00:00:00Z",
                                }
                            ]
                        ],
                    }
                }
            ]
        }

        standings = normalize_standings(payload)

        self.assertEqual(len(standings), 1)
        self.assertEqual(standings[0]["team_id"], 10)
        self.assertEqual(standings[0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
