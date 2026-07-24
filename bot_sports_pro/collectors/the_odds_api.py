from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from bot_sports_pro.collectors.http import JsonHttpClient


class TheOddsApiError(RuntimeError):
    """Réponse fonctionnelle invalide de The Odds API."""


@dataclass(frozen=True, slots=True)
class OddsApiResponse:
    payload: list[dict[str, Any]]
    requests_remaining: int | None
    requests_used: int | None
    requests_last: int | None


class TheOddsApiCatalogCollector:
    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self, api_key: str, http_client: JsonHttpClient | None = None) -> None:
        if not api_key:
            raise ValueError("La clé The Odds API est absente.")
        self._api_key = api_key
        self._http_client = http_client or JsonHttpClient()

    def fetch_sports(self) -> list[dict[str, Any]]:
        query = urlencode({"apiKey": self._api_key})
        response = self._http_client.get(f"{self.BASE_URL}/sports/?{query}")
        return self._validate_list(response.payload, "catalogue des sports")

    def fetch_events(
        self,
        sport_key: str,
        commence_from: datetime,
        commence_to: datetime,
    ) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "apiKey": self._api_key,
                "dateFormat": "iso",
                "commenceTimeFrom": self._format_utc_seconds(commence_from),
                "commenceTimeTo": self._format_utc_seconds(commence_to),
            }
        )
        safe_key = quote(sport_key, safe="_-")
        response = self._http_client.get(
            f"{self.BASE_URL}/sports/{safe_key}/events?{query}"
        )
        return self._validate_list(response.payload, f"événements {sport_key}")

    def fetch_odds(
        self,
        sport_key: str,
        event_ids: tuple[str, ...],
        commence_from: datetime,
        commence_to: datetime,
    ) -> OddsApiResponse:
        if not event_ids:
            raise ValueError("Au moins un identifiant d'événement est requis.")
        query = urlencode(
            {
                "apiKey": self._api_key,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
                "eventIds": ",".join(event_ids),
                "commenceTimeFrom": self._format_utc_seconds(commence_from),
                "commenceTimeTo": self._format_utc_seconds(commence_to),
            }
        )
        safe_key = quote(sport_key, safe="_-")
        response = self._http_client.get(
            f"{self.BASE_URL}/sports/{safe_key}/odds?{query}"
        )
        payload = self._validate_list(response.payload, f"cotes {sport_key}")
        return OddsApiResponse(
            payload=payload,
            requests_remaining=self._integer_header(
                response.headers, "x-requests-remaining"
            ),
            requests_used=self._integer_header(response.headers, "x-requests-used"),
            requests_last=self._integer_header(response.headers, "x-requests-last"),
        )

    @staticmethod
    def _format_utc_seconds(value: datetime) -> str:
        if value.tzinfo is None:
            raise ValueError("La fenêtre temporelle doit contenir un fuseau horaire.")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _integer_header(headers: dict[str, str], name: str) -> int | None:
        raw_value = headers.get(name)
        if raw_value is None:
            return None
        try:
            return int(raw_value)
        except ValueError:
            return None

    @staticmethod
    def _validate_list(payload: Any, context: str) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and payload.get("message"):
            raise TheOddsApiError(f"{context} : {payload['message']}")
        if not isinstance(payload, list):
            raise TheOddsApiError(f"Structure inattendue pour {context}.")
        if not all(isinstance(item, dict) for item in payload):
            raise TheOddsApiError(f"Élément invalide dans {context}.")
        return payload
