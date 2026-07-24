from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from bot_sports_pro.analyzers.football_ensemble import (
    ChronologicalEnsembleFeatures,
    EnsemblePrediction,
    ProbabilityVector,
    blend_probabilities,
)
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.storage.json_store import write_json_atomic


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    matches: int
    accuracy: float
    log_loss: float
    brier: float


@dataclass(frozen=True, slots=True)
class BlendWeights:
    poisson: float
    elo: float
    recent_form: float


@dataclass(frozen=True, slots=True)
class FootballModelComparisonReport:
    development_season: int
    validation_season: int
    selected_weights: BlendWeights
    development_metrics: dict[str, ModelMetrics]
    validation_metrics: dict[str, ModelMetrics]
    report_file: Path
    config_file: Path

    def to_text(self) -> str:
        development = self.development_metrics
        validation = self.validation_metrics
        return (
            "COMPARAISON MODÈLES FOOTBALL — DÉVELOPPEMENT/VALIDATION\n"
            "======================================================\n"
            f"Saison de développement       : {self.development_season}\n"
            f"Saison de validation          : {self.validation_season}\n"
            f"Poids retenus                 : Poisson "
            f"{self.selected_weights.poisson:.0%} | Elo "
            f"{self.selected_weights.elo:.0%} | Forme "
            f"{self.selected_weights.recent_form:.0%}\n"
            "\nDÉVELOPPEMENT — choix effectué ici uniquement\n"
            f"Référence — log loss          : {development['baseline'].log_loss:.4f}\n"
            f"Poisson — log loss            : {development['poisson'].log_loss:.4f}\n"
            f"Elo — log loss                : {development['elo'].log_loss:.4f}\n"
            f"Forme — log loss              : {development['recent_form'].log_loss:.4f}\n"
            f"Combinaison — log loss        : {development['ensemble'].log_loss:.4f}\n"
            "\nVALIDATION — jamais utilisée pour choisir les poids\n"
            f"Référence — exactitude/log loss: "
            f"{validation['baseline'].accuracy:.1%} / "
            f"{validation['baseline'].log_loss:.4f}\n"
            f"Poisson — exactitude/log loss  : "
            f"{validation['poisson'].accuracy:.1%} / "
            f"{validation['poisson'].log_loss:.4f}\n"
            f"Elo — exactitude/log loss      : "
            f"{validation['elo'].accuracy:.1%} / "
            f"{validation['elo'].log_loss:.4f}\n"
            f"Forme — exactitude/log loss    : "
            f"{validation['recent_form'].accuracy:.1%} / "
            f"{validation['recent_form'].log_loss:.4f}\n"
            f"Combinaison — exactitude/log loss: "
            f"{validation['ensemble'].accuracy:.1%} / "
            f"{validation['ensemble'].log_loss:.4f}\n"
            f"Rapport                        : {self.report_file}\n"
            f"Configuration gelée            : {self.config_file}\n"
            "\nCotes historiques utilisées   : non"
            "\nRentabilité calculée           : non"
            "\nPronostic réel produit         : non"
        )


def calculate_metrics(
    predictions: tuple[EnsemblePrediction, ...],
    probability_getter: Callable[[EnsemblePrediction], ProbabilityVector],
) -> ModelMetrics:
    if not predictions:
        raise ValueError("Aucune prédiction à évaluer.")
    correct = 0
    log_loss = 0.0
    brier = 0.0
    for prediction in predictions:
        probabilities = probability_getter(prediction)
        values = {
            "home": probabilities.home,
            "draw": probabilities.draw,
            "away": probabilities.away,
        }
        actual = prediction.actual_outcome
        correct += int(max(values, key=values.__getitem__) == actual)
        log_loss -= math.log(max(values[actual], 1e-15))
        brier += sum(
            (probability - float(outcome == actual)) ** 2
            for outcome, probability in values.items()
        )
    count = len(predictions)
    return ModelMetrics(
        matches=count,
        accuracy=correct / count,
        log_loss=log_loss / count,
        brier=brier / count,
    )


def select_blend_weights(
    predictions: tuple[EnsemblePrediction, ...],
) -> BlendWeights:
    candidates: list[tuple[float, BlendWeights]] = []
    for poisson_units in range(11):
        for elo_units in range(11 - poisson_units):
            form_units = 10 - poisson_units - elo_units
            weights = BlendWeights(
                poisson=poisson_units / 10.0,
                elo=elo_units / 10.0,
                recent_form=form_units / 10.0,
            )
            metrics = calculate_metrics(
                predictions,
                lambda prediction, weights=weights: blend_probabilities(
                    prediction,
                    weights.poisson,
                    weights.elo,
                    weights.recent_form,
                ),
            )
            candidates.append((metrics.log_loss, weights))
    # En cas d'égalité, le poids Poisson le plus élevé favorise le moteur le
    # plus directement lié aux buts plutôt qu'une combinaison plus complexe.
    return min(
        candidates,
        key=lambda item: (
            item[0],
            -item[1].poisson,
            -item[1].elo,
        ),
    )[1]


