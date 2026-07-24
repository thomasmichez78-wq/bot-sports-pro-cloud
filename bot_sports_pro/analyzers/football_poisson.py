from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Any, Iterable


REGULATION_STATUS = "FT"


@dataclass(slots=True)
class TeamRollingStats:
    games: int = 0
    home_games: int = 0
    away_games: int = 0
    home_goals_for: int = 0
    home_goals_against: int = 0
    away_goals_for: int = 0
    away_goals_against: int = 0


@dataclass(slots=True)
class LeagueRollingStats:
    games: int = 0
    home_goals: int = 0
    away_goals: int = 0
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0


@dataclass(slots=True)
class PoissonModelState:
    leagues: dict[int, LeagueRollingStats]
    teams: dict[tuple[int, int], TeamRollingStats]


@dataclass(frozen=True, slots=True)
class UpcomingPoissonPrediction:
    fixture_id: int
    starts_at: str
    league_id: int
    home_team_id: int
    home_team: str
    away_team_id: int
    away_team: str
    expected_home_goals: float
    expected_away_goals: float
    home_win: float
    draw: float
    away_win: float
    over_1_5: float
    over_2_5: float
    both_teams_score: float


@dataclass(frozen=True, slots=True)
class MatchProbabilities:
    fixture_id: int
    starts_at: str
    league_id: int
    home_team_id: int
    home_team: str
    away_team_id: int
    away_team: str
    expected_home_goals: float
    expected_away_goals: float
    home_win: float
    draw: float
    away_win: float
    baseline_home_win: float
    baseline_draw: float
    baseline_away_win: float
    over_1_5: float
    over_2_5: float
    both_teams_score: float
    actual_home_goals: int
    actual_away_goals: int

    @property
    def actual_outcome(self) -> str:
        if self.actual_home_goals > self.actual_away_goals:
            return "home"
        if self.actual_home_goals < self.actual_away_goals:
            return "away"
        return "draw"


@dataclass(frozen=True, slots=True)
class ChronologicalModelResult:
    predictions: tuple[MatchProbabilities, ...]
    input_matches: int
    regulation_matches: int
    excluded_non_regulation: int
    warmup_matches: int


