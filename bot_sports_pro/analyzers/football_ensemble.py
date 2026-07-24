from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Any, Iterable

from bot_sports_pro.analyzers.football_poisson import ChronologicalPoissonModel


@dataclass(frozen=True, slots=True)
class ProbabilityVector:
    home: float
    draw: float
    away: float

    def __post_init__(self) -> None:
        values = (self.home, self.draw, self.away)
        if any(value < 0.0 or value > 1.0 for value in values):
            raise ValueError("Chaque probabilité doit être comprise entre 0 et 1.")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-8):
            raise ValueError("Les probabilités 1N2 doivent totaliser 1.")


@dataclass(frozen=True, slots=True)
class EnsemblePrediction:
    fixture_id: int
    starts_at: str
    league_id: int
    home_team: str
    away_team: str
    actual_outcome: str
    baseline: ProbabilityVector
    poisson: ProbabilityVector
    elo: ProbabilityVector
    recent_form: ProbabilityVector


@dataclass(frozen=True, slots=True)
class LiveEnsemblePrediction:
    fixture_id: int
    starts_at: str
    league_id: int
    home_team: str
    away_team: str
    expected_home_goals: float
    expected_away_goals: float
    poisson: ProbabilityVector
    elo: ProbabilityVector
    ensemble: ProbabilityVector
    over_1_5: float
    over_2_5: float
    both_teams_score: float


@dataclass(slots=True)
class OutcomeHistory:
    games: int = 0
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0

    def probabilities(self, prior_games: float = 20.0) -> ProbabilityVector:
        denominator = self.games + prior_games
        return ProbabilityVector(
            home=(self.home_wins + prior_games * 0.45) / denominator,
            draw=(self.draws + prior_games * 0.27) / denominator,
            away=(self.away_wins + prior_games * 0.28) / denominator,
        )


@dataclass(frozen=True, slots=True)
class FormEntry:
    points: float
    goal_difference: float


