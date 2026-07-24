from __future__ import annotations

from datetime import datetime
from typing import Any

from bot_sports_pro.core.enums import Sport
from bot_sports_pro.core.models import Event, SourceStamp


class FixtureNormalizationError(ValueError):
    """Une rencontre ne respecte pas le contrat de données interne."""


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise FixtureNormalizationError(f"Champ '{context}.{key}' absent.")
    return value


def normalize_fixture(item: dict[str, Any], fetched_at: datetime) -> Event:
    try:
        fixture = item["fixture"]
        league = item["league"]
        teams = item["teams"]
        home = teams["home"]
        away = teams["away"]
    except (KeyError, TypeError) as error:
        raise FixtureNormalizationError("Structure de rencontre incomplète.") from error

    starts_at = datetime.fromisoformat(str(_required(fixture, "date", "fixture")))
    if starts_at.tzinfo is None:
        raise FixtureNormalizationError("L'heure de rencontre ne contient aucun fuseau.")

    fixture_id = str(_required(fixture, "id", "fixture"))
    league_id = _required(league, "id", "league")
    season = _required(league, "season", "league")
    return Event(
        event_id=f"api-football:{fixture_id}",
        sport=Sport.FOOTBALL,
        competition=str(_required(league, "name", "league")),
        starts_at=starts_at,
        home_name=str(_required(home, "name", "teams.home")),
        away_name=str(_required(away, "name", "teams.away")),
        source=SourceStamp(
            name="API-Football",
            fetched_at=fetched_at,
            confidence=0.90,
        ),
        metadata={
            "provider_fixture_id": fixture_id,
            "provider_league_id": league_id,
            "season": season,
            "home_team_id": _required(home, "id", "teams.home"),
            "away_team_id": _required(away, "id", "teams.away"),
            "country": league.get("country"),
            "round": league.get("round"),
            "status": fixture.get("status", {}).get("short"),
        },
    )


def normalize_fixtures(
    payload: dict[str, Any],
    fetched_at: datetime,
) -> tuple[list[Event], list[str]]:
    events: list[Event] = []
    rejected: list[str] = []
    for index, item in enumerate(payload.get("response", [])):
        try:
            events.append(normalize_fixture(item, fetched_at))
        except (FixtureNormalizationError, ValueError, TypeError) as error:
            rejected.append(f"Élément {index}: {error}")
    return events, rejected
