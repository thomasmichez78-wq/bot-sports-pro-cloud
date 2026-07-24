from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from bot_sports_pro.collectors.api_football import ApiFootballFixturesCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.services.odds_discovery import load_fixtures
from bot_sports_pro.storage.json_store import JsonSnapshotStore, write_json_atomic


COMPLETED_STATUSES = {"FT", "AET", "PEN"}


@dataclass(frozen=True, slots=True)
class CompetitionSpec:
    league_id: int
    season: int
    name: str

    @property
    def cache_key(self) -> str:
        return f"{self.league_id}_{self.season}"


@dataclass(frozen=True, slots=True)
class FootballSportsDataReport:
    target_events: int
    competitions: int
    expected_requests: int
    api_requests: int
    cache_hits: int
    history_fixtures: int
    target_teams: int
    teams_with_five_matches: int
    standings_rows: int
    standings_unavailable: int
    errors: tuple[str, ...]
    processed_file: Path
    report_file: Path

    def to_text(self) -> str:
        errors = "aucune" if not self.errors else " | ".join(self.errors)
        return (
            "COLLECTE DONNÉES SPORTIVES FOOTBALL\n"
            "===================================\n"
            f"Matchs cibles                 : {self.target_events}\n"
            f"Compétitions                 : {self.competitions}\n"
            f"Requêtes maximales prévues   : {self.expected_requests}\n"
            f"Requêtes API réellement faites: {self.api_requests}\n"
            f"Réponses servies par le cache: {self.cache_hits}\n"
            f"Matchs historiques terminés  : {self.history_fixtures}\n"
            f"Équipes cibles               : {self.target_teams}\n"
            f"Équipes avec au moins 5 matchs: {self.teams_with_five_matches}\n"
            f"Lignes de classement         : {self.standings_rows}\n"
            f"Classements indisponibles    : {self.standings_unavailable}\n"
            f"Erreurs                      : {errors}\n"
            f"Données traitées             : {self.processed_file}\n"
            f"Rapport                      : {self.report_file}\n"
            "\nAucune probabilité et aucun pronostic n'ont été calculés."
        )


def load_target_context(
    settings: AppSettings,
    dates: tuple[date, ...],
) -> tuple[list[dict], list[CompetitionSpec]]:
    fixtures = load_fixtures(settings, dates)
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    odds_file = settings.processed_dir / f"football_odds_h2h_{batch_name}.json"
    if not odds_file.exists():
        raise RuntimeError(
            f"Cotes normalisées introuvables : {odds_file}. "
            "Lance d'abord collect-odds-football."
        )
    odds_document = json.loads(odds_file.read_text(encoding="utf-8"))
    target_fixture_ids = {
        str(row["fixture_event_id"])
        for row in odds_document.get("prices", [])
        if row.get("fixture_event_id")
    }
    target_events = [
        event for event in fixtures if str(event.get("event_id")) in target_fixture_ids
    ]
    if len(target_events) != len(target_fixture_ids):
        raise RuntimeError(
            "Certaines rencontres de cotes ne sont plus présentes dans la collecte football."
        )

    competition_map: dict[tuple[int, int], CompetitionSpec] = {}
    for event in target_events:
        metadata = event.get("metadata", {})
        required = (
            "provider_league_id",
            "season",
            "home_team_id",
            "away_team_id",
        )
        if any(metadata.get(key) is None for key in required):
            raise RuntimeError(
                "Les identifiants d'équipes sont absents. "
                "Relance collect-football avec la version 0.5.0."
            )
        league_id = int(metadata["provider_league_id"])
        season = int(metadata["season"])
        competition_map[(league_id, season)] = CompetitionSpec(
            league_id=league_id,
            season=season,
            name=str(event["competition"]),
        )
    return target_events, sorted(
        competition_map.values(),
        key=lambda competition: (competition.league_id, competition.season),
    )


def _load_or_fetch(
    cache_file: Path,
    fetcher: Callable[[], dict[str, Any]],
    raw_store: JsonSnapshotStore,
    source_name: str,
) -> tuple[dict[str, Any], bool]:
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8")), True
    payload = fetcher()
    raw_store.save(source_name, payload)
    write_json_atomic(cache_file, payload)
    return payload, False


