from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from bot_sports_pro.collectors.the_odds_api import TheOddsApiCatalogCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.matching.events import MatchDecision, match_fixture
from bot_sports_pro.services.odds_discovery import (
    discovery_window_utc,
    load_fixtures,
)
from bot_sports_pro.storage.json_store import JsonSnapshotStore


@dataclass(frozen=True, slots=True)
class OddsCollectionReport:
    relevant_competitions: tuple[str, ...]
    expected_credits: int
    actual_credits: int
    quota_remaining: int | None
    requested_events: int
    returned_events: int
    events_with_odds: int
    normalized_prices: int
    rejected_prices: int
    processed_file: Path
    report_file: Path

    def to_text(self) -> str:
        competitions = ", ".join(self.relevant_competitions)
        quota = str(self.quota_remaining) if self.quota_remaining is not None else "inconnu"
        return (
            "COLLECTE COTES FOOTBALL — H2H/1N2 EUROPE\n"
            "========================================\n"
            f"Compétitions interrogées : {len(self.relevant_competitions)}\n"
            f"Clés compétitions        : {competitions}\n"
            f"Crédits prévus           : {self.expected_credits}\n"
            f"Crédits réellement pris  : {self.actual_credits}\n"
            f"Crédits restants API     : {quota}\n"
            f"Événements demandés      : {self.requested_events}\n"
            f"Événements retournés     : {self.returned_events}\n"
            f"Événements avec cotes    : {self.events_with_odds}\n"
            f"Cotes normalisées        : {self.normalized_prices}\n"
            f"Cotes rejetées           : {self.rejected_prices}\n"
            f"Données traitées         : {self.processed_file}\n"
            f"Rapport                   : {self.report_file}\n"
            "\nAucun filtre de cote et aucun pronostic n'ont été appliqués."
        )


def _discover_relevant_events(
    settings: AppSettings,
    dates: tuple[date, ...],
    collector: TheOddsApiCatalogCollector,
) -> tuple[dict[str, list[dict]], list[MatchDecision]]:
    fixtures = load_fixtures(settings, dates)
    start, end = discovery_window_utc(dates, settings.timezone)
    sports = collector.fetch_sports()
    soccer_sports = sorted(
        (
            sport
            for sport in sports
            if str(sport.get("group", "")).casefold() == "soccer"
            and sport.get("active") is True
            and sport.get("has_outrights") is not True
            and sport.get("key")
        ),
        key=lambda sport: str(sport["key"]),
    )
    provider_by_sport: dict[str, list[dict]] = {}
    all_provider_events: list[dict] = []
    for sport in soccer_sports:
        sport_key = str(sport["key"])
        events = collector.fetch_events(sport_key, start, end)
        if events:
            provider_by_sport[sport_key] = events
            all_provider_events.extend(events)

    decisions = [match_fixture(fixture, all_provider_events) for fixture in fixtures]
    matched_ids = {
        decision.odds_event_id
        for decision in decisions
        if decision.status == "matched" and decision.odds_event_id
    }
    relevant_by_sport = {
        sport_key: [event for event in events if str(event.get("id")) in matched_ids]
        for sport_key, events in provider_by_sport.items()
    }
    return (
        {
            sport_key: events
            for sport_key, events in relevant_by_sport.items()
            if events
        },
        decisions,
    )


