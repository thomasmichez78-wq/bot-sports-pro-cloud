from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True, slots=True)
class AppSettings:
    root_dir: Path
    environment: str
    timezone: str
    api_football_key: str | None
    odds_api_key: str | None
    football_data_key: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    @classmethod
    def load(cls, root_dir: Path) -> "AppSettings":
        file_values = _read_env_file(root_dir / ".env")

        def value(name: str, default: str = "") -> str:
            return os.environ.get(name, file_values.get(name, default)).strip()

        def secret(name: str) -> str | None:
            return value(name) or None

        return cls(
            root_dir=root_dir,
            environment=value("APP_ENV", "development"),
            timezone=value("APP_TIMEZONE", "Europe/Paris"),
            api_football_key=secret("API_FOOTBALL_KEY"),
            odds_api_key=secret("ODDS_API_KEY"),
            football_data_key=secret("FOOTBALL_DATA_KEY"),
            telegram_bot_token=secret("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=secret("TELEGRAM_CHAT_ID"),
        )

    @property
    def storage_dir(self) -> Path:
        return self.root_dir / "storage"

    @property
    def raw_dir(self) -> Path:
        return self.storage_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.storage_dir / "processed"

    @property
    def reports_dir(self) -> Path:
        return self.storage_dir / "reports"

    @property
    def cache_dir(self) -> Path:
        return self.storage_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "logs"

    def ensure_directories(self) -> None:
        for path in (
            self.raw_dir,
            self.processed_dir,
            self.reports_dir,
            self.cache_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def configured_sources(self) -> dict[str, bool]:
        return {
            "API-Football": self.api_football_key is not None,
            "The Odds API": self.odds_api_key is not None,
            "football-data.org": self.football_data_key is not None,
            "Telegram": bool(self.telegram_bot_token and self.telegram_chat_id),
        }
