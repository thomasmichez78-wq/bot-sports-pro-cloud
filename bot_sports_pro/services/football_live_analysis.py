from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from bot_sports_pro.analyzers.football_ensemble import (
    ChronologicalEnsembleFeatures,
)
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.services.odds_discovery import load_fixtures
from bot_sports_pro.storage.json_store import write_json_atomic


UPCOMING_STATUSES = {"NS", "TBD"}


@dataclass(frozen=True, slots=True)
class FixtureReadiness:
    event_id: str
    fixture_id: int | None
    starts_at: str
    competition: str
    league_id: int | None
    home_team: str
    away_team: str
    home_history: int
    away_history: int
    league_history: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FootballLiveAnalysisReport:
    dates: tuple[date, ...]
    fixtures_loaded: int
    target_upcoming: int
    ready_matches: int
    insufficient_matches: int
    invalid_matches: int
    live_history_matches: int
    collected_history_dates: int
    model_name: str
    output_file: Path
    report_file: Path

    def to_text(self) -> str:
        start = self.dates[0].isoformat()
        end = self.dates[-1].isoformat()
        return (
            "ANALYSE FOOTBALL DIRECTE — PROBABILITÉS SANS COTES\n"
            "==================================================\n"
            f"Période analysée               : {start} au {end}\n"
            f"Rencontres chargées            : {self.fixtures_loaded}\n"
            f"Rencontres cibles à venir      : {self.target_upcoming}\n"
            f"Matchs prêts pour le modèle    : {self.ready_matches}\n"
            f"Historique insuffisant         : {self.insufficient_matches}\n"
            f"Rencontres techniquement invalides: {self.invalid_matches}\n"
            f"Matchs dans l'historique direct: {self.live_history_matches}\n"
            f"Journées historiques archivées : {self.collected_history_dates}\n"
            f"Modèle chargé                  : {self.model_name}\n"
            "Crédits de cotes consommés     : 0\n"
            f"Analyse détaillée              : {self.output_file}\n"
            f"Rapport                         : {self.report_file}\n"
            "\nAucune value, aucun pari et aucun message Telegram n'ont été produits."
        )


