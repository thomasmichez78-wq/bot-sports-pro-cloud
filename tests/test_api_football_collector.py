from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from bot_sports_pro.collectors.api_football import ApiFootballFixturesCollector
from bot_sports_pro.collectors.http import HttpClientError, JsonHttpResponse


class RecordingHttpClient:
    def __init__(self) -> None:
        self.last_url: str | None = None

    def get(self, url: str, headers: dict[str, str] | None = None) -> JsonHttpResponse:
        self.last_url = url
        return JsonHttpResponse(
            payload={"errors": [], "results": 0, "response": []},
            status_code=200,
            headers={},
        )


class RateLimitedOnceHttpClient:
    def __init__(self) -> None:
        self.call_count = 0

    def get(self, url: str, headers: dict[str, str] | None = None) -> JsonHttpResponse:
        self.call_count += 1
        if self.call_count == 1:
            raise HttpClientError(
                "Limite temporaire",
                status_code=429,
                retry_after_seconds=0.0,
            )
        return JsonHttpResponse(
            payload={"errors": [], "results": 0, "response": []},
            status_code=200,
            headers={},
        )


class ApiFootballCollectorTests(unittest.TestCase):
    def test_fetches_complete_historical_season_without_date_filter(self) -> None:
        client = RecordingHttpClient()
        collector = ApiFootballFixturesCollector(  # type: ignore[arg-type]
            "secret-test",
            client,
            min_interval_seconds=0.0,
        )

        collector.fetch_season_fixtures(71, 2024)

        parsed = urlparse(client.last_url or "")
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/fixtures")
        self.assertEqual(query["league"], ["71"])
        self.assertEqual(query["season"], ["2024"])
        self.assertNotIn("from", query)
        self.assertNotIn("to", query)

    def test_retries_after_http_429(self) -> None:
        client = RateLimitedOnceHttpClient()
        collector = ApiFootballFixturesCollector(  # type: ignore[arg-type]
            "secret-test",
            client,
            min_interval_seconds=0.0,
        )

        collector.fetch_standings(71, 2024)

        self.assertEqual(client.call_count, 2)


if __name__ == "__main__":
    unittest.main()
