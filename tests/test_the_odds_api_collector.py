from __future__ import annotations

import unittest
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from bot_sports_pro.collectors.http import JsonHttpResponse
from bot_sports_pro.collectors.the_odds_api import TheOddsApiCatalogCollector


class RecordingHttpClient:
    def __init__(
        self,
        payload: list[dict] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.last_url: str | None = None
        self.payload = payload or []
        self.headers = headers or {}

    def get(self, url: str, headers: dict[str, str] | None = None) -> JsonHttpResponse:
        self.last_url = url
        return JsonHttpResponse(
            payload=self.payload,
            status_code=200,
            headers=self.headers,
        )


class TheOddsApiCollectorTests(unittest.TestCase):
    def test_event_window_uses_utc_seconds_without_microseconds(self) -> None:
        client = RecordingHttpClient()
        collector = TheOddsApiCatalogCollector("secret-test", client)  # type: ignore[arg-type]

        collector.fetch_events(
            "soccer_epl",
            datetime(2026, 7, 23, 0, 0, 0, 123456, tzinfo=UTC),
            datetime(2026, 7, 24, 23, 59, 59, 999999, tzinfo=UTC),
        )

        self.assertIsNotNone(client.last_url)
        query = parse_qs(urlparse(client.last_url or "").query)
        self.assertEqual(query["commenceTimeFrom"], ["2026-07-23T00:00:00Z"])
        self.assertEqual(query["commenceTimeTo"], ["2026-07-24T23:59:59Z"])

    def test_rejects_naive_event_window(self) -> None:
        with self.assertRaises(ValueError):
            TheOddsApiCatalogCollector._format_utc_seconds(datetime(2026, 7, 23))

    def test_fetch_odds_returns_quota_headers_and_filters_event_ids(self) -> None:
        client = RecordingHttpClient(
            headers={
                "x-requests-remaining": "271",
                "x-requests-used": "229",
                "x-requests-last": "1",
            }
        )
        collector = TheOddsApiCatalogCollector("secret-test", client)  # type: ignore[arg-type]

        response = collector.fetch_odds(
            "soccer_epl",
            ("event-1", "event-2"),
            datetime(2026, 7, 23, tzinfo=UTC),
            datetime(2026, 7, 24, 23, 59, 59, tzinfo=UTC),
        )

        query = parse_qs(urlparse(client.last_url or "").query)
        self.assertEqual(query["eventIds"], ["event-1,event-2"])
        self.assertEqual(query["regions"], ["eu"])
        self.assertEqual(query["markets"], ["h2h"])
        self.assertEqual(response.requests_remaining, 271)
        self.assertEqual(response.requests_last, 1)


if __name__ == "__main__":
    unittest.main()
