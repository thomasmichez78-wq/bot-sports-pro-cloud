from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpClientError(RuntimeError):
    """Erreur réseau lisible sans exposer les secrets."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class JsonHttpResponse:
    payload: Any
    status_code: int
    headers: dict[str, str]


class JsonHttpClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def get(self, url: str, headers: dict[str, str] | None = None) -> JsonHttpResponse:
        request = Request(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": "bot-sports-pro/0.2",
                **(headers or {}),
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read()
                status_code = response.status
                response_headers = {
                    key.lower(): value for key, value in response.headers.items()
                }
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            retry_after: float | None = None
            raw_retry_after = error.headers.get("Retry-After")
            if raw_retry_after:
                try:
                    retry_after = float(raw_retry_after)
                except ValueError:
                    retry_after = None
            raise HttpClientError(
                f"HTTP {error.code} renvoyé par la source : {detail}",
                status_code=error.code,
                retry_after_seconds=retry_after,
            ) from error
        except URLError as error:
            raise HttpClientError(f"Connexion impossible : {error.reason}") from error
        except TimeoutError as error:
            raise HttpClientError("La source n'a pas répondu dans le délai prévu.") from error

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HttpClientError("La source a renvoyé une réponse JSON invalide.") from error
        return JsonHttpResponse(payload, status_code, response_headers)
