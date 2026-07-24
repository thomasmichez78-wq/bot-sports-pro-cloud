from __future__ import annotations

import unittest

from bot_sports_pro.analyzers.football_ensemble import (
    ChronologicalEnsembleFeatures,
    EnsemblePrediction,
    ProbabilityVector,
    blend_probabilities,
)
from bot_sports_pro.services.football_model_comparison import select_blend_weights


def fixture(
    fixture_id: int,
    starts_at: str,
    home_id: int,
    away_id: int,
    home_goals: int,
    away_goals: int,
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "starts_at": starts_at,
        "status": "FT",
        "league_id": 71,
        "home_team_id": home_id,
        "home_team": f"Équipe {home_id}",
        "away_team_id": away_id,
        "away_team": f"Équipe {away_id}",
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


class FootballEnsembleTests(unittest.TestCase):
    def test_selects_poisson_when_it_is_strictly_best(self) -> None:
        baseline = ProbabilityVector(0.34, 0.33, 0.33)
        strong = ProbabilityVector(0.90, 0.05, 0.05)
        weak = ProbabilityVector(0.10, 0.45, 0.45)
        predictions = (
            EnsemblePrediction(
                fixture_id=1,
                starts_at="2023-01-01T12:00:00+01:00",
                league_id=71,
                home_team="A",
                away_team="B",
                actual_outcome="home",
                baseline=baseline,
                poisson=strong,
                elo=weak,
                recent_form=baseline,
            ),
        )

        weights = select_blend_weights(predictions)

        self.assertEqual(weights.poisson, 1.0)
        self.assertEqual(weights.elo, 0.0)
        self.assertEqual(weights.recent_form, 0.0)

    def test_simultaneous_match_result_does_not_change_other_prediction(self) -> None:
        model = ChronologicalEnsembleFeatures(
            min_team_matches=1,
            min_league_matches=1,
        )
        history = [
            fixture(1, "2023-01-01T15:00:00+01:00", 10, 20, 1, 0),
            fixture(2, "2023-01-01T15:00:00+01:00", 30, 40, 0, 1),
            fixture(3, "2023-01-08T15:00:00+01:00", 10, 30, 8, 0),
            fixture(4, "2023-01-08T15:00:00+01:00", 20, 40, 1, 1),
        ]
        changed = [
            *history[:2],
            fixture(3, "2023-01-08T15:00:00+01:00", 10, 30, 0, 8),
            history[3],
        ]

        first = next(
            item for item in model.evaluate(history) if item.fixture_id == 4
        )
        second = next(
            item for item in model.evaluate(changed) if item.fixture_id == 4
        )

        self.assertEqual(first.elo, second.elo)
        self.assertEqual(first.recent_form, second.recent_form)

    def test_live_ensemble_matches_backtest_state(self) -> None:
        model = ChronologicalEnsembleFeatures(
            min_team_matches=1,
            min_league_matches=1,
        )
        history = [
            fixture(1, "2023-01-01T15:00:00+01:00", 10, 20, 2, 0),
        ]
        upcoming = {
            "fixture_id": 2,
            "starts_at": "2023-01-08T15:00:00+01:00",
            "league_id": 71,
            "home_team_id": 20,
            "home_team": "Équipe 20",
            "away_team_id": 10,
            "away_team": "Équipe 10",
        }

        live = model.predict_upcoming(
            history,
            [upcoming],
            poisson_weight=0.5,
            elo_weight=0.5,
            form_weight=0.0,
        )[0]
        backtest = model.evaluate(
            [
                *history,
                fixture(2, "2023-01-08T15:00:00+01:00", 20, 10, 1, 1),
            ]
        )[0]
        blended_backtest = blend_probabilities(backtest, 0.5, 0.5, 0.0)

        self.assertAlmostEqual(live.ensemble.home, blended_backtest.home)
        self.assertAlmostEqual(live.ensemble.draw, blended_backtest.draw)
        self.assertAlmostEqual(live.ensemble.away, blended_backtest.away)


if __name__ == "__main__":
    unittest.main()
