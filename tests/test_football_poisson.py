from __future__ import annotations

import unittest

from bot_sports_pro.analyzers.football_poisson import ChronologicalPoissonModel


def fixture(
    fixture_id: int,
    starts_at: str,
    home_id: int,
    away_id: int,
    home_goals: int,
    away_goals: int,
    status: str = "FT",
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "starts_at": starts_at,
        "status": status,
        "league_id": 71,
        "home_team_id": home_id,
        "home_team": f"Équipe {home_id}",
        "away_team_id": away_id,
        "away_team": f"Équipe {away_id}",
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


class FootballPoissonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = ChronologicalPoissonModel(
            min_team_matches=1,
            min_league_matches=1,
        )

    def test_probabilities_sum_to_one_and_non_regulation_is_excluded(self) -> None:
        result = self.model.evaluate(
            [
                fixture(1, "2024-01-01T15:00:00+01:00", 10, 20, 2, 0),
                fixture(2, "2024-01-08T15:00:00+01:00", 20, 10, 1, 1),
                fixture(
                    3,
                    "2024-01-15T15:00:00+01:00",
                    10,
                    20,
                    3,
                    2,
                    status="AET",
                ),
            ]
        )

        self.assertEqual(result.input_matches, 3)
        self.assertEqual(result.excluded_non_regulation, 1)
        self.assertEqual(len(result.predictions), 1)
        prediction = result.predictions[0]
        self.assertAlmostEqual(
            prediction.home_win + prediction.draw + prediction.away_win,
            1.0,
        )

    def test_simultaneous_results_do_not_leak_between_predictions(self) -> None:
        history = [
            fixture(1, "2024-01-01T15:00:00+01:00", 10, 20, 1, 0),
            fixture(2, "2024-01-01T15:00:00+01:00", 30, 40, 0, 1),
            fixture(3, "2024-01-08T15:00:00+01:00", 10, 30, 9, 0),
            fixture(4, "2024-01-08T15:00:00+01:00", 20, 40, 1, 1),
        ]
        changed_same_time_result = [
            *history[:2],
            fixture(3, "2024-01-08T15:00:00+01:00", 10, 30, 0, 9),
            history[3],
        ]

        first = self.model.evaluate(history)
        second = self.model.evaluate(changed_same_time_result)
        first_fixture_four = next(
            item for item in first.predictions if item.fixture_id == 4
        )
        second_fixture_four = next(
            item for item in second.predictions if item.fixture_id == 4
        )

        self.assertAlmostEqual(
            first_fixture_four.home_win,
            second_fixture_four.home_win,
        )
        self.assertAlmostEqual(
            first_fixture_four.draw,
            second_fixture_four.draw,
        )
        self.assertAlmostEqual(
            first_fixture_four.away_win,
            second_fixture_four.away_win,
        )

    def test_live_prediction_matches_chronological_backtest_prediction(self) -> None:
        model = ChronologicalPoissonModel(
            min_team_matches=1,
            min_league_matches=1,
        )
        history = [
            fixture(1, "2024-01-01T15:00:00+01:00", 10, 20, 2, 0),
        ]
        upcoming = {
            "fixture_id": 2,
            "starts_at": "2024-01-08T15:00:00+01:00",
            "league_id": 71,
            "home_team_id": 20,
            "home_team": "Équipe 20",
            "away_team_id": 10,
            "away_team": "Équipe 10",
        }
        state = model.fit(history)

        live = model.predict_upcoming(upcoming, state)
        backtest = model.evaluate(
            [
                *history,
                fixture(2, "2024-01-08T15:00:00+01:00", 20, 10, 1, 1),
            ]
        ).predictions[0]

        self.assertIsNotNone(live)
        assert live is not None
        self.assertAlmostEqual(live.home_win, backtest.home_win)
        self.assertAlmostEqual(live.draw, backtest.draw)
        self.assertAlmostEqual(live.away_win, backtest.away_win)


if __name__ == "__main__":
    unittest.main()