class ChronologicalEnsembleFeatures:
    """Calcule Elo et forme sans jamais lire un résultat futur."""

    def __init__(
        self,
        min_team_matches: int = 5,
        min_league_matches: int = 30,
        elo_k: float = 20.0,
        elo_home_advantage: float = 80.0,
        form_window: int = 5,
        form_scale: float = 0.35,
    ) -> None:
        if elo_k <= 0 or form_window < 1 or form_scale < 0:
            raise ValueError("Paramètres Elo/forme invalides.")
        self.min_team_matches = min_team_matches
        self.min_league_matches = min_league_matches
        self.elo_k = elo_k
        self.elo_home_advantage = elo_home_advantage
        self.form_window = form_window
        self.form_scale = form_scale

    def evaluate(self, matches: Iterable[dict[str, Any]]) -> tuple[EnsemblePrediction, ...]:
        raw_matches = list(matches)
        poisson_result = ChronologicalPoissonModel(
            min_team_matches=self.min_team_matches,
            min_league_matches=self.min_league_matches,
        ).evaluate(raw_matches)
        poisson_by_fixture = {
            prediction.fixture_id: prediction
            for prediction in poisson_result.predictions
        }
        prepared = sorted(
            (
                self._prepare(item)
                for item in raw_matches
                if item.get("status") == "FT"
            ),
            key=lambda item: (item["_starts_at"], item["fixture_id"]),
        )
        league_outcomes: dict[int, OutcomeHistory] = {}
        ratings: dict[tuple[int, int], float] = defaultdict(lambda: 1500.0)
        forms: dict[tuple[int, int], deque[FormEntry]] = {}
        predictions: list[EnsemblePrediction] = []

        for _, simultaneous_iter in groupby(
            prepared,
            key=lambda item: item["_starts_at"],
        ):
            simultaneous = list(simultaneous_iter)
            for match in simultaneous:
                poisson = poisson_by_fixture.get(match["fixture_id"])
                if poisson is None:
                    continue
                league_id = match["league_id"]
                baseline = league_outcomes.get(
                    league_id,
                    OutcomeHistory(),
                ).probabilities()
                elo = self._elo_probabilities(match, baseline, ratings)
                recent_form = self._form_probabilities(match, baseline, forms)
                predictions.append(
                    EnsemblePrediction(
                        fixture_id=match["fixture_id"],
                        starts_at=match["starts_at"],
                        league_id=league_id,
                        home_team=match["home_team"],
                        away_team=match["away_team"],
                        actual_outcome=self._actual_outcome(match),
                        baseline=baseline,
                        poisson=ProbabilityVector(
                            home=poisson.home_win,
                            draw=poisson.draw,
                            away=poisson.away_win,
                        ),
                        elo=elo,
                        recent_form=recent_form,
                    )
                )
            for match in simultaneous:
                self._update(match, league_outcomes, ratings, forms)
        return tuple(predictions)

    def predict_upcoming(
        self,
        history: Iterable[dict[str, Any]],
        fixtures: Iterable[dict[str, Any]],
        poisson_weight: float,
        elo_weight: float,
        form_weight: float,
    ) -> tuple[LiveEnsemblePrediction, ...]:
        historical_matches = list(history)
        poisson_model = ChronologicalPoissonModel(
            min_team_matches=self.min_team_matches,
            min_league_matches=self.min_league_matches,
        )
        poisson_state = poisson_model.fit(historical_matches)
        league_outcomes: dict[int, OutcomeHistory] = {}
        ratings: dict[tuple[int, int], float] = defaultdict(lambda: 1500.0)
        forms: dict[tuple[int, int], deque[FormEntry]] = {}
        prepared_history = sorted(
            (
                self._prepare(item)
                for item in historical_matches
                if item.get("status") == "FT"
            ),
            key=lambda item: (item["_starts_at"], item["fixture_id"]),
        )
        for match in prepared_history:
            self._update(match, league_outcomes, ratings, forms)

        predictions: list[LiveEnsemblePrediction] = []
        for raw_fixture in fixtures:
            fixture = self._prepare_upcoming(raw_fixture)
            poisson = poisson_model.predict_upcoming(fixture, poisson_state)
            if poisson is None:
                continue
            baseline = league_outcomes.get(
                fixture["league_id"],
                OutcomeHistory(),
            ).probabilities()
            elo = self._elo_probabilities(fixture, baseline, ratings)
            recent_form = self._form_probabilities(fixture, baseline, forms)
            ensemble = combine_probability_vectors(
                poisson=ProbabilityVector(
                    poisson.home_win,
                    poisson.draw,
                    poisson.away_win,
                ),
                elo=elo,
                recent_form=recent_form,
                poisson_weight=poisson_weight,
                elo_weight=elo_weight,
                form_weight=form_weight,
            )
            predictions.append(
                LiveEnsemblePrediction(
                    fixture_id=fixture["fixture_id"],
                    starts_at=fixture["starts_at"],
                    league_id=fixture["league_id"],
                    home_team=fixture["home_team"],
                    away_team=fixture["away_team"],
                    expected_home_goals=poisson.expected_home_goals,
                    expected_away_goals=poisson.expected_away_goals,
                    poisson=ProbabilityVector(
                        poisson.home_win,
                        poisson.draw,
                        poisson.away_win,
                    ),
                    elo=elo,
                    ensemble=ensemble,
                    over_1_5=poisson.over_1_5,
                    over_2_5=poisson.over_2_5,
                    both_teams_score=poisson.both_teams_score,
                )
            )
        return tuple(predictions)

    def _elo_probabilities(
        self,
        match: dict[str, Any],
        baseline: ProbabilityVector,
        ratings: dict[tuple[int, int], float],
    ) -> ProbabilityVector:
        league_id = match["league_id"]
        home_rating = ratings[(league_id, match["home_team_id"])]
        away_rating = ratings[(league_id, match["away_team_id"])]
        difference = home_rating + self.elo_home_advantage - away_rating
        decisive_home = 1.0 / (1.0 + 10.0 ** (-difference / 400.0))
        draw_attenuation = math.exp(-abs(difference) / 800.0)
        draw = self._clamp(baseline.draw * draw_attenuation, 0.10, 0.34)
        return ProbabilityVector(
            home=(1.0 - draw) * decisive_home,
            draw=draw,
            away=(1.0 - draw) * (1.0 - decisive_home),
        )

    def _form_probabilities(
        self,
        match: dict[str, Any],
        baseline: ProbabilityVector,
        forms: dict[tuple[int, int], deque[FormEntry]],
    ) -> ProbabilityVector:
        league_id = match["league_id"]
        home_form = forms.get((league_id, match["home_team_id"]), deque())
        away_form = forms.get((league_id, match["away_team_id"]), deque())
        form_difference = self._form_score(home_form) - self._form_score(away_form)
        shift = self.form_scale * form_difference
        logits = (
            math.log(max(baseline.home, 1e-12)) + shift,
            math.log(max(baseline.draw, 1e-12)) - 0.10 * abs(shift),
            math.log(max(baseline.away, 1e-12)) - shift,
        )
        largest = max(logits)
        exponentials = tuple(math.exp(value - largest) for value in logits)
        denominator = sum(exponentials)
        return ProbabilityVector(
            home=exponentials[0] / denominator,
            draw=exponentials[1] / denominator,
            away=exponentials[2] / denominator,
        )

    @staticmethod
    def _form_score(entries: deque[FormEntry]) -> float:
        if not entries:
            return 0.0
        points = sum(entry.points for entry in entries) / (3.0 * len(entries))
        goal_difference = sum(entry.goal_difference for entry in entries) / len(entries)
        return points + 0.10 * math.tanh(goal_difference / 2.0)

    def _update(
        self,
        match: dict[str, Any],
        league_outcomes: dict[int, OutcomeHistory],
        ratings: dict[tuple[int, int], float],
        forms: dict[tuple[int, int], deque[FormEntry]],
    ) -> None:
        league_id = match["league_id"]
        home_key = (league_id, match["home_team_id"])
        away_key = (league_id, match["away_team_id"])
        history = league_outcomes.setdefault(league_id, OutcomeHistory())
        home_rating = ratings[home_key]
        away_rating = ratings[away_key]
        expected_home = 1.0 / (
            1.0
            + 10.0
            ** (
                -(
                    home_rating
                    + self.elo_home_advantage
                    - away_rating
                )
                / 400.0
            )
        )
        outcome = self._actual_outcome(match)
        actual_home = {"home": 1.0, "draw": 0.5, "away": 0.0}[outcome]
        change = self.elo_k * (actual_home - expected_home)
        ratings[home_key] = home_rating + change
        ratings[away_key] = away_rating - change

        if outcome == "home":
            history.home_wins += 1
            home_points, away_points = 3.0, 0.0
        elif outcome == "away":
            history.away_wins += 1
            home_points, away_points = 0.0, 3.0
        else:
            history.draws += 1
            home_points = away_points = 1.0
        history.games += 1

        home_form = forms.setdefault(
            home_key,
            deque(maxlen=self.form_window),
        )
        away_form = forms.setdefault(
            away_key,
            deque(maxlen=self.form_window),
        )
        goal_difference = match["home_goals"] - match["away_goals"]
        home_form.append(FormEntry(home_points, goal_difference))
        away_form.append(FormEntry(away_points, -goal_difference))

    @staticmethod
    def _prepare(item: dict[str, Any]) -> dict[str, Any]:
        starts_at = datetime.fromisoformat(str(item["starts_at"]))
        if starts_at.tzinfo is None:
            raise ValueError("starts_at doit contenir un fuseau horaire.")
        return {
            **item,
            "fixture_id": int(item["fixture_id"]),
            "league_id": int(item["league_id"]),
            "home_team_id": int(item["home_team_id"]),
            "away_team_id": int(item["away_team_id"]),
            "home_goals": int(item["home_goals"]),
            "away_goals": int(item["away_goals"]),
            "_starts_at": starts_at,
        }

    @staticmethod
    def _prepare_upcoming(item: dict[str, Any]) -> dict[str, Any]:
        starts_at = datetime.fromisoformat(str(item["starts_at"]))
        if starts_at.tzinfo is None:
            raise ValueError("starts_at doit contenir un fuseau horaire.")
        return {
            **item,
            "fixture_id": int(item["fixture_id"]),
            "league_id": int(item["league_id"]),
            "home_team_id": int(item["home_team_id"]),
            "away_team_id": int(item["away_team_id"]),
            "_starts_at": starts_at,
        }

    @staticmethod
    def _actual_outcome(match: dict[str, Any]) -> str:
        if match["home_goals"] > match["away_goals"]:
            return "home"
        if match["home_goals"] < match["away_goals"]:
            return "away"
        return "draw"

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))


