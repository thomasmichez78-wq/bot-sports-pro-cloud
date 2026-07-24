from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.services.football_live_history import (
    _load_competitions,
    build_live_coverage,
    merge_live_history,
    resolve_live_target_date,
)


def fixture(
    fixture_id: int,
    league_id: int,
    starts_at: str,
    home_id: int,
    away_id: int,
    home_goals: int = 1,
    away_goals: int = 0,
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "starts_at": starts_at,
        "status": "FT",
        "league_id": league_id,
        "season": 2026,
        "round": "Round",
        "home_team_id": home_id,
        "home_team": f"Équipe {home_id}",
        "away_team_id": away_id,
        "away_team": f"Équipe {away_id}",
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


class FootballLiveHistoryTests(unittest.TestCase):
    def test_cloud_copy_reads_competitions_from_live_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = AppSettings(
                root_dir=root,
                environment="cloud",
                timezone="Europe/Paris",
                api_football_key="test",
                odds_api_key=None,
                football_data_key=None,
                telegram_bot_token=None,
                telegram_chat_id=None,
            )
            settings.ensure_directories()
            live_file = settings.processed_dir / "football_live_history.json"
            live_file.write_text(
                json.dumps(
                    {
                        "purpose": "prospective_live_model_history",
                        "competitions": [
                            {"league_id": 71, "name": "Serie A"},
                            {"league_id": 72, "name": "Serie B"},
                        ],
                        "history": [],
                    }
                ),
                encoding="utf-8",
            )

            competitions = _load_competitions(settings)

            self.assertEqual(
                competitions,
                [
                    {"league_id": 71, "name": "Serie A"},
                    {"league_id": 72, "name": "Serie B"},
                ],
            )

    def test_only_yesterday_is_allowed_after_six(self) -> None:
        now = datetime(2026, 7, 24, 6, 15, tzinfo=ZoneInfo("Europe/Paris"))

        self.assertEqual(resolve_live_target_date(None, now), date(2026, 7, 23))
        with self.assertRaises(ValueError):
            resolve_live_target_date(date(2026, 7, 22), now)

    def test_refuses_collection_too_early(self) -> None:
        now = datetime(2026, 7, 24, 5, 59, tzinfo=ZoneInfo("Europe/Paris"))

        with self.assertRaises(ValueError):
            resolve_live_target_date(None, now)

    def test_merge_replaces_existing_fixture_without_duplicate(self) -> None:
        original = fixture(
            1,
            71,
            "2026-07-23T18:00:00+02:00",
            10,
            20,
            1,
            0,
        )
        corrected = fixture(
            1,
            71,
            "2026-07-23T18:00:00+02:00",
            10,
            20,
            2,
            0,
        )

        merged = merge_live_history([original], [corrected])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["home_goals"], 2)

    def test_coverage_counts_teams_with_five_matches(self) -> None:
        history = [
            fixture(
                index,
                71,
                f"2026-07-{index:02d}T18:00:00+02:00",
                10,
                20,
            )
            for index in range(1, 6)
        ]

        coverage = build_live_coverage(
            history,
            [{"league_id": 71, "name": "Serie A"}],
        )

        self.assertEqual(coverage[0].matches, 5)
        self.assertEqual(coverage[0].observed_teams, 2)
        self.assertEqual(coverage[0].teams_ready, 2)


if __name__ == "__main__":
    unittest.main()
