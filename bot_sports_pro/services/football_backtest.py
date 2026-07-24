from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot_sports_pro.analyzers.football_poisson import (
    ChronologicalPoissonModel,
    MatchProbabilities,
)
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.storage.json_store import write_json_atomic


@dataclass(frozen=True, slots=True)
class Metrics:
    matches: int
    accuracy_1x2: float
    log_loss_1x2: float
    brier_1x2: float
    baseline_accuracy_1x2: float
    baseline_log_loss_1x2: float
    baseline_brier_1x2: float
    brier_over_1_5: float
    brier_over_2_5: float
    brier_both_teams_score: float


@dataclass(frozen=True, slots=True)
class CompetitionMetrics:
    league_id: int
    name: str
    metrics: Metrics


@dataclass(frozen=True, slots=True)
class FootballBacktestReport:
    season: int
    input_matches: int
    regulation_matches: int
    excluded_non_regulation: int
    warmup_matches: int
    evaluated_matches: int
    metrics: Metrics
    competition_metrics: tuple[CompetitionMetrics, ...]
    predictions_file: Path
    report_file: Path

    def to_text(self) -> str:
        return (
            f"BACKTEST FOOTBALL CHRONOLOGIQUE — SAISON {self.season}\n"
            "====================================================\n"
            f"Matchs lus                    : {self.input_matches}\n"
            f"Matchs temps réglementaire    : {self.regulation_matches}\n"
            f"Matchs AET/PEN exclus         : {self.excluded_non_regulation}\n"
            f"Matchs réservés au démarrage  : {self.warmup_matches}\n"
            f"Prédictions évaluées          : {self.evaluated_matches}\n"
            f"Exactitude 1N2                : {self.metrics.accuracy_1x2:.1%}\n"
            f"Référence championnat         : "
            f"{self.metrics.baseline_accuracy_1x2:.1%}\n"
            f"Log loss 1N2                  : {self.metrics.log_loss_1x2:.4f}\n"
            f"Log loss référence            : "
            f"{self.metrics.baseline_log_loss_1x2:.4f}\n"
            f"Brier 1N2                     : {self.metrics.brier_1x2:.4f}\n"
            f"Brier référence               : "
            f"{self.metrics.baseline_brier_1x2:.4f}\n"
            f"Brier Over 1,5                : {self.metrics.brier_over_1_5:.4f}\n"
            f"Brier Over 2,5                : {self.metrics.brier_over_2_5:.4f}\n"
            f"Brier BTTS                     : {self.metrics.brier_both_teams_score:.4f}\n"
            f"Prédictions auditables        : {self.predictions_file}\n"
            f"Rapport                        : {self.report_file}\n"
            "\nClassements finaux utilisés   : non"
            "\nCotes historiques utilisées   : non"
            "\nRentabilité calculée           : non"
            "\nPronostic réel produit         : non"
        )


