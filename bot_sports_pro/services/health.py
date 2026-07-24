from __future__ import annotations

from dataclasses import dataclass

from bot_sports_pro import __version__
from bot_sports_pro.config.catalog import ENABLED_SPORTS
from bot_sports_pro.config.settings import AppSettings


@dataclass(frozen=True, slots=True)
class HealthReport:
    version: str
    environment: str
    timezone: str
    enabled_sports: tuple[str, ...]
    directories_ready: bool
    sources: dict[str, bool]


def build_health_report(settings: AppSettings) -> HealthReport:
    required_directories = (
        settings.raw_dir,
        settings.processed_dir,
        settings.reports_dir,
        settings.logs_dir,
    )
    return HealthReport(
        version=__version__,
        environment=settings.environment,
        timezone=settings.timezone,
        enabled_sports=tuple(sport.value for sport in ENABLED_SPORTS),
        directories_ready=all(path.is_dir() for path in required_directories),
        sources=settings.configured_sources(),
    )


def format_health_report(report: HealthReport) -> str:
    source_lines = "\n".join(
        f"  - {name}: {'configurée' if configured else 'absente'}"
        for name, configured in report.sources.items()
    )
    sports = ", ".join(report.enabled_sports) or "aucun"
    return (
        "BOT SPORTS PRO — DIAGNOSTIC\n"
        "===========================\n"
        f"Version              : {report.version}\n"
        f"Environnement        : {report.environment}\n"
        f"Fuseau horaire       : {report.timezone}\n"
        f"Sports actifs        : {sports}\n"
        f"Dossiers opérationnels: {'oui' if report.directories_ready else 'non'}\n"
        "Sources :\n"
        f"{source_lines}"
    )
