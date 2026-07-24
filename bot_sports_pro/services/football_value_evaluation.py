from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable

from bot_sports_pro.collectors.the_odds_api import TheOddsApiCatalogCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.config.thresholds import (
    FOOTBALL_OPPORTUNITY_MIN_EXPECTED_ROI,
    FOOTBALL_OPPORTUNITY_PAPER_STAKE,
    FOOTBALL_VALIDATED_MIN_EXPECTED_ROI,
    FOOTBALL_VALIDATED_PAPER_STAKE,
)
from bot_sports_pro.matching.events import (
    MatchDecision,
    match_fixture,
    team_similarity,
)
from bot_sports_pro.services.odds_collection import _normalize_h2h_prices
from bot_sports_pro.services.odds_discovery import (
    discovery_window_utc,
    load_fixtures,
)
from bot_sports_pro.storage.json_store import JsonSnapshotStore, write_json_atomic


CollectorFactory = Callable[[str], TheOddsApiCatalogCollector]
WINAMAX_KEY = "winamax_fr"


@dataclass(frozen=True, slots=True)
class FootballValueReport:
    dates: tuple[date, ...]
    ready_matches: int
    matched_provider_events: int
    unmatched_provider_events: int
    ambiguous_provider_events: int
    relevant_competitions: tuple[str, ...]
    expected_credits: int
    actual_credits: int
    quota_remaining: int | None
    winamax_matches: int
    odds_to_check: int
    validated: int
    opportunities: int
    no_bet: int
    new_paper_bets: int
    existing_paper_bets: int
    output_file: Path
    paper_file: Path
    report_file: Path

    def to_text(self) -> str:
        quota = (
            str(self.quota_remaining)
            if self.quota_remaining is not None
            else "inconnu"
        )
        return (
            "ÉVALUATION VALUE FOOTBALL — WINAMAX, MODE PAPIER\n"
            "================================================\n"
            f"Matchs prêts pour le modèle    : {self.ready_matches}\n"
            f"Événements fournisseur reliés  : {self.matched_provider_events}\n"
            f"Rapprochements ambigus         : {self.ambiguous_provider_events}\n"
            f"Sans correspondance            : {self.unmatched_provider_events}\n"
            f"Compétitions de cotes ciblées  : {len(self.relevant_competitions)}\n"
            f"Crédits prévus                  : {self.expected_credits}\n"
            f"Crédits réellement pris        : {self.actual_credits}\n"
            f"Crédits restants API           : {quota}\n"
            f"Matchs avec cotes Winamax      : {self.winamax_matches}\n"
            f"Cotes Winamax à vérifier       : {self.odds_to_check}\n"
            f"Paris validés papier           : {self.validated}\n"
            f"Opportunités papier            : {self.opportunities}\n"
            f"Aucun pari                     : {self.no_bet}\n"
            f"Nouveaux paris papier          : {self.new_paper_bets}\n"
            f"Paris papier déjà enregistrés  : {self.existing_paper_bets}\n"
            f"Analyse détaillée              : {self.output_file}\n"
            f"Suivi papier                    : {self.paper_file}\n"
            f"Rapport                         : {self.report_file}\n"
            "\nAucun pari réel et aucun message Telegram n'ont été produits."
        )


