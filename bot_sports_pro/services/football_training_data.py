from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from bot_sports_pro.collectors.api_football import ApiFootballFixturesCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.services.football_sports_data import (
    CompetitionSpec,
    _load_or_fetch,
    load_target_context,
    normalize_history,
    normalize_standings,
)
from bot_sports_pro.storage.json_store import JsonSnapshotStore, write_json_atomic


@dataclass(frozen=True, slots=True)
class CompetitionTrainingCoverage:
    league_id: int
    name: str
    fixtures: int
    teams: int
    standings_rows: int
    status: str


@dataclass(frozen=True, slots=True)
class FootballTrainingDataReport:
    season: int
    competitions: int
    expected_requests: int
    api_requests: int
    cache_hits: int
    completed_fixtures: int
    teams: int
    standings_rows: int
    usable_competitions: int
    errors: tuple[str, ...]
    processed_file: Path
    report_file: Path

    def to_text(self) -> str:
        errors = "aucune" if not self.errors else " | ".join(self.errors)
        return (
            f"COLLECTE BASE D'ENTRAÎNEMENT FOOTBALL — SAISON {self.season}\n"
            "========================================================\n"
            f"Compétitions demandées       : {self.competitions}\n"
            f"Requêtes maximales prévues   : {self.expected_requests}\n"
            f"Requêtes API réellement faites: {self.api_requests}\n"
            f"Réponses servies par le cache: {self.cache_hits}\n"
            f"Matchs terminés              : {self.completed_fixtures}\n"
            f"Équipes distinctes           : {self.teams}\n"
            f"Lignes de classement         : {self.standings_rows}\n"
            f"Compétitions exploitables    : {self.usable_competitions}\n"
            f"Erreurs                      : {errors}\n"
            f"Données traitées             : {self.processed_file}\n"
            f"Rapport                      : {self.report_file}\n"
            "\nCette base sert uniquement au développement et au backtest."
        )


def collect_football_training_data(
    settings: AppSettings,
    dates: tuple[date, ...],
    season: int,
    max_requests: int,
) -> FootballTrainingDataReport:
    if not settings.api_football_key:
        raise RuntimeError("API_FOOTBALL_KEY n'est pas configurée dans .env.")
    if not 2000 <= season <= 2100:
        raise ValueError("season doit être une année à quatre chiffres.")
    _, current_competitions = load_target_context(settings, dates)
    competitions = [
        CompetitionSpec(
            league_id=competition.league_id,
            season=season,
            name=competition.name,
        )
        for competition in current_competitions
    ]
    expected_requests = len(competitions) * 2
    if expected_requests > max_requests:
        raise RuntimeError(
            f"Coût maximal prévu {expected_requests} requêtes, supérieur au plafond "
            f"{max_requests}."
        )

    collector = ApiFootballFixturesCollector(settings.api_football_key)
    cache_dir = settings.cache_dir / "api_football" / "training" / str(season)
    raw_store = JsonSnapshotStore(
        settings.raw_dir / "api_football" / "training" / str(season)
    )
    api_requests = 0
    cache_hits = 0
    errors: list[str] = []
    all_history: list[dict[str, Any]] = []
    all_standings: list[dict[str, Any]] = []
    coverage: list[CompetitionTrainingCoverage] = []

    for competition in competitions:
        competition_history: list[dict[str, Any]] = []
        competition_standings: list[dict[str, Any]] = []
        competition_errors: list[str] = []

        fixtures_cache = cache_dir / f"fixtures_{competition.cache_key}.json"
        fixtures_was_cached = fixtures_cache.exists()
        try:
            fixtures_payload, cached = _load_or_fetch(
                fixtures_cache,
                lambda competition=competition: collector.fetch_season_fixtures(
                    competition.league_id,
                    competition.season,
                ),
                raw_store,
                f"training-fixtures-{competition.cache_key}",
            )
            cache_hits += int(cached)
            api_requests += int(not cached)
            competition_history = normalize_history(fixtures_payload)
            all_history.extend(competition_history)
        except Exception as error:
            api_requests += int(not fixtures_was_cached)
            message = f"Matchs {competition.name}: {error}"
            competition_errors.append(message)
            errors.append(message)

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
                f"training-standings-{competition.cache_key}",
            )
            cache_hits += int(cached)
            api_requests += int(not cached)
            competition_standings = normalize_standings(standings_payload)
            all_standings.extend(competition_standings)
        except Exception as error:
            api_requests += int(not standings_was_cached)
            message = f"Classement {competition.name}: {error}"
            competition_errors.append(message)
            errors.append(message)

        team_ids = {
            team_id
            for fixture in competition_history
            for team_id in (fixture["home_team_id"], fixture["away_team_id"])
        }
        coverage.append(
            CompetitionTrainingCoverage(
                league_id=competition.league_id,
                name=competition.name,
                fixtures=len(competition_history),
                teams=len(team_ids),
                standings_rows=len(competition_standings),
                status=(
                    "usable"
                    if len(competition_history) >= 30
                    else ("error" if competition_errors else "insufficient")
                ),
            )
        )

    unique_fixture_ids = {fixture["fixture_id"] for fixture in all_history}
    if len(unique_fixture_ids) != len(all_history):
        deduplicated_history = {
            fixture["fixture_id"]: fixture for fixture in all_history
        }
        all_history = list(deduplicated_history.values())
    all_history.sort(key=lambda fixture: fixture["starts_at"])
    all_standings.sort(
        key=lambda row: (row["league_id"], str(row.get("group")), row["rank"])
    )
    distinct_team_ids = {
        team_id
        for fixture in all_history
        for team_id in (fixture["home_team_id"], fixture["away_team_id"])
    }

    processed_file = settings.processed_dir / f"football_training_data_{season}.json"
    write_json_atomic(
        processed_file,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "purpose": "development_and_backtest_only",
            "season": season,
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
        },
    )
    report_file = settings.reports_dir / f"football_training_data_{season}.json"
    write_json_atomic(
        report_file,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "purpose": "development_and_backtest_only",
            "season": season,
            "expected_requests": expected_requests,
            "api_requests": api_requests,
            "cache_hits": cache_hits,
            "completed_fixture_count": len(all_history),
            "team_count": len(distinct_team_ids),
            "standing_row_count": len(all_standings),
            "coverage": [
                {
                    "league_id": item.league_id,
                    "name": item.name,
                    "fixtures": item.fixtures,
                    "teams": item.teams,
                    "standings_rows": item.standings_rows,
                    "status": item.status,
                }
                for item in coverage
            ],
            "errors": errors,
        },
    )
    return FootballTrainingDataReport(
        season=season,
        competitions=len(competitions),
        expected_requests=expected_requests,
        api_requests=api_requests,
        cache_hits=cache_hits,
        completed_fixtures=len(all_history),
        teams=len(distinct_team_ids),
        standings_rows=len(all_standings),
        usable_competitions=sum(item.status == "usable" for item in coverage),
        errors=tuple(errors),
        processed_file=processed_file,
        report_file=report_file,
    )