def normalize_history(payload: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in payload.get("response", []):
        try:
            fixture = item["fixture"]
            league = item["league"]
            teams = item["teams"]
            goals = item["goals"]
            status = str(fixture["status"]["short"])
            if status not in COMPLETED_STATUSES:
                continue
            home_goals = goals.get("home")
            away_goals = goals.get("away")
            if home_goals is None or away_goals is None:
                continue
            normalized.append(
                {
                    "fixture_id": int(fixture["id"]),
                    "starts_at": str(fixture["date"]),
                    "status": status,
                    "league_id": int(league["id"]),
                    "season": int(league["season"]),
                    "round": league.get("round"),
                    "home_team_id": int(teams["home"]["id"]),
                    "home_team": str(teams["home"]["name"]),
                    "away_team_id": int(teams["away"]["id"]),
                    "away_team": str(teams["away"]["name"]),
                    "home_goals": int(home_goals),
                    "away_goals": int(away_goals),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return normalized


def normalize_standings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for response_item in payload.get("response", []):
        league = response_item.get("league", {})
        for group in league.get("standings", []):
            for row in group:
                try:
                    normalized.append(
                        {
                            "league_id": int(league["id"]),
                            "season": int(league["season"]),
                            "group": row.get("group"),
                            "rank": int(row["rank"]),
                            "team_id": int(row["team"]["id"]),
                            "team": str(row["team"]["name"]),
                            "points": int(row["points"]),
                            "goals_difference": int(row["goalsDiff"]),
                            "form": row.get("form"),
                            "all": row.get("all"),
                            "home": row.get("home"),
                            "away": row.get("away"),
                            "updated_at": row.get("update"),
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
    return normalized


def collect_football_sports_data(
    settings: AppSettings,
    dates: tuple[date, ...],
    history_days: int,
    max_requests: int,
) -> FootballSportsDataReport:
    if not settings.api_football_key:
        raise RuntimeError("API_FOOTBALL_KEY n'est pas configurée dans .env.")
    if not 30 <= history_days <= 365:
        raise ValueError("history_days doit être compris entre 30 et 365.")
    if max_requests < 1:
        raise ValueError("max_requests doit être supérieur ou égal à 1.")

    target_events, competitions = load_target_context(settings, dates)
    expected_requests = len(competitions) * 2
    if expected_requests > max_requests:
        raise RuntimeError(
            f"Coût maximal prévu {expected_requests} requêtes, supérieur au plafond "
            f"{max_requests}."
        )

    collector = ApiFootballFixturesCollector(settings.api_football_key)
    today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    cache_dir = settings.cache_dir / "api_football" / today
    raw_store = JsonSnapshotStore(settings.raw_dir / "api_football" / "sports_data")
    history_from = dates[0] - timedelta(days=history_days)
    history_to = dates[0] - timedelta(days=1)
    api_requests = 0
    cache_hits = 0
    errors: list[str] = []
    all_history: list[dict[str, Any]] = []
    all_standings: list[dict[str, Any]] = []
    standings_unavailable = 0

    for competition in competitions:
        history_cache = cache_dir / (
            f"history_{competition.cache_key}_{history_from}_{history_to}.json"
        )
        history_was_cached = history_cache.exists()
        try:
            history_payload, cached = _load_or_fetch(
                history_cache,
                lambda competition=competition: collector.fetch_history(
                    competition.league_id,
                    competition.season,
                    history_from,
                    history_to,
                ),
                raw_store,
                f"history-{competition.cache_key}",
            )
            cache_hits += int(cached)
            api_requests += int(not cached)
            all_history.extend(normalize_history(history_payload))
        except Exception as error:
            api_requests += int(not history_was_cached)
            errors.append(f"Historique {competition.name}: {error}")

        standings_cache = cache_dir / f"standings_{competition.cache_key}.json"
        standings_was_cached = standings_cache.exists()
        try:
            standings_payload, cached = _load_or_fetch(
                standings_cache,
                lambda competition=competition: collector.fetch_standings(
                    competition.league_id,
                    competition.season,
                ),
                raw_store,
                f"standings-{competition.cache_key}",
            )
            cache_hits += int(cached)
            api_requests += int(not cached)
            rows = normalize_standings(standings_payload)
            if not rows:
                standings_unavailable += 1
            all_standings.extend(rows)
        except Exception as error:
            api_requests += int(not standings_was_cached)
            standings_unavailable += 1
            errors.append(f"Classement {competition.name}: {error}")

    target_team_ids = {
        int(event["metadata"][key])
        for event in target_events
        for key in ("home_team_id", "away_team_id")
    }
    appearances: Counter[int] = Counter()
    for fixture in all_history:
        appearances[fixture["home_team_id"]] += 1
        appearances[fixture["away_team_id"]] += 1
    teams_with_five_matches = sum(
        appearances[team_id] >= 5 for team_id in target_team_ids
    )

    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    processed_file = settings.processed_dir / f"football_sports_data_{batch_name}.json"
    processed_document = {
        "generated_at": datetime.now(UTC).isoformat(),
        "history_window": {
            "from": history_from.isoformat(),
            "to": history_to.isoformat(),
        },
        "target_events": target_events,
        "competitions": [
            {
                "league_id": competition.league_id,
                "season": competition.season,
                "name": competition.name,
            }
            for competition in competitions
        ],
        "history": all_history,
        "standings": all_standings,
    }
    write_json_atomic(processed_file, processed_document)

    report_file = settings.reports_dir / f"football_sports_data_{batch_name}.json"
    write_json_atomic(
        report_file,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "target_event_count": len(target_events),
            "competition_count": len(competitions),
            "expected_requests": expected_requests,
            "api_requests": api_requests,
            "cache_hits": cache_hits,
            "history_fixture_count": len(all_history),
            "target_team_count": len(target_team_ids),
            "teams_with_five_matches": teams_with_five_matches,
            "standings_row_count": len(all_standings),
            "standings_unavailable": standings_unavailable,
            "errors": errors,
        },
    )
    return FootballSportsDataReport(
        target_events=len(target_events),
        competitions=len(competitions),
        expected_requests=expected_requests,
        api_requests=api_requests,
        cache_hits=cache_hits,
        history_fixtures=len(all_history),
        target_teams=len(target_team_ids),
        teams_with_five_matches=teams_with_five_matches,
        standings_rows=len(all_standings),
        standings_unavailable=standings_unavailable,
        errors=tuple(errors),
        processed_file=processed_file,
        report_file=report_file,
    )
