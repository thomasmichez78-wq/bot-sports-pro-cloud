from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot_sports_pro.collectors.the_odds_api import TheOddsApiCatalogCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.matching.events import MatchDecision, match_fixture
from bot_sports_pro.storage.json_store import JsonSnapshotStore


@dataclass(frozen=True, slots=True)
class OddsDiscoveryReport:
    active_competitions: int
    provider_events: int
    fixtures: int
    matched: int
    ambiguous: int
    unmatched: int
    provider_matched: int
    provider_unmatched: int
    failed_competitions: tuple[str, ...]
    report_file: Path

    def to_text(self) -> str:
        failures = (
            ", ".join(self.failed_competitions) if self.failed_competitions else "aucune"
        )
        fixture_coverage = (self.matched / self.fixtures * 100) if self.fixtures else 0.0
        provider_coverage = (
            (self.provider_matched / self.provider_events * 100)
            if self.provider_events
            else 0.0
        )
        return (
            "DÉCOUVERTE COTES FOOTBALL — SANS CRÉDIT DE COTES\n"
            "================================================\n"
            f"Compétitions football actives : {self.active_competitions}\n"
            f"Événements fournisseur        : {self.provider_events}\n"
            f"Rencontres API-Football       : {self.fixtures}\n"
            f"Rapprochements validés        : {self.matched}\n"
            f"Rapprochements ambigus        : {self.ambiguous}\n"
            f"Sans correspondance           : {self.unmatched}\n"
            f"Couverture univers brut        : {fixture_coverage:.1f}%\n"
            f"Événements fournisseur reliés  : {self.provider_matched}\n"
            f"Événements fournisseur orphelins: {self.provider_unmatched}\n"
            f"Couverture fournisseur         : {provider_coverage:.1f}%\n"
            f"Compétitions en erreur         : {failures}\n"
            f"Rapport                        : {self.report_file}\n"
            "\nAucune cote payante et aucun pronostic n'ont été demandés."
        )


def load_fixtures(settings: AppSettings, dates: tuple[date, ...]) -> list[dict]:
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    path = settings.processed_dir / f"football_fixtures_{batch_name}.json"
    if not path.exists():
        raise RuntimeError(
            f"Collecte introuvable : {path}. Lance d'abord collect-football avec les mêmes dates."
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    events = document.get("events")
    if not isinstance(events, list):
        raise RuntimeError("Le fichier de rencontres normalisées est invalide.")
    return events


def discovery_window_utc(
    dates: tuple[date, ...],
    timezone_name: str,
) -> tuple[datetime, datetime]:
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise RuntimeError(f"Fuseau horaire inconnu : {timezone_name}") from error

    local_start = datetime.combine(dates[0], time.min, tzinfo=local_timezone)
    local_end_exclusive = datetime.combine(
        dates[-1] + timedelta(days=1),
        time.min,
        tzinfo=local_timezone,
    )
    return (
        local_start.astimezone(UTC),
        local_end_exclusive.astimezone(UTC) - timedelta(seconds=1),
    )


def discover_odds_football(
    settings: AppSettings,
    dates: tuple[date, ...],
) -> OddsDiscoveryReport:
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_KEY n'est pas configurée dans .env.")

    fixtures = load_fixtures(settings, dates)
    collector = TheOddsApiCatalogCollector(settings.odds_api_key)
    raw_store = JsonSnapshotStore(settings.raw_dir / "the_odds_api" / "discovery")

    sports = collector.fetch_sports()
    raw_store.save("the-odds-api-sports", sports)
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

    start, end = discovery_window_utc(dates, settings.timezone)
    provider_events: list[dict] = []
    failed_competitions: list[str] = []

    for sport in soccer_sports:
        sport_key = str(sport["key"])
        try:
            events = collector.fetch_events(sport_key, start, end)
        except Exception as error:
            failed_competitions.append(f"{sport_key} ({error})")
            continue
        raw_store.save(f"the-odds-api-events-{sport_key}", events)
        provider_events.extend(events)

    unique_provider_events = {
        str(event["id"]): event for event in provider_events if event.get("id")
    }
    decisions: list[MatchDecision] = [
        match_fixture(fixture, list(unique_provider_events.values())) for fixture in fixtures
    ]
    matched = sum(decision.status == "matched" for decision in decisions)
    ambiguous = sum(decision.status == "ambiguous" for decision in decisions)
    unmatched = sum(decision.status == "unmatched" for decision in decisions)
    matched_provider_ids = {
        decision.odds_event_id
        for decision in decisions
        if decision.status == "matched" and decision.odds_event_id
    }
    unmatched_provider_events = [
        {
            "id": event_id,
            "sport_key": event.get("sport_key"),
            "sport_title": event.get("sport_title"),
            "commence_time": event.get("commence_time"),
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
        }
        for event_id, event in sorted(unique_provider_events.items())
        if event_id not in matched_provider_ids
    ]
    matched_provider_events = [
        {
            "id": event_id,
            "sport_key": event.get("sport_key"),
            "sport_title": event.get("sport_title"),
            "commence_time": event.get("commence_time"),
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
        }
        for event_id, event in sorted(unique_provider_events.items())
        if event_id in matched_provider_ids
    ]

    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    report_file = settings.reports_dir / f"odds_discovery_{batch_name}.json"
    report_document = {
        "generated_at": datetime.now(UTC).isoformat(),
        "active_competitions": [
            {
                "key": sport["key"],
                "title": sport.get("title"),
                "description": sport.get("description"),
            }
            for sport in soccer_sports
        ],
        "provider_event_count": len(unique_provider_events),
        "provider_matched_count": len(matched_provider_ids),
        "provider_unmatched_count": len(unmatched_provider_events),
        "fixture_count": len(fixtures),
        "decisions": [asdict(decision) for decision in decisions],
        "matched_provider_events": matched_provider_events,
        "unmatched_provider_events": unmatched_provider_events,
        "failed_competitions": failed_competitions,
    }
    report_file.write_text(
        json.dumps(report_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return OddsDiscoveryReport(
        active_competitions=len(soccer_sports),
        provider_events=len(unique_provider_events),
        fixtures=len(fixtures),
        matched=matched,
        ambiguous=ambiguous,
        unmatched=unmatched,
        provider_matched=len(matched_provider_ids),
        provider_unmatched=len(unmatched_provider_events),
        failed_competitions=tuple(failed_competitions),
        report_file=report_file,
    )
