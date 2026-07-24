from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bot_sports_pro.collectors.api_football import ApiFootballFixturesCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.services.football_sports_data import normalize_history
from bot_sports_pro.storage.json_store import JsonSnapshotStore, write_json_atomic


MIN_TEAM_MATCHES = 5


@dataclass(frozen=True, slots=True)
class LiveCompetitionCoverage:
    league_id: int
    name: str
    matches: int
    observed_teams: int
    teams_ready: int


@dataclass(frozen=True, slots=True)
class FootballLiveHistoryReport:
    target_date: date
    api_requests: int
    cache_hits: int
    received_fixtures: int
    completed_fixtures: int
    retained_fixtures: int
    total_history: int
    collected_dates: int
    competitions: int
    observed_teams: int
    teams_ready: int
    coverage: tuple[LiveCompetitionCoverage, ...]
    processed_file: Path
    report_file: Path

    def to_text(self) -> str:
        state = (
            "premières probabilités possibles pour certaines équipes"
            if self.teams_ready
            else "base en construction"
        )
        return (
            "MISE À JOUR HISTORIQUE FOOTBALL EN DIRECT\n"
            "=========================================\n"
            f"Journée archivée              : {self.target_date.isoformat()}\n"
            f"Requêtes API réalisées        : {self.api_requests}\n"
            f"Réponses servies par le cache : {self.cache_hits}\n"
            f"Rencontres reçues             : {self.received_fixtures}\n"
            f"Rencontres terminées          : {self.completed_fixtures}\n"
            f"Rencontres cibles conservées  : {self.retained_fixtures}\n"
            f"Historique cumulé             : {self.total_history}\n"
            f"Journées définitivement suivies: {self.collected_dates}\n"
            f"Compétitions surveillées      : {self.competitions}\n"
            f"Équipes observées             : {self.observed_teams}\n"
            f"Équipes avec au moins 5 matchs: {self.teams_ready}\n"
            f"État du modèle actuel         : {state}\n"
            f"Données cumulées              : {self.processed_file}\n"
            f"Rapport                       : {self.report_file}\n"
            "\nAucune probabilité, value ou sélection n'a été produite."
        )


def resolve_live_target_date(
    requested_date: date | None,
    now: datetime,
) -> date:
    if now.tzinfo is None:
        raise ValueError("now doit contenir un fuseau horaire.")
    yesterday = now.date() - timedelta(days=1)
    target_date = requested_date or yesterday
    if target_date != yesterday:
        raise ValueError(
            "Le forfait gratuit permet d'archiver uniquement la veille. "
            f"Date attendue aujourd'hui : {yesterday.isoformat()}."
        )
    if now.hour < 6:
        raise ValueError(
            "Attends 06h00 avant d'archiver la veille afin que les matchs "
            "tardifs soient terminés."
        )
    return target_date