def _load_history(settings: AppSettings, season: int) -> tuple[list[dict], dict[int, str]]:
    source = settings.processed_dir / f"football_training_data_{season}.json"
    if not source.exists():
        raise FileNotFoundError(f"Base historique absente : {source}")
    with source.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("purpose") != "development_and_backtest_only":
        raise ValueError(f"Base {season} non autorisée pour le backtest.")
    if int(document.get("season", -1)) != season:
        raise ValueError(f"La saison du fichier ne correspond pas à {season}.")
    history = document.get("history")
    if not isinstance(history, list):
        raise ValueError(f"Historique {season} absent.")
    names = {
        int(item["league_id"]): str(item["name"])
        for item in document.get("competitions", [])
    }
    return history, names


def _all_metrics(
    predictions: tuple[EnsemblePrediction, ...],
    weights: BlendWeights,
) -> dict[str, ModelMetrics]:
    return {
        "baseline": calculate_metrics(predictions, lambda item: item.baseline),
        "poisson": calculate_metrics(predictions, lambda item: item.poisson),
        "elo": calculate_metrics(predictions, lambda item: item.elo),
        "recent_form": calculate_metrics(
            predictions,
            lambda item: item.recent_form,
        ),
        "ensemble": calculate_metrics(
            predictions,
            lambda item: blend_probabilities(
                item,
                weights.poisson,
                weights.elo,
                weights.recent_form,
            ),
        ),
    }


def _by_competition(
    predictions: tuple[EnsemblePrediction, ...],
    names: dict[int, str],
    weights: BlendWeights,
) -> list[dict]:
    rows: list[dict] = []
    for league_id in sorted({item.league_id for item in predictions}):
        league_predictions = tuple(
            item for item in predictions if item.league_id == league_id
        )
        metrics = _all_metrics(league_predictions, weights)
        rows.append(
            {
                "league_id": league_id,
                "name": names.get(league_id, f"Ligue {league_id}"),
                "metrics": {
                    name: asdict(value) for name, value in metrics.items()
                },
            }
        )
    return rows


def compare_football_models(
    settings: AppSettings,
    development_season: int = 2023,
    validation_season: int = 2024,
    min_team_matches: int = 5,
) -> FootballModelComparisonReport:
    if development_season == validation_season:
        raise ValueError("Les saisons de développement et validation doivent différer.")
    development_history, development_names = _load_history(
        settings,
        development_season,
    )
    validation_history, validation_names = _load_history(
        settings,
        validation_season,
    )
    feature_engine = ChronologicalEnsembleFeatures(
        min_team_matches=min_team_matches,
    )
    development_predictions = feature_engine.evaluate(development_history)
    selected_weights = select_blend_weights(development_predictions)
    # Les poids sont désormais figés. La validation n'intervient jamais dans
    # select_blend_weights.
    validation_predictions = feature_engine.evaluate(validation_history)
    development_metrics = _all_metrics(
        development_predictions,
        selected_weights,
    )
    validation_metrics = _all_metrics(
        validation_predictions,
        selected_weights,
    )
    generated_at = datetime.now(UTC).isoformat()
    report_file = settings.reports_dir / (
        f"football_model_comparison_{development_season}_{validation_season}.json"
    )
    config_file = settings.processed_dir / "football_model_config.json"
    configuration = {
        "model_name": "football_ensemble_v1",
        "status": "experimental",
        "locked_using_season": development_season,
        "validated_once_on_season": validation_season,
        "min_team_matches": min_team_matches,
        "min_league_matches": feature_engine.min_league_matches,
        "elo": {
            "k": feature_engine.elo_k,
            "home_advantage": feature_engine.elo_home_advantage,
        },
        "recent_form": {
            "window": feature_engine.form_window,
            "scale": feature_engine.form_scale,
        },
        "weights": asdict(selected_weights),
        "uses_final_standings": False,
        "uses_historical_odds": False,
    }
    write_json_atomic(
        config_file,
        {
            "generated_at": generated_at,
            **configuration,
        },
    )
    write_json_atomic(
        report_file,
        {
            "generated_at": generated_at,
            "purpose": "development_and_backtest_only",
            "configuration": configuration,
            "development": {
                "season": development_season,
                "role": "weight_selection",
                "metrics": {
                    name: asdict(value)
                    for name, value in development_metrics.items()
                },
                "by_competition": _by_competition(
                    development_predictions,
                    development_names,
                    selected_weights,
                ),
            },
            "validation": {
                "season": validation_season,
                "role": "untouched_validation",
                "metrics": {
                    name: asdict(value)
                    for name, value in validation_metrics.items()
                },
                "by_competition": _by_competition(
                    validation_predictions,
                    validation_names,
                    selected_weights,
                ),
            },
            "limitations": [
                "Deux saisons seulement : modèle encore expérimental.",
                "Aucune cote historique : value et ROI non mesurables.",
                "Blessures, compositions, météo et actualités absentes.",
            ],
        },
    )
    return FootballModelComparisonReport(
        development_season=development_season,
        validation_season=validation_season,
        selected_weights=selected_weights,
        development_metrics=development_metrics,
        validation_metrics=validation_metrics,
        report_file=report_file,
        config_file=config_file,
    )