class ChronologicalPoissonModel:
    """Poisson simple alimenté uniquement par les matchs déjà commencés."""

    def __init__(
        self,
        min_team_matches: int = 5,
        min_league_matches: int = 30,
        prior_games: float = 20.0,
        team_shrinkage: float = 6.0,
        max_goals: int = 10,
    ) -> None:
        if min_team_matches < 1:
            raise ValueError("min_team_matches doit être positif.")
        if min_league_matches < 1:
            raise ValueError("min_league_matches doit être positif.")
        if prior_games <= 0 or team_shrinkage <= 0:
            raise ValueError("Les paramètres de régularisation doivent être positifs.")
        if max_goals < 6:
            raise ValueError("max_goals doit être au moins égal à 6.")
        self.min_team_matches = min_team_matches
        self.min_league_matches = min_league_matches
        self.prior_games = prior_games
        self.team_shrinkage = team_shrinkage
        self.max_goals = max_goals

    def fit(self, matches: Iterable[dict[str, Any]]) -> PoissonModelState:
        prepared = sorted(
            (self._validated_match(item) for item in matches),
            key=lambda item: (item["_starts_at"], item["fixture_id"]),
        )
        state = PoissonModelState(leagues={}, teams={})
        for match in prepared:
            if match["status"] == REGULATION_STATUS:
                self._update(match, state.leagues, state.teams)
        return state

    def predict_upcoming(
        self,
        fixture: dict[str, Any],
        state: PoissonModelState,
    ) -> UpcomingPoissonPrediction | None:
        match = self._validated_upcoming_fixture(fixture)
        values = self._probability_values(match, state.leagues, state.teams)
        if values is None:
            return None
        return UpcomingPoissonPrediction(
            fixture_id=match["fixture_id"],
            starts_at=match["starts_at"],
            league_id=match["league_id"],
            home_team_id=match["home_team_id"],
            home_team=match["home_team"],
            away_team_id=match["away_team_id"],
            away_team=match["away_team"],
            expected_home_goals=values["expected_home"],
            expected_away_goals=values["expected_away"],
            home_win=values["home"],
            draw=values["draw"],
            away_win=values["away"],
            over_1_5=values["over_1_5"],
            over_2_5=values["over_2_5"],
            both_teams_score=values["both_teams_score"],
        )

    def evaluate(self, matches: Iterable[dict[str, Any]]) -> ChronologicalModelResult:
        prepared = sorted(
            (self._validated_match(item) for item in matches),
            key=lambda item: (item["_starts_at"], item["fixture_id"]),
        )
        regulation = [item for item in prepared if item["status"] == REGULATION_STATUS]
        league_stats: dict[int, LeagueRollingStats] = {}
        team_stats: dict[tuple[int, int], TeamRollingStats] = {}
        predictions: list[MatchProbabilities] = []
        warmup_matches = 0

        # Les matchs ayant exactement la même heure sont tous prédits avant que
        # leurs résultats ne soient ajoutés à l'état.
        for _, simultaneous_matches_iter in groupby(
            regulation,
            key=lambda item: item["_starts_at"],
        ):
            simultaneous_matches = list(simultaneous_matches_iter)
            for match in simultaneous_matches:
                prediction = self._predict(match, league_stats, team_stats)
                if prediction is None:
                    warmup_matches += 1
                else:
                    predictions.append(prediction)
            for match in simultaneous_matches:
                self._update(match, league_stats, team_stats)

        return ChronologicalModelResult(
            predictions=tuple(predictions),
            input_matches=len(prepared),
            regulation_matches=len(regulation),
            excluded_non_regulation=len(prepared) - len(regulation),
            warmup_matches=warmup_matches,
        )

    def _predict(
        self,
        match: dict[str, Any],
        leagues: dict[int, LeagueRollingStats],
        teams: dict[tuple[int, int], TeamRollingStats],
    ) -> MatchProbabilities | None:
        values = self._probability_values(match, leagues, teams)
        if values is None:
            return None
        return MatchProbabilities(
            fixture_id=match["fixture_id"],
            starts_at=match["starts_at"],
            league_id=match["league_id"],
            home_team_id=match["home_team_id"],
            home_team=match["home_team"],
            away_team_id=match["away_team_id"],
            away_team=match["away_team"],
            expected_home_goals=values["expected_home"],
            expected_away_goals=values["expected_away"],
            home_win=values["home"],
            draw=values["draw"],
            away_win=values["away"],
            baseline_home_win=values["baseline_home"],
            baseline_draw=values["baseline_draw"],
            baseline_away_win=values["baseline_away"],
            over_1_5=values["over_1_5"],
            over_2_5=values["over_2_5"],
            both_teams_score=values["both_teams_score"],
            actual_home_goals=match["home_goals"],
            actual_away_goals=match["away_goals"],
        )

    def _probability_values(
        self,
        match: dict[str, Any],
        leagues: dict[int, LeagueRollingStats],
        teams: dict[tuple[int, int], TeamRollingStats],
    ) -> dict[str, float] | None:
        league_id = match["league_id"]
        league = leagues.get(league_id, LeagueRollingStats())
        home = teams.get((league_id, match["home_team_id"]), TeamRollingStats())
        away = teams.get((league_id, match["away_team_id"]), TeamRollingStats())
        if (
            league.games < self.min_league_matches
            or home.games < self.min_team_matches
            or away.games < self.min_team_matches
        ):
            return None

        league_home_rate = (
            league.home_goals + self.prior_games * 1.45
        ) / (league.games + self.prior_games)
        league_away_rate = (
            league.away_goals + self.prior_games * 1.15
        ) / (league.games + self.prior_games)

        home_attack = self._ratio(
            home.home_goals_for,
            home.home_games,
            league_home_rate,
        )
        home_defence = self._ratio(
            home.home_goals_against,
            home.home_games,
            league_away_rate,
        )
        away_attack = self._ratio(
            away.away_goals_for,
            away.away_games,
            league_away_rate,
        )
        away_defence = self._ratio(
            away.away_goals_against,
            away.away_games,
            league_home_rate,
        )

        expected_home = self._clamp(
            league_home_rate * home_attack * away_defence,
            0.20,
            4.50,
        )
        expected_away = self._clamp(
            league_away_rate * away_attack * home_defence,
            0.20,
            4.50,
        )
        probabilities = self._score_probabilities(expected_home, expected_away)
        outcome_denominator = league.games + self.prior_games
        baseline_home = (
            league.home_wins + self.prior_games * 0.45
        ) / outcome_denominator
        baseline_draw = (
            league.draws + self.prior_games * 0.27
        ) / outcome_denominator
        baseline_away = (
            league.away_wins + self.prior_games * 0.28
        ) / outcome_denominator

        return {
            "expected_home": expected_home,
            "expected_away": expected_away,
            "home": probabilities["home"],
            "draw": probabilities["draw"],
            "away": probabilities["away"],
            "baseline_home": baseline_home,
            "baseline_draw": baseline_draw,
            "baseline_away": baseline_away,
            "over_1_5": probabilities["over_1_5"],
            "over_2_5": probabilities["over_2_5"],
            "both_teams_score": probabilities["both_teams_score"],
        }

    def _ratio(self, goals: int, games: int, league_rate: float) -> float:
        smoothed_rate = (
            goals + self.team_shrinkage * league_rate
        ) / (games + self.team_shrinkage)
        return smoothed_rate / league_rate

    def _score_probabilities(
        self,
        expected_home: float,
        expected_away: float,
    ) -> dict[str, float]:
        home_distribution = self._poisson_distribution(expected_home)
        away_distribution = self._poisson_distribution(expected_away)
        grid_total = sum(home_distribution) * sum(away_distribution)
        home_win = 0.0
        draw = 0.0
        away_win = 0.0
        under_or_equal_1 = 0.0
        under_or_equal_2 = 0.0
        no_btts = 0.0

        for home_goals, home_probability in enumerate(home_distribution):
            for away_goals, away_probability in enumerate(away_distribution):
                probability = home_probability * away_probability / grid_total
                if home_goals > away_goals:
                    home_win += probability
                elif home_goals < away_goals:
                    away_win += probability
                else:
                    draw += probability
                total = home_goals + away_goals
                if total <= 1:
                    under_or_equal_1 += probability
                if total <= 2:
                    under_or_equal_2 += probability
                if home_goals == 0 or away_goals == 0:
                    no_btts += probability

        return {
            "home": home_win,
            "draw": draw,
            "away": away_win,
            "over_1_5": 1.0 - under_or_equal_1,
            "over_2_5": 1.0 - under_or_equal_2,
            "both_teams_score": 1.0 - no_btts,
        }

    def _poisson_distribution(self, expected_goals: float) -> list[float]:
        distribution = [math.exp(-expected_goals)]
        for goals in range(1, self.max_goals + 1):
            distribution.append(distribution[-1] * expected_goals / goals)
        return distribution

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))

    @staticmethod
    def _validated_match(item: dict[str, Any]) -> dict[str, Any]:
        required = (
            "fixture_id",
            "starts_at",
            "status",
            "league_id",
            "home_team_id",
            "home_team",
            "away_team_id",
            "away_team",
            "home_goals",
            "away_goals",
        )
        missing = [field for field in required if item.get(field) is None]
        if missing:
            raise ValueError(
                f"Match incomplet, champs absents : {', '.join(missing)}."
            )
        starts_at = datetime.fromisoformat(str(item["starts_at"]))
        if starts_at.tzinfo is None:
            raise ValueError("starts_at doit contenir un fuseau horaire.")
        home_goals = int(item["home_goals"])
        away_goals = int(item["away_goals"])
        if home_goals < 0 or away_goals < 0:
            raise ValueError("Les scores ne peuvent pas être négatifs.")
        return {
            **item,
            "fixture_id": int(item["fixture_id"]),
            "league_id": int(item["league_id"]),
            "home_team_id": int(item["home_team_id"]),
            "away_team_id": int(item["away_team_id"]),
            "home_goals": home_goals,
            "away_goals": away_goals,
            "_starts_at": starts_at,
        }

    @staticmethod
    def _validated_upcoming_fixture(item: dict[str, Any]) -> dict[str, Any]:
        required = (
            "fixture_id",
            "starts_at",
            "league_id",
            "home_team_id",
            "home_team",
            "away_team_id",
            "away_team",
        )
        missing = [field for field in required if item.get(field) is None]
        if missing:
            raise ValueError(
                f"Rencontre à venir incomplète : {', '.join(missing)}."
            )
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
    def _update(
        match: dict[str, Any],
        leagues: dict[int, LeagueRollingStats],
        teams: dict[tuple[int, int], TeamRollingStats],
    ) -> None:
        league_id = match["league_id"]
        home_goals = match["home_goals"]
        away_goals = match["away_goals"]
        league = leagues.setdefault(league_id, LeagueRollingStats())
        home = teams.setdefault(
            (league_id, match["home_team_id"]),
            TeamRollingStats(),
        )
        away = teams.setdefault(
            (league_id, match["away_team_id"]),
            TeamRollingStats(),
        )

        league.games += 1
        league.home_goals += home_goals
        league.away_goals += away_goals
        if home_goals > away_goals:
            league.home_wins += 1
        elif home_goals < away_goals:
            league.away_wins += 1
        else:
            league.draws += 1

        home.games += 1
        home.home_games += 1
        home.home_goals_for += home_goals
        home.home_goals_against += away_goals
        away.games += 1
        away.away_games += 1
        away.away_goals_for += away_goals
        away.away_goals_against += home_goals