def merge_live_history(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_fixture_id = {
        int(fixture["fixture_id"]): fixture
        for fixture in existing
    }
    for fixture in incoming:
        by_fixture_id[int(fixture["fixture_id"])] = fixture
    return sorted(
        by_fixture_id.values(),
        key=lambda fixture: (str(fixture["starts_at"]), int(fixture["fixture_id"])),
    )


def build_live_coverage(
    history: list[dict[str, Any]],
    competitions: list[dict[str, Any]],
) -> tuple[LiveCompetitionCoverage, ...]:
    coverage: list[LiveCompetitionCoverage] = []
    for competition in sorted(competitions, key=lambda item: int(item["league_id"])):
        league_id = int(competition["league_id"])
        league_matches = [
            fixture
            for fixture in history
            if int(fixture["league_id"]) == league_id
        ]
        appearances: Counter[int] = Counter()
        for fixture in league_matches:
            appearances[int(fixture["home_team_id"])] += 1
            appearances[int(fixture["away_team_id"])] += 1
        coverage.append(
            LiveCompetitionCoverage(
                league_id=league_id,
                name=str(competition["name"]),
                matches=len(league_matches),
                observed_teams=len(appearances),
                teams_ready=sum(
                    matches >= MIN_TEAM_MATCHES
                    for matches in appearances.values()
                ),
            )
        )
    return tuple(coverage)


def _load_competitions(settings: AppSettings) -> list[dict[str, Any]]:
    live_file = settings.processed_dir / "football_live_history.json"
    if live_file.exists():
        try:
            live_document = json.loads(live_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            live_document = {}
        live_competitions = live_document.get("competitions")
        if (
            live_document.get("purpose") == "prospective_live_model_history"
            and isinstance(live_competitions, list)
            and live_competitions
        ):
            return [
                {
                    "league_id": int(item["league_id"]),
                    "name": str(item["name"]),
                }
                for item in live_competitions
            ]

    candidates = sorted(
        settings.processed_dir.glob("football_training_data_*.json"),
        reverse=True,
    )
    for candidate in candidates:
        try:
            document = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        competitions = document.get("competitions")
        if isinstance(competitions, list) and competitions:
            return [
                {
                    "league_id": int(item["league_id"]),
                    "name": str(item["name"]),
                }
                for item in competitions
            ]
    raise RuntimeError(
        "Aucun historique direct ou base d'entraînement ne permet de déterminer "
        "les compétitions."
    )


def _load_existing_document(
    processed_file: Path,
    competitions: list[dict[str, Any]],
) -> dict[str, Any]:
    if not processed_file.exists():
        return {
            "purpose": "prospective_live_model_history",
            "collection_started_at": datetime.now(UTC).isoformat(),
            "dates_collected": [],
            "competitions": competitions,
            "history": [],
        }
    document = json.loads(processed_file.read_text(encoding="utf-8"))
    if document.get("purpose") != "prospective_live_model_history":
        raise ValueError("Le fichier d'historique direct possède un usage incompatible.")
    if not isinstance(document.get("history"), list):
        raise ValueError("La liste history est absente de l'historique direct.")
    return document


def update_football_live_history(
    settings: AppSettings,
    requested_date: date | None = None,
    now: datetime | None = None,
) -> FootballLiveHistoryReport:
    if not settings.api_football_key:
        raise RuntimeError("API_FOOTBALL_KEY n'est pas configurée dans .env.")
    local_now = now or datetime.now(ZoneInfo(settings.timezone))
    target_date = resolve_live_target_date(requested_date, local_now)
    competitions = _load_competitions(settings)
    target_league_ids = {
        int(competition["league_id"])
        for competition in competitions
    }
    processed_file = settings.processed_dir / "football_live_history.json"
    document = _load_existing_document(processed_file, competitions)
    cache_file = (
        settings.cache_dir
        / "api_football"
        / "live_dates"
        / f"{target_date.isoformat()}.json"
    )
    raw_store = JsonSnapshotStore(
        settings.raw_dir / "api_football" / "live_dates"
    )

    if cache_file.exists():
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        api_requests = 0
        cache_hits = 1
    else:
        collector = ApiFootballFixturesCollector(settings.api_football_key)
        payload = collector.fetch_by_date(target_date)
        raw_store.save(
            f"api-football-live-{target_date.isoformat()}",
            payload,
        )
        write_json_atomic(cache_file, payload)
        api_requests = 1
        cache_hits = 0

    completed = normalize_history(payload)
    retained = [
        fixture
        for fixture in completed
        if int(fixture["league_id"]) in target_league_ids
    ]
    merged_history = merge_live_history(document["history"], retained)
    collected_dates = sorted(
        {
            *(str(value) for value in document.get("dates_collected", [])),
            target_date.isoformat(),
        }
    )
    write_json_atomic(
        processed_file,
        {
            **document,
            "generated_at": datetime.now(UTC).isoformat(),
            "dates_collected": collected_dates,
            "competitions": competitions,
            "history": merged_history,
        },
    )
    coverage = build_live_coverage(merged_history, competitions)
    report_file = (
        settings.reports_dir
        / f"football_live_history_{target_date.isoformat()}.json"
    )
    report_document = {
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "prospective_live_model_history",
        "target_date": target_date.isoformat(),
        "api_requests": api_requests,
        "cache_hits": cache_hits,
        "received_fixtures": len(payload.get("response", [])),
        "completed_fixtures": len(completed),
        "retained_fixtures": len(retained),
        "total_history": len(merged_history),
        "collected_dates": len(collected_dates),
        "minimum_team_matches": MIN_TEAM_MATCHES,
        "coverage": [
            {
                "league_id": item.league_id,
                "name": item.name,
                "matches": item.matches,
                "observed_teams": item.observed_teams,
                "teams_ready": item.teams_ready,
            }
            for item in coverage
        ],
    }
    write_json_atomic(report_file, report_document)
    return FootballLiveHistoryReport(
        target_date=target_date,
        api_requests=api_requests,
        cache_hits=cache_hits,
        received_fixtures=len(payload.get("response", [])),
        completed_fixtures=len(completed),
        retained_fixtures=len(retained),
        total_history=len(merged_history),
        collected_dates=len(collected_dates),
        competitions=len(competitions),
        observed_teams=sum(item.observed_teams for item in coverage),
        teams_ready=sum(item.teams_ready for item in coverage),
        coverage=coverage,
        processed_file=processed_file,
        report_file=report_file,
    )