def _load_document(path: Path, missing_message: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{missing_message} : {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Document JSON invalide : {path}")
    return document


def _analysis_path(settings: AppSettings, dates: tuple[date, ...]) -> Path:
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    return settings.processed_dir / f"football_live_analysis_{batch_name}.json"


def _empty_result(
    settings: AppSettings,
    dates: tuple[date, ...],
    generated_at: str,
) -> FootballValueReport:
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    output_file = (
        settings.processed_dir / f"football_value_evaluation_{batch_name}.json"
    )
    paper_file = settings.processed_dir / "football_paper_bets.json"
    report_file = settings.reports_dir / f"football_value_evaluation_{batch_name}.json"
    if not paper_file.exists():
        write_json_atomic(
            paper_file,
            {
                "purpose": "paper_betting_only",
                "updated_at": generated_at,
                "bets": [],
            },
        )
    document = {
        "generated_at": generated_at,
        "mode": "paper",
        "bookmaker": WINAMAX_KEY,
        "dates": [value.isoformat() for value in dates],
        "ready_matches": 0,
        "catalog_api_calls": 0,
        "odds_api_calls": 0,
        "expected_credits": 0,
        "actual_credits": 0,
        "evaluations": [],
        "paper_bets_added": [],
        "guard": "no_ready_match_no_odds_api_contact",
    }
    write_json_atomic(output_file, document)
    write_json_atomic(report_file, document)
    return FootballValueReport(
        dates=dates,
        ready_matches=0,
        matched_provider_events=0,
        unmatched_provider_events=0,
        ambiguous_provider_events=0,
        relevant_competitions=(),
        expected_credits=0,
        actual_credits=0,
        quota_remaining=None,
        winamax_matches=0,
        odds_to_check=0,
        validated=0,
        opportunities=0,
        no_bet=0,
        new_paper_bets=0,
        existing_paper_bets=0,
        output_file=output_file,
        paper_file=paper_file,
        report_file=report_file,
    )


def _ready_fixtures(
    settings: AppSettings,
    dates: tuple[date, ...],
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fixture_ids = {int(item["fixture_id"]) for item in predictions}
    matches = []
    for event in load_fixtures(settings, dates):
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            continue
        fixture_id = metadata.get("provider_fixture_id")
        if fixture_id is not None and int(fixture_id) in fixture_ids:
            matches.append(event)
    if len(matches) != len(fixture_ids):
        found = {
            int(event["metadata"]["provider_fixture_id"])
            for event in matches
        }
        missing = ", ".join(str(value) for value in sorted(fixture_ids - found))
        raise RuntimeError(
            f"Rencontres prêtes absentes du fichier normalisé : {missing}"
        )
    return matches


def _discover_ready_events(
    fixtures: list[dict[str, Any]],
    collector: TheOddsApiCatalogCollector,
    start: datetime,
    end: datetime,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    list[MatchDecision],
    int,
    list[str],
]:
    sports = collector.fetch_sports()
    soccer_keys = sorted(
        str(sport["key"])
        for sport in sports
        if str(sport.get("group", "")).casefold() == "soccer"
        and sport.get("active") is True
        and sport.get("has_outrights") is not True
        and sport.get("key")
    )
    provider_by_sport: dict[str, list[dict[str, Any]]] = {}
    provider_events: list[dict[str, Any]] = []
    failed_competitions: list[str] = []
    for sport_key in soccer_keys:
        try:
            events = collector.fetch_events(sport_key, start, end)
        except Exception as error:
            failed_competitions.append(f"{sport_key} ({error})")
            continue
        if events:
            provider_by_sport[sport_key] = events
            provider_events.extend(events)
    decisions = [match_fixture(fixture, provider_events) for fixture in fixtures]
    matched_ids = {
        str(decision.odds_event_id)
        for decision in decisions
        if decision.status == "matched" and decision.odds_event_id
    }
    return (
        {
            sport_key: [
                event
                for event in events
                if str(event.get("id")) in matched_ids
            ]
            for sport_key, events in provider_by_sport.items()
            if any(str(event.get("id")) in matched_ids for event in events)
        },
        decisions,
        1 + len(soccer_keys),
        failed_competitions,
    )


def _outcome_key(
    selection: str,
    home_team: str,
    away_team: str,
) -> str | None:
    if selection.casefold().strip() in {"draw", "tie", "nul"}:
        return "draw"
    home_score = team_similarity(selection, home_team)
    away_score = team_similarity(selection, away_team)
    if max(home_score, away_score) < 0.82:
        return None
    if abs(home_score - away_score) < 0.04:
        return None
    return "home" if home_score > away_score else "away"


def evaluate_winamax_prices(
    prediction: dict[str, Any],
    prices: list[dict[str, Any]],
) -> dict[str, Any]:
    ensemble = prediction.get("ensemble")
    if not isinstance(ensemble, dict):
        raise ValueError("Probabilités ensemble absentes d'une prédiction.")
    probability_by_key = {
        key: float(ensemble[key]) for key in ("home", "draw", "away")
    }
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for price in prices:
        key = _outcome_key(
            str(price["selection"]),
            str(prediction["home_team"]),
            str(prediction["away_team"]),
        )
        if key is None or key in seen_keys:
            continue
        seen_keys.add(key)
        decimal_price = float(price["decimal_price"])
        model_probability = probability_by_key[key]
        implied_probability = 1.0 / decimal_price
        expected_roi = model_probability * decimal_price - 1.0
        rows.append(
            {
                "outcome": key,
                "selection": str(price["selection"]),
                "decimal_price": decimal_price,
                "model_probability": model_probability,
                "implied_probability": implied_probability,
                "value_points": model_probability - implied_probability,
                "expected_roi": expected_roi,
                "last_update": price.get("last_update"),
            }
        )
    rows.sort(key=lambda item: item["expected_roi"], reverse=True)
    if not rows:
        return {"status": "ODDS_TO_CHECK", "outcomes": [], "best": None}
    best = rows[0]
    if best["expected_roi"] >= FOOTBALL_VALIDATED_MIN_EXPECTED_ROI:
        status = "VALIDATED"
    elif best["expected_roi"] > FOOTBALL_OPPORTUNITY_MIN_EXPECTED_ROI:
        status = "OPPORTUNITY"
    else:
        status = "NO_BET"
    return {"status": status, "outcomes": rows, "best": best}


def _paper_bet(
    prediction: dict[str, Any],
    fixture: dict[str, Any],
    evaluation: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    best = evaluation["best"]
    status = str(evaluation["status"])
    fixture_event_id = str(fixture["event_id"])
    identity = f"{fixture_event_id}|1n2|{best['outcome']}"
    paper_bet_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return {
        "paper_bet_id": paper_bet_id,
        "created_at": generated_at,
        "mode": "paper",
        "fixture_event_id": fixture_event_id,
        "fixture_id": int(prediction["fixture_id"]),
        "starts_at": prediction["starts_at"],
        "competition": fixture["competition"],
        "home_team": prediction["home_team"],
        "away_team": prediction["away_team"],
        "bookmaker_key": WINAMAX_KEY,
        "market": "1n2",
        "selection_key": best["outcome"],
        "selection": best["selection"],
        "decimal_price": best["decimal_price"],
        "model_probability": best["model_probability"],
        "implied_probability": best["implied_probability"],
        "value_points": best["value_points"],
        "expected_roi": best["expected_roi"],
        "recommendation": status,
        "stake_units": (
            FOOTBALL_VALIDATED_PAPER_STAKE
            if status == "VALIDATED"
            else FOOTBALL_OPPORTUNITY_PAPER_STAKE
        ),
        "included_in_main_performance": status == "VALIDATED",
        "result": "pending",
        "profit_units": None,
    }


def _upsert_paper_bets(
    paper_file: Path,
    candidates: list[dict[str, Any]],
    generated_at: str,
) -> tuple[list[dict[str, Any]], int]:
    if paper_file.exists():
        document = _load_document(paper_file, "Suivi papier absent")
        existing = document.get("bets")
        if not isinstance(existing, list):
            raise ValueError("Le fichier de suivi papier est invalide.")
    else:
        existing = []
    existing_ids = {
        str(item.get("paper_bet_id"))
        for item in existing
        if item.get("paper_bet_id")
    }
    added = [
        candidate
        for candidate in candidates
        if candidate["paper_bet_id"] not in existing_ids
    ]
    write_json_atomic(
        paper_file,
        {
            "purpose": "paper_betting_only",
            "updated_at": generated_at,
            "bets": [*existing, *added],
        },
    )
    return added, len(candidates) - len(added)


def evaluate_live_football_value(
    settings: AppSettings,
    dates: tuple[date, ...],
    max_credits: int,
    collector_factory: CollectorFactory = TheOddsApiCatalogCollector,
) -> FootballValueReport:
    if max_credits < 1:
        raise ValueError("max_credits doit être supérieur ou égal à 1.")
    generated_at = datetime.now(UTC).isoformat()
    analysis = _load_document(
        _analysis_path(settings, dates),
        "Analyse directe absente. Lance analyze-live-football",
    )
    predictions = analysis.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("La liste predictions est absente de l'analyse directe.")
    if not predictions:
        return _empty_result(settings, dates, generated_at)
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_KEY n'est pas configurée dans .env.")

    fixtures = _ready_fixtures(settings, dates, predictions)
    fixture_by_id = {
        int(event["metadata"]["provider_fixture_id"]): event
        for event in fixtures
    }
    prediction_by_event_id = {
        str(fixture_by_id[int(item["fixture_id"])]["event_id"]): item
        for item in predictions
    }
    collector = collector_factory(settings.odds_api_key)
    start, end = discovery_window_utc(dates, settings.timezone)
    (
        relevant_by_sport,
        decisions,
        catalog_api_calls,
        failed_competitions,
    ) = _discover_ready_events(
        fixtures,
        collector,
        start,
        end,
    )
    expected_credits = len(relevant_by_sport)
    if expected_credits > max_credits:
        keys = ", ".join(sorted(relevant_by_sport))
        raise RuntimeError(
            f"Coût prévu {expected_credits} crédits, supérieur au plafond "
            f"{max_credits}. Compétitions : {keys}"
        )

    provider_to_fixture = {
        str(decision.odds_event_id): decision.fixture_event_id
        for decision in decisions
        if decision.status == "matched" and decision.odds_event_id
    }
    raw_store = JsonSnapshotStore(settings.raw_dir / "the_odds_api" / "value")
    payloads: list[tuple[str, list[dict[str, Any]]]] = []
    actual_credits = 0
    quota_remaining: int | None = None
    for sport_key, events in sorted(relevant_by_sport.items()):
        event_ids = tuple(str(event["id"]) for event in events)
        response = collector.fetch_odds(sport_key, event_ids, start, end)
        raw_store.save(f"the-odds-api-value-{sport_key}", response.payload)
        payloads.append((sport_key, response.payload))
        if response.requests_last is not None:
            actual_credits += response.requests_last
        if response.requests_remaining is not None:
            quota_remaining = response.requests_remaining

    prices, rejected, _ = _normalize_h2h_prices(payloads, provider_to_fixture)
    winamax_by_fixture: dict[str, list[dict[str, Any]]] = {}
    for price in prices:
        fixture_event_id = price.get("fixture_event_id")
        if (
            price.get("bookmaker_key") == WINAMAX_KEY
            and isinstance(fixture_event_id, str)
        ):
            winamax_by_fixture.setdefault(fixture_event_id, []).append(price)

    evaluations: list[dict[str, Any]] = []
    paper_candidates: list[dict[str, Any]] = []
    for fixture_event_id, prediction in prediction_by_event_id.items():
        fixture = fixture_by_id[int(prediction["fixture_id"])]
        matching_decision = next(
            (
                decision
                for decision in decisions
                if decision.fixture_event_id == fixture_event_id
            ),
            None,
        )
        if matching_decision is None or matching_decision.status != "matched":
            result = {"status": "ODDS_TO_CHECK", "outcomes": [], "best": None}
        else:
            result = evaluate_winamax_prices(
                prediction,
                winamax_by_fixture.get(fixture_event_id, []),
            )
        row = {
            "fixture_event_id": fixture_event_id,
            "fixture_id": prediction["fixture_id"],
            "starts_at": prediction["starts_at"],
            "competition": fixture["competition"],
            "home_team": prediction["home_team"],
            "away_team": prediction["away_team"],
            "provider_match": (
                asdict(matching_decision) if matching_decision is not None else None
            ),
            **result,
        }
        evaluations.append(row)
        if result["status"] in {"VALIDATED", "OPPORTUNITY"}:
            paper_candidates.append(
                _paper_bet(prediction, fixture, result, generated_at)
            )

    paper_file = settings.processed_dir / "football_paper_bets.json"
    added, existing_count = _upsert_paper_bets(
        paper_file,
        paper_candidates,
        generated_at,
    )
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    output_file = (
        settings.processed_dir / f"football_value_evaluation_{batch_name}.json"
    )
    report_file = settings.reports_dir / f"football_value_evaluation_{batch_name}.json"
    matched = sum(decision.status == "matched" for decision in decisions)
    ambiguous = sum(decision.status == "ambiguous" for decision in decisions)
    unmatched = sum(decision.status == "unmatched" for decision in decisions)
    validated = sum(item["status"] == "VALIDATED" for item in evaluations)
    opportunities = sum(item["status"] == "OPPORTUNITY" for item in evaluations)
    no_bet = sum(item["status"] == "NO_BET" for item in evaluations)
    odds_to_check = sum(item["status"] == "ODDS_TO_CHECK" for item in evaluations)
    winamax_matches = len(evaluations) - odds_to_check
    document = {
        "generated_at": generated_at,
        "mode": "paper",
        "bookmaker": WINAMAX_KEY,
        "dates": [value.isoformat() for value in dates],
        "thresholds": {
            "validated_min_expected_roi": FOOTBALL_VALIDATED_MIN_EXPECTED_ROI,
            "opportunity_min_expected_roi_exclusive": (
                FOOTBALL_OPPORTUNITY_MIN_EXPECTED_ROI
            ),
            "minimum_decimal_price": None,
        },
        "ready_matches": len(predictions),
        "catalog_api_calls": catalog_api_calls,
        "odds_api_calls": len(payloads),
        "expected_credits": expected_credits,
        "actual_credits": actual_credits,
        "quota_remaining": quota_remaining,
        "relevant_competitions": sorted(relevant_by_sport),
        "match_decisions": [asdict(decision) for decision in decisions],
        "failed_competitions": failed_competitions,
        "rejected_prices": rejected,
        "evaluations": evaluations,
        "paper_bets_added": [item["paper_bet_id"] for item in added],
    }
    write_json_atomic(output_file, document)
    write_json_atomic(
        report_file,
        {
            **document,
            "evaluations": [],
            "rejected_prices": rejected,
        },
    )
    return FootballValueReport(
        dates=dates,
        ready_matches=len(predictions),
        matched_provider_events=matched,
        unmatched_provider_events=unmatched,
        ambiguous_provider_events=ambiguous,
        relevant_competitions=tuple(sorted(relevant_by_sport)),
        expected_credits=expected_credits,
        actual_credits=actual_credits,
        quota_remaining=quota_remaining,
        winamax_matches=winamax_matches,
        odds_to_check=odds_to_check,
        validated=validated,
        opportunities=opportunities,
        no_bet=no_bet,
        new_paper_bets=len(added),
        existing_paper_bets=existing_count,
        output_file=output_file,
        paper_file=paper_file,
        report_file=report_file,
    )