def _load_json(path: Path, missing_message: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{missing_message} : {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Document JSON invalide : {path}")
    return document


def _fixture_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return None
    required = (
        "provider_fixture_id",
        "provider_league_id",
        "home_team_id",
        "away_team_id",
    )
    if any(metadata.get(key) is None for key in required):
        return None
    return {
        "event_id": str(event["event_id"]),
        "fixture_id": int(metadata["provider_fixture_id"]),
        "starts_at": str(event["starts_at"]),
        "league_id": int(metadata["provider_league_id"]),
        "home_team_id": int(metadata["home_team_id"]),
        "home_team": str(event["home_name"]),
        "away_team_id": int(metadata["away_team_id"]),
        "away_team": str(event["away_name"]),
        "competition": str(event["competition"]),
        "status": str(metadata.get("status", "")),
    }


def assess_fixture_readiness(
    event: dict[str, Any],
    team_matches: Counter[tuple[int, int]],
    league_matches: Counter[int],
    min_team_matches: int,
    min_league_matches: int,
) -> FixtureReadiness:
    fixture = _fixture_from_event(event)
    if fixture is None:
        return FixtureReadiness(
            event_id=str(event.get("event_id", "")),
            fixture_id=None,
            starts_at=str(event.get("starts_at", "")),
            competition=str(event.get("competition", "")),
            league_id=None,
            home_team=str(event.get("home_name", "")),
            away_team=str(event.get("away_name", "")),
            home_history=0,
            away_history=0,
            league_history=0,
            reasons=("missing_team_or_league_identifiers",),
        )
    league_id = fixture["league_id"]
    home_history = team_matches[(league_id, fixture["home_team_id"])]
    away_history = team_matches[(league_id, fixture["away_team_id"])]
    league_history = league_matches[league_id]
    reasons: list[str] = []
    if league_history < min_league_matches:
        reasons.append(
            f"league_history_{league_history}_below_{min_league_matches}"
        )
    if home_history < min_team_matches:
        reasons.append(
            f"home_history_{home_history}_below_{min_team_matches}"
        )
    if away_history < min_team_matches:
        reasons.append(
            f"away_history_{away_history}_below_{min_team_matches}"
        )
    return FixtureReadiness(
        event_id=fixture["event_id"],
        fixture_id=fixture["fixture_id"],
        starts_at=fixture["starts_at"],
        competition=fixture["competition"],
        league_id=league_id,
        home_team=fixture["home_team"],
        away_team=fixture["away_team"],
        home_history=home_history,
        away_history=away_history,
        league_history=league_history,
        reasons=tuple(reasons),
    )


def analyze_live_football(
    settings: AppSettings,
    dates: tuple[date, ...],
) -> FootballLiveAnalysisReport:
    live_file = settings.processed_dir / "football_live_history.json"
    config_file = settings.processed_dir / "football_model_config.json"
    live_document = _load_json(
        live_file,
        "Historique direct absent. Attends la collecte quotidienne",
    )
    config = _load_json(
        config_file,
        "Configuration du modèle absente. Lance compare-football-models",
    )
    if live_document.get("purpose") != "prospective_live_model_history":
        raise ValueError("L'historique chargé n'est pas une base directe.")
    if config.get("status") != "experimental":
        raise ValueError("Le statut du modèle chargé est inattendu.")
    history = live_document.get("history")
    if not isinstance(history, list):
        raise ValueError("La liste history est absente de la base directe.")
    fixtures = load_fixtures(settings, dates)
    target_league_ids = {
        int(item["league_id"])
        for item in live_document.get("competitions", [])
    }
    min_team_matches = int(config["min_team_matches"])
    min_league_matches = int(config["min_league_matches"])
    weights = config.get("weights", {})

    regulation_history = [
        item for item in history if item.get("status") == "FT"
    ]
    team_matches: Counter[tuple[int, int]] = Counter()
    league_matches: Counter[int] = Counter()
    for match in regulation_history:
        league_id = int(match["league_id"])
        league_matches[league_id] += 1
        team_matches[(league_id, int(match["home_team_id"]))] += 1
        team_matches[(league_id, int(match["away_team_id"]))] += 1

    target_events: list[dict[str, Any]] = []
    invalid_events: list[dict[str, Any]] = []
    for event in fixtures:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("status", "")) not in UPCOMING_STATUSES:
            continue
        league_id = metadata.get("provider_league_id")
        if league_id is None or int(league_id) not in target_league_ids:
            continue
        if _fixture_from_event(event) is None:
            invalid_events.append(event)
        else:
            target_events.append(event)

    readiness = [
        assess_fixture_readiness(
            event,
            team_matches,
            league_matches,
            min_team_matches,
            min_league_matches,
        )
        for event in target_events
    ]
    ready_ids = {
        item.fixture_id
        for item in readiness
        if not item.reasons and item.fixture_id is not None
    }
    ready_fixtures = [
        fixture
        for event in target_events
        if (fixture := _fixture_from_event(event)) is not None
        and fixture["fixture_id"] in ready_ids
    ]
    feature_engine = ChronologicalEnsembleFeatures(
        min_team_matches=min_team_matches,
        min_league_matches=min_league_matches,
        elo_k=float(config["elo"]["k"]),
        elo_home_advantage=float(config["elo"]["home_advantage"]),
        form_window=int(config["recent_form"]["window"]),
        form_scale=float(config["recent_form"]["scale"]),
    )
    predictions = feature_engine.predict_upcoming(
        regulation_history,
        ready_fixtures,
        poisson_weight=float(weights["poisson"]),
        elo_weight=float(weights["elo"]),
        form_weight=float(weights["recent_form"]),
    )
    if len(predictions) != len(ready_fixtures):
        raise RuntimeError(
            "Le moteur n'a pas produit toutes les probabilités attendues."
        )

    prediction_rows: list[dict[str, Any]] = []
    for prediction in predictions:
        probabilities = {
            "home": prediction.ensemble.home,
            "draw": prediction.ensemble.draw,
            "away": prediction.ensemble.away,
        }
        prediction_rows.append(
            {
                **asdict(prediction),
                "leading_outcome": max(
                    probabilities,
                    key=probabilities.__getitem__,
                ),
                "status": "MODEL_PROBABILITY_ONLY",
            }
        )
    insufficient_rows = [
        asdict(item)
        for item in readiness
        if item.reasons
    ]
    invalid_rows = [
        asdict(
            assess_fixture_readiness(
                event,
                team_matches,
                league_matches,
                min_team_matches,
                min_league_matches,
            )
        )
        for event in invalid_events
    ]
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    output_file = (
        settings.processed_dir / f"football_live_analysis_{batch_name}.json"
    )
    report_file = (
        settings.reports_dir / f"football_live_analysis_{batch_name}.json"
    )
    generated_at = datetime.now(UTC).isoformat()
    write_json_atomic(
        output_file,
        {
            "generated_at": generated_at,
            "purpose": "live_probability_analysis_only",
            "dates": [value.isoformat() for value in dates],
            "model": {
                "name": config["model_name"],
                "status": config["status"],
                "weights": weights,
                "min_team_matches": min_team_matches,
                "min_league_matches": min_league_matches,
            },
            "predictions": prediction_rows,
            "insufficient_history": insufficient_rows,
            "invalid_fixtures": invalid_rows,
            "odds_api_calls": 0,
            "bet_selections": [],
        },
    )
    report_document = {
        "generated_at": generated_at,
        "fixtures_loaded": len(fixtures),
        "target_upcoming": len(target_events) + len(invalid_events),
        "ready_matches": len(predictions),
        "insufficient_matches": len(insufficient_rows),
        "invalid_matches": len(invalid_rows),
        "live_history_matches": len(regulation_history),
        "collected_history_dates": len(
            live_document.get("dates_collected", [])
        ),
        "model_name": config["model_name"],
        "odds_api_calls": 0,
    }
    write_json_atomic(report_file, report_document)
    return FootballLiveAnalysisReport(
        dates=dates,
        fixtures_loaded=len(fixtures),
        target_upcoming=len(target_events) + len(invalid_events),
        ready_matches=len(predictions),
        insufficient_matches=len(insufficient_rows),
        invalid_matches=len(invalid_rows),
        live_history_matches=len(regulation_history),
        collected_history_dates=len(live_document.get("dates_collected", [])),
        model_name=str(config["model_name"]),
        output_file=output_file,
        report_file=report_file,
    )
