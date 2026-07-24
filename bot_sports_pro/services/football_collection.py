from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from bot_sports_pro.collectors.api_football import ApiFootballFixturesCollector
from bot_sports_pro.config.settings import AppSettings
from bot_sports_pro.normalizers.api_football import normalize_fixtures
from bot_sports_pro.storage.json_store import JsonSnapshotStore
from bot_sports_pro.storage.serialization import to_json_compatible


@dataclass(frozen=True, slots=True)
class CollectionDay:
    target_date: date
    received: int
    normalized: int
    rejected: int
    raw_file: Path


@dataclass(frozen=True, slots=True)
class FootballCollectionReport:
    days: tuple[CollectionDay, ...]
    normalized_file: Path
    report_file: Path

    @property
    def received(self) -> int:
        return sum(day.received for day in self.days)

    @property
    def normalized(self) -> int:
        return sum(day.normalized for day in self.days)

    @property
    def rejected(self) -> int:
        return sum(day.rejected for day in self.days)

    def to_text(self) -> str:
        lines = [
            "COLLECTE FOOTBALL — API-FOOTBALL",
            "================================",
        ]
        lines.extend(
            (
                f"{day.target_date.isoformat()} : reçues={day.received}, "
                f"normalisées={day.normalized}, rejetées={day.rejected}"
            )
            for day in self.days
        )
        lines.extend(
            [
                "",
                f"Total reçu       : {self.received}",
                f"Total normalisé  : {self.normalized}",
                f"Total rejeté     : {self.rejected}",
                f"Données traitées : {self.normalized_file}",
                f"Rapport           : {self.report_file}",
                "",
                "Aucun pronostic n'a été produit.",
            ]
        )
        return "\n".join(lines)


def collect_football_fixtures(
    settings: AppSettings,
    dates: tuple[date, ...],
) -> FootballCollectionReport:
    if not settings.api_football_key:
        raise RuntimeError("API_FOOTBALL_KEY n'est pas configurée dans .env.")

    collector = ApiFootballFixturesCollector(settings.api_football_key)
    raw_store = JsonSnapshotStore(settings.raw_dir / "api_football" / "fixtures")
    fetched_at = datetime.now(UTC)
    all_events = []
    all_rejections: list[dict[str, object]] = []
    day_reports: list[CollectionDay] = []

    for target_date in dates:
        payload = collector.fetch_by_date(target_date)
        raw_file = raw_store.save(
            source=f"api-football-fixtures-{target_date.isoformat()}",
            payload=payload,
            fetched_at=datetime.now(UTC),
        )
        events, rejected = normalize_fixtures(payload, fetched_at)
        all_events.extend(events)
        all_rejections.extend(
            {"date": target_date.isoformat(), "reason": reason} for reason in rejected
        )
        day_reports.append(
            CollectionDay(
                target_date=target_date,
                received=len(payload["response"]),
                normalized=len(events),
                rejected=len(rejected),
                raw_file=raw_file,
            )
        )

    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    normalized_file = settings.processed_dir / f"football_fixtures_{batch_name}.json"
    normalized_document = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "API-Football",
        "events": to_json_compatible(all_events),
    }
    normalized_file.write_text(
        json.dumps(normalized_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report_file = settings.reports_dir / f"football_collection_{batch_name}.json"
    report_document = {
        "generated_at": datetime.now(UTC).isoformat(),
        "received": sum(day.received for day in day_reports),
        "normalized": sum(day.normalized for day in day_reports),
        "rejected": len(all_rejections),
        "days": [
            {
                "date": day.target_date.isoformat(),
                "received": day.received,
                "normalized": day.normalized,
                "rejected": day.rejected,
                "raw_file": str(day.raw_file),
            }
            for day in day_reports
        ],
        "rejections": all_rejections,
    }
    report_file.write_text(
        json.dumps(report_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return FootballCollectionReport(
        days=tuple(day_reports),
        normalized_file=normalized_file,
        report_file=report_file,
    )