def _normalize_h2h_prices(
    payloads: list[tuple[str, list[dict]]],
    provider_to_fixture: dict[str, str],
) -> tuple[list[dict], list[str], set[str]]:
    normalized: list[dict] = []
    rejected: list[str] = []
    events_with_odds: set[str] = set()

    for sport_key, events in payloads:
        for event in events:
            event_id = str(event.get("id", ""))
            if not event_id:
                rejected.append(f"{sport_key}: événement sans identifiant")
                continue
            for bookmaker in event.get("bookmakers", []):
                bookmaker_key = str(bookmaker.get("key", ""))
                bookmaker_title = str(bookmaker.get("title", bookmaker_key))
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        try:
                            price = float(outcome["price"])
                            name = str(outcome["name"])
                            if price <= 1.0:
                                raise ValueError("cote inférieure ou égale à 1")
                        except (KeyError, TypeError, ValueError) as error:
                            rejected.append(
                                f"{sport_key}/{event_id}/{bookmaker_key}: {error}"
                            )
                            continue
                        normalized.append(
                            {
                                "fixture_event_id": provider_to_fixture.get(event_id),
                                "provider_event_id": event_id,
                                "sport_key": sport_key,
                                "commence_time": event.get("commence_time"),
                                "home_team": event.get("home_team"),
                                "away_team": event.get("away_team"),
                                "bookmaker_key": bookmaker_key,
                                "bookmaker": bookmaker_title,
                                "market": "h2h",
                                "selection": name,
                                "decimal_price": price,
                                "last_update": market.get(
                                    "last_update", bookmaker.get("last_update")
                                ),
                            }
                        )
                        events_with_odds.add(event_id)
    return normalized, rejected, events_with_odds


def collect_football_odds(
    settings: AppSettings,
    dates: tuple[date, ...],
    max_credits: int,
) -> OddsCollectionReport:
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_KEY n'est pas configurée dans .env.")
    if max_credits < 1:
        raise ValueError("max_credits doit être supérieur ou égal à 1.")

    collector = TheOddsApiCatalogCollector(settings.odds_api_key)
    relevant_by_sport, decisions = _discover_relevant_events(settings, dates, collector)
    expected_credits = len(relevant_by_sport)
    if expected_credits == 0:
        raise RuntimeError("Aucune compétition avec événement rapproché.")
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
    start, end = discovery_window_utc(dates, settings.timezone)
    raw_store = JsonSnapshotStore(settings.raw_dir / "the_odds_api" / "odds")
    payloads: list[tuple[str, list[dict]]] = []
    actual_credits = 0
    quota_remaining: int | None = None

    for sport_key, events in sorted(relevant_by_sport.items()):
        event_ids = tuple(str(event["id"]) for event in events)
        response = collector.fetch_odds(sport_key, event_ids, start, end)
        raw_store.save(f"the-odds-api-h2h-{sport_key}", response.payload)
        payloads.append((sport_key, response.payload))
        if response.requests_last is not None:
            actual_credits += response.requests_last
        quota_remaining = (
            response.requests_remaining
            if response.requests_remaining is not None
            else quota_remaining
        )

    normalized, rejected, events_with_odds = _normalize_h2h_prices(
        payloads, provider_to_fixture
    )
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    processed_file = settings.processed_dir / f"football_odds_h2h_{batch_name}.json"
    processed_file.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "region": "eu",
                "market": "h2h",
                "prices": normalized,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_file = settings.reports_dir / f"odds_collection_{batch_name}.json"
    report_file.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "relevant_competitions": sorted(relevant_by_sport),
                "expected_credits": expected_credits,
                "actual_credits": actual_credits,
                "quota_remaining": quota_remaining,
                "requested_event_ids": sorted(provider_to_fixture),
                "returned_event_count": sum(len(events) for _, events in payloads),
                "events_with_odds": sorted(events_with_odds),
                "normalized_price_count": len(normalized),
                "rejections": rejected,
                "match_decisions": [asdict(decision) for decision in decisions],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return OddsCollectionReport(
        relevant_competitions=tuple(sorted(relevant_by_sport)),
        expected_credits=expected_credits,
        actual_credits=actual_credits,
        quota_remaining=quota_remaining,
        requested_events=len(provider_to_fixture),
        returned_events=sum(len(events) for _, events in payloads),
        events_with_odds=len(events_with_odds),
        normalized_prices=len(normalized),
        rejected_prices=len(rejected),
        processed_file=processed_file,
        report_file=report_file,
    )