def blend_probabilities(
    prediction: EnsemblePrediction,
    poisson_weight: float,
    elo_weight: float,
    form_weight: float,
) -> ProbabilityVector:
    return combine_probability_vectors(
        poisson=prediction.poisson,
        elo=prediction.elo,
        recent_form=prediction.recent_form,
        poisson_weight=poisson_weight,
        elo_weight=elo_weight,
        form_weight=form_weight,
    )


def combine_probability_vectors(
    poisson: ProbabilityVector,
    elo: ProbabilityVector,
    recent_form: ProbabilityVector,
    poisson_weight: float,
    elo_weight: float,
    form_weight: float,
) -> ProbabilityVector:
    if any(weight < 0 for weight in (poisson_weight, elo_weight, form_weight)):
        raise ValueError("Les poids ne peuvent pas être négatifs.")
    total_weight = poisson_weight + elo_weight + form_weight
    if not math.isclose(total_weight, 1.0, abs_tol=1e-8):
        raise ValueError("La somme des poids doit être égale à 1.")
    return ProbabilityVector(
        home=(
            poisson_weight * poisson.home
            + elo_weight * elo.home
            + form_weight * recent_form.home
        ),
        draw=(
            poisson_weight * poisson.draw
            + elo_weight * elo.draw
            + form_weight * recent_form.draw
        ),
        away=(
            poisson_weight * poisson.away
            + elo_weight * elo.away
            + form_weight * recent_form.away
        ),
    )
