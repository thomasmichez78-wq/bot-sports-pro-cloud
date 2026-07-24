from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any
from urllib.parse import urlencode

from bot_sports_pro.collectors.http import HttpClientError, JsonHttpClient


LOGGER = logging.getLogger(__name__)


class ApiFootballError(RuntimeError):
    """Réponse fonctionnelle invalide d'API-Football."""


class ApiFootballFixturesCollector:
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(
        self,
        api_key: str,
        http_client: JsonHttpClient | None = None,
        min_interval_seconds: float = 6.2,
    ) -> None:
        if not api_key:
            raise ValueError("La clé API-Football est absente.")
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds ne peut pas être négatif.")
        self._api_key = api_key
        self._http_client = http_client or JsonHttpClient()
        self._min_interval_seconds = min_interval_seconds
        self._last_request_at: float | None = None

    def fetch_by_date(self, target_date: date) -> dict[str, Any]:
        query = urlencode({"date": target_date.isoformat(), "timezone": "Europe/Paris"})
        return self._fetch(
            endpoint="fixtures",
            query=query,
            context=f"rencontres du {target_date.isoformat()}",
        )

    def fetch_history(
        self,
        league_id: int,
        season: int,
        date_from: date,
        date_to: date,
    ) -> dict[str, Any]:
        query = urlencode(
            {
                "league": league_id,
                "season": season,
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "timezone": "Europe/Paris",
            }
        )
        return self._fetch(
            endpoint="fixtures",
            query=query,
            context=f"historique ligue {league_id}, saison {season}",
        )

    def fetch_season_fixtures(self, league_id: int, season: int) -> dict[str, Any]:
        query = urlencode(
            {
                "league": league_id,
                "season": season,
                "timezone": "Europe/Paris",
            }
        )
        return self._fetch(
            endpoint="fixtures",
            query=query,
            context=f"saison complète ligue {league_id}, saison {season}",
        )

    def fetch_standings(self, league_id: int, season: int) -> dict[str, Any]:
        query = urlencode({"league": league_id, "season": season})
        return self._fetch(
            endpoint="standings",
            query=query,
            context=f"classement ligue {league_id}, saison {season}",
        )

    def _fetch(self, endpoint: str, query: str, context: str) -> dict[str, Any]:
        response = None
        for attempt in range(1, 4):
            self._wait_for_slot(context)
            try:
                response = self._http_client.get(
                    f"{self.BASE_URL}/{endpoint}?{query}",
                    headers={"x-apisports-key": self._api_key},
                )
                break
            except HttpClientError as error:
                if error.status_code != 429 or attempt == 3:
                    raise
                retry_after = max(
                    error.retry_after_seconds or self._min_interval_seconds,
                    self._min_interval_seconds,
                )
                LOGGER.warning(
                    "Limite temporaire API-Football pour %s. Nouvelle tentative "
                    "dans %.1f secondes.",
                    context,
                    retry_after,
                )
                time.sleep(retry_after)
        if response is None:
            raise ApiFootballError(f"Aucune réponse obtenue pour {context}.")
        if not isinstance(response.payload, dict):
            raise ApiFootballError(f"Structure inattendue pour {context}.")

        errors = response.payload.get("errors")
        if errors:
            raise ApiFootballError(f"API-Football signale une erreur pour {context} : {errors}")
        fixtures = response.payload.get("response")
        if not isinstance(fixtures, list):
            raise ApiFootballError("La liste 'response' est absente de la réponse.")
        return response.payload

    def _wait_for_slot(self, context: str) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self._min_interval_seconds - elapsed
            if remaining > 0:
                LOGGER.info(
                    "Régulation API-Football : attente de %.1f secondes avant %s.",
                    remaining,
                    context,
                )
                time.sleep(remaining)
        self._last_request_at = time.monotonic()