def _metrics(predictions: list[MatchProbabilities]) -> Metrics:
    if not predictions:
        raise ValueError("Aucune prédiction ne peut être évaluée.")
    correct = 0
    baseline_correct = 0
    log_loss = 0.0
    baseline_log_loss = 0.0
    brier_1x2 = 0.0
    baseline_brier_1x2 = 0.0
    brier_over_1_5 = 0.0
    brier_over_2_5 = 0.0
    brier_btts = 0.0

    for prediction in predictions:
        probabilities = {
            "home": prediction.home_win,
            "draw": prediction.draw,
            "away": prediction.away_win,
        }
        baseline_probabilities = {
            "home": prediction.baseline_home_win,
            "draw": prediction.baseline_draw,
            "away": prediction.baseline_away_win,
        }
        actual = prediction.actual_outcome
        predicted = max(probabilities, key=probabilities.__getitem__)
        baseline_predicted = max(
            baseline_probabilities,
            key=baseline_probabilities.__getitem__,
        )
        correct += int(predicted == actual)
        baseline_correct += int(baseline_predicted == actual)
        log_loss -= math.log(max(probabilities[actual], 1e-15))
        baseline_log_loss -= math.log(
            max(baseline_probabilities[actual], 1e-15)
        )
        brier_1x2 += sum(
            (probability - float(outcome == actual)) ** 2
            for outcome, probability in probabilities.items()
        )
        baseline_brier_1x2 += sum(
            (probability - float(outcome == actual)) ** 2
            for outcome, probability in baseline_probabilities.items()
        )
        total_goals = prediction.actual_home_goals + prediction.actual_away_goals
        brier_over_1_5 += (
            prediction.over_1_5 - float(total_goals > 1)
        ) ** 2
        brier_over_2_5 += (
            prediction.over_2_5 - float(total_goals > 2)
        ) ** 2
        brier_btts += (
            prediction.both_teams_score
            - float(
                prediction.actual_home_goals > 0
                and prediction.actual_away_goals > 0
            )
        ) ** 2

    count = len(predictions)
    return Metrics(
        matches=count,
        accuracy_1x2=correct / count,
        log_loss_1x2=log_loss / count,
        brier_1x2=brier_1x2 / count,
        baseline_accuracy_1x2=baseline_correct / count,
        baseline_log_loss_1x2=baseline_log_loss / count,
        baseline_brier_1x2=baseline_brier_1x2 / count,
        brier_over_1_5=brier_over_1_5 / count,
        brier_over_2_5=brier_over_2_5 / count,
        brier_both_teams_score=brier_btts / count,
    )


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def run_football_backtest(
    settings: AppSettings,
    season: int,
    min_team_matches: int = 5,
) -> FootballBacktestReport:
    source_file = settings.processed_dir / f"football_training_data_{season}.json"
    if not source_file.exists():
        raise FileNotFoundError(
            f"Base historique absente : {source_file}. "
            "Exécute d'abord collect-training-data."
        )
    with source_file.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("purpose") != "development_and_backtest_only":
        raise ValueError("La base n'est pas étiquetée pour le développement/backtest.")
    if int(document.get("season", -1)) != season:
        raise ValueError("La saison demandée ne correspond pas au fichier chargé.")
    history = document.get("history")
    if not isinstance(history, list):
        raise ValueError("La liste history est absente de la base.")

    competition_names = {
        int(item["league_id"]): str(item["name"])
        for item in document.get("competitions", [])
    }
    model = ChronologicalPoissonModel(min_team_matches=min_team_matches)
    result = model.evaluate(history)
    predictions = list(result.predictions)
    overall_metrics = _metrics(predictions)
    by_competition: list[CompetitionMetrics] = []
    for league_id in sorted({item.league_id for item in predictions}):
        league_predictions = [
            item for item in predictions if item.league_id == league_id
        ]
        by_competition.append(
            CompetitionMetrics(
                league_id=league_id,
                name=competition_names.get(league_id, f"Ligue {league_id}"),
                metrics=_metrics(league_predictions),
            )
        )

    generated_at = datetime.now(UTC).isoformat()
    predictions_file = (
        settings.processed_dir / f"football_backtest_predictions_{season}.json"
    )
    report_file = settings.reports_dir / f"football_backtest_{season}.json"
    write_json_atomic(
        predictions_file,
        {
            "generated_at": generated_at,
            "purpose": "development_and_backtest_only",
            "season": season,
            "model": {
                "name": "chronological_poisson_v1",
                "min_team_matches": min_team_matches,
                "min_league_matches": model.min_league_matches,
                "uses_final_standings": False,
                "uses_historical_odds": False,
            },
            "predictions": [_rounded(asdict(item)) for item in predictions],
        },
    )
    write_json_atomic(
        report_file,
        {
            "generated_at": generated_at,
            "purpose": "development_and_backtest_only",
            "season": season,
            "model": {
                "name": "chronological_poisson_v1",
                "min_team_matches": min_team_matches,
                "min_league_matches": model.min_league_matches,
                "strictly_chronological": True,
                "simultaneous_matches_updated_as_batch": True,
                "uses_final_standings": False,
                "uses_historical_odds": False,
            },
            "coverage": {
                "input_matches": result.input_matches,
                "regulation_matches": result.regulation_matches,
                "excluded_non_regulation": result.excluded_non_regulation,
                "warmup_matches": result.warmup_matches,
                "evaluated_matches": len(predictions),
            },
            "metrics": _rounded(asdict(overall_metrics)),
            "by_competition": [
                _rounded(
                    {
                        "league_id": item.league_id,
                        "name": item.name,
                        "metrics": asdict(item.metrics),
                    }
                )
                for item in by_competition
            ],
            "limitations": [
                "Aucune cote historique : ROI et value non calculables.",
                "Une seule saison : résultat insuffisant pour valider un modèle réel.",
                "Blessures, compositions, météo et actualités absentes.",
            ],
        },
    )
    return FootballBacktestReport(
        season=season,
        input_matches=result.input_matches,
        regulation_matches=result.regulation_matches,
        excluded_non_regulation=result.excluded_non_regulation,
        warmup_matches=result.warmup_matches,
        evaluated_matches=len(predictions),
        metrics=overall_metrics,
        competition_metrics=tuple(by_competition),
        predictions_file=predictions_file,
        report_file=report_file,
    )
