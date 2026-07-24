from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from bot_sports_pro.collectors.the_odds_api import OddsApiResponse
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.services.football_value_evaluation import (
    _outcome_key,
    evaluate_live_football_value,
    evaluate_winamax_prices,
)


def settings(root: Path, odds_key: str | None = None) -> AppSettings:
    result = AppSettings(
        root_dir=root,
        environment="test",
        timezone="Europe/Paris",
        api_football_key=None,
        odds_api_key=odds_key,
        football_data_key=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    result.ensure_directories()
    return result


def write_analysis(root: Path, predictions: list[dict[str, object]]) -> None:
    target = (
        root
        / "storage"
        / "processed"
        / "football_live_analysis_2026-07-24_2026-07-25.json"
    )
    target.write_text(
        json.dumps(
            {
                "purpose": "live_probability_analysis_only",
                "predictions": predictions,
            }
        ),
        encoding="utf-8",
    )


def write_fixtures(root: Path) -> None:
    target = (
        root
        / "storage"
        / "processed"
        / "football_fixtures_2026-07-24_2026-07-25.json"
    )
    target.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "event_id": "api-football:500",
                        "starts_at": "2026-07-24T20:00:00+02:00",
                        "competition": "Test League",
                        "home_name": "Paris FC",
                        "away_name": "Lyon",
                        "metadata": {
                            "provider_fixture_id": 500,
                            "provider_league_id": 71,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class FailingFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, api_key: str) -> object:
        self.calls += 1
        raise AssertionError("Le fournisseur de cotes ne devait pas être contacté.")


class FakeCollector:
    def __init__(self, api_key: str) -> None:
        self.odds_calls = 0

    def fetch_sports(self) -> list[dict[str, object]]:
        return [
            {
                "key": "soccer_test",
                "group": "Soccer",
                "active": True,
                "has_outrights": False,
            }
        ]

    def fetch_events(
        self,
        sport_key: str,
        start: object,
        end: object,
    ) -> list[dict]:
        return [
            {
                "id": "odds-500",
                "sport_key": sport_key,
                "commence_time": "2026-07-24T18:00:00Z",
                "home_team": "Paris",
                "away_team": "Lyon",
            }
        ]

    def fetch_odds(
        self,
        sport_key: str,
        event_ids: tuple[str, ...],
        start: object,
        end: object,
    ) -> OddsApiResponse:
        self.odds_calls += 1
        return OddsApiResponse(
            payload=[
                {
                    "id": "odds-500",
                    "commence_time": "2026-07-24T18:00:00Z",
                    "home_team": "Paris",
                    "away_team": "Lyon",
                    "bookmakers": [
                        {
                            "key": "winamax_fr",
                            "title": "Winamax",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Paris", "price": 1.20},
                                        {"name": "Draw", "price": 7.0},
                                        {"name": "Lyon", "price": 12.0},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            requests_remaining=250,
            requests_used=1,
            requests_last=1,
        )


class FootballValueEvaluationTests(unittest.TestCase):
    def test_zero_ready_matches_never_constructs_odds_collector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_settings = settings(root, odds_key=None)
            write_analysis(root, [])
            factory = FailingFactory()

            report = evaluate_live_football_value(
                app_settings,
                (date(2026, 7, 24), date(2026, 7, 25)),
                max_credits=3,
                collector_factory=factory,  # type: ignore[arg-type]
            )

            self.assertEqual(factory.calls, 0)
            self.assertEqual(report.actual_credits, 0)
            self.assertEqual(report.expected_credits, 0)
            output = json.loads(report.output_file.read_text(encoding="utf-8"))
            self.assertEqual(output["catalog_api_calls"], 0)
            self.assertEqual(
                output["guard"],
                "no_ready_match_no_odds_api_contact",
            )

    def test_low_odds_are_kept_when_expected_value_is_positive(self) -> None:
        prediction = {
            "home_team": "Paris FC",
            "away_team": "Lyon",
            "ensemble": {"home": 0.88, "draw": 0.07, "away": 0.05},
        }
        prices = [
            {
                "selection": "Paris",
                "decimal_price": 1.20,
                "last_update": "2026-07-24T10:00:00Z",
            },
            {"selection": "Draw", "decimal_price": 7.0},
            {"selection": "Lyon", "decimal_price": 12.0},
        ]

        result = evaluate_winamax_prices(prediction, prices)

        self.assertEqual(result["status"], "VALIDATED")
        self.assertEqual(result["best"]["outcome"], "home")
        self.assertAlmostEqual(result["best"]["expected_roi"], 0.056)

    def test_negative_expected_value_is_not_selected_even_at_high_probability(
        self,
    ) -> None:
        prediction = {
            "home_team": "A",
            "away_team": "B",
            "ensemble": {"home": 0.79, "draw": 0.12, "away": 0.09},
        }
        prices = [
            {"selection": "A", "decimal_price": 1.20},
            {"selection": "Draw", "decimal_price": 5.0},
            {"selection": "B", "decimal_price": 8.0},
        ]

        result = evaluate_winamax_prices(prediction, prices)

        self.assertEqual(result["status"], "NO_BET")

    def test_outcomes_are_mapped_to_real_team_names(self) -> None:
        self.assertEqual(_outcome_key("Paris", "Paris FC", "Lyon"), "home")
        self.assertEqual(_outcome_key("Draw", "Paris FC", "Lyon"), "draw")
        self.assertEqual(_outcome_key("Lyon", "Paris FC", "Lyon"), "away")
        self.assertIsNone(_outcome_key("Madrid", "Paris FC", "Lyon"))

    def test_ready_match_creates_one_winamax_paper_bet_without_duplicate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_settings = settings(root, odds_key="test-key")
            prediction = {
                "fixture_id": 500,
                "starts_at": "2026-07-24T20:00:00+02:00",
                "home_team": "Paris FC",
                "away_team": "Lyon",
                "ensemble": {"home": 0.88, "draw": 0.07, "away": 0.05},
            }
            write_analysis(root, [prediction])
            write_fixtures(root)
            dates = (date(2026, 7, 24), date(2026, 7, 25))

            first = evaluate_live_football_value(
                app_settings,
                dates,
                max_credits=1,
                collector_factory=FakeCollector,
            )
            second = evaluate_live_football_value(
                app_settings,
                dates,
                max_credits=1,
                collector_factory=FakeCollector,
            )

            self.assertEqual(first.actual_credits, 1)
            self.assertEqual(first.validated, 1)
            self.assertEqual(first.new_paper_bets, 1)
            self.assertEqual(second.new_paper_bets, 0)
            self.assertEqual(second.existing_paper_bets, 1)
            paper = json.loads(first.paper_file.read_text(encoding="utf-8"))
            self.assertEqual(len(paper["bets"]), 1)
            self.assertEqual(paper["bets"][0]["decimal_price"], 1.20)

    def test_credit_cap_stops_before_first_paid_odds_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_settings = settings(root, odds_key="test-key")
            write_analysis(
                root,
                [
                    {
                        "fixture_id": 500,
                        "starts_at": "2026-07-24T20:00:00+02:00",
                        "home_team": "Paris FC",
                        "away_team": "Lyon",
                        "ensemble": {
                            "home": 0.88,
                            "draw": 0.07,
                            "away": 0.05,
                        },
                    }
                ],
            )
            write_fixtures(root)
            dates = (date(2026, 7, 24), date(2026, 7, 25))
            collector = FakeCollector("test-key")
            discovery = (
                {
                    "soccer_a": [{"id": "odds-a"}],
                    "soccer_b": [{"id": "odds-b"}],
                },
                [],
                3,
                [],
            )

            with patch(
                "bot_sports_pro.services.football_value_evaluation."
                "_discover_ready_events",
                return_value=discovery,
            ):
                with self.assertRaisesRegex(RuntimeError, "Coût prévu 2 crédits"):
                    evaluate_live_football_value(
                        app_settings,
                        dates,
                        max_credits=1,
                        collector_factory=lambda api_key: collector,
                    )

            self.assertEqual(collector.odds_calls, 0)


if __name__ == "__main__":
    unittest.main()
