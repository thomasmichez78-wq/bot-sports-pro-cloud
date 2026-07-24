from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from bot_sports_pro.config.settings import AppSettings


@dataclass(frozen=True, slots=True)
class MarketAnalysisReport:
    events: int
    winamax_priced_events: int
    odds_to_check_events: int
    analyzed_outcomes: int
    positive_market_edges: int
    min_market_edge: float | None
    max_market_edge: float | None
    report_file: Path

    def to_text(self) -> str:
        minimum = (
            f"{self.min_market_edge * 100:.2f}%"
            if self.min_market_edge is not None
            else "indisponible"
        )
        maximum = (
            f"{self.max_market_edge * 100:.2f}%"
            if self.max_market_edge is not None
            else "indisponible"
        )
        return (
            "ANALYSE DU MARCHÉ H2H — CIBLE WINAMAX FRANCE\n"
            "=============================================\n"
            f"Matchs analysés               : {self.events}\n"
            f"Matchs avec cote Winamax      : {self.winamax_priced_events}\n"
            f"Matchs cote à vérifier        : {self.odds_to_check_events}\n"
            f"Issues Winamax comparées      : {self.analyzed_outcomes}\n"
            f"Écarts de marché positifs     : {self.positive_market_edges}\n"
            f"Écart de marché minimal       : {minimum}\n"
            f"Écart de marché maximal       : {maximum}\n"
            f"Rapport                        : {self.report_file}\n"
            "\nCes écarts comparent Winamax à Pinnacle corrigé de marge. "
            "Ils ne constituent pas des pronostics."
        )


def _fair_probabilities(outcomes: dict[str, dict]) -> tuple[dict[str, float], float]:
    if len(outcomes) != 3:
        raise ValueError("Un marché 1N2 doit contenir exactement trois issues.")
    implied = {
        selection: 1.0 / float(row["decimal_price"])
        for selection, row in outcomes.items()
    }
    total = sum(implied.values())
    if total <= 1.0:
        raise ValueError("La marge brute du marché doit être positive.")
    return (
        {selection: probability / total for selection, probability in implied.items()},
        total - 1.0,
    )


def analyze_football_odds_market(
    settings: AppSettings,
    dates: tuple[date, ...],
) -> MarketAnalysisReport:
    batch_name = f"{dates[0].isoformat()}_{dates[-1].isoformat()}"
    input_file = settings.processed_dir / f"football_odds_h2h_{batch_name}.json"
    if not input_file.exists():
        raise RuntimeError(
            f"Collecte de cotes introuvable : {input_file}. "
            "Lance d'abord collect-odds-football avec les mêmes dates."
        )

    document = json.loads(input_file.read_text(encoding="utf-8"))
    prices = document.get("prices")
    if not isinstance(prices, list):
        raise RuntimeError("Le fichier de cotes normalisées est invalide.")

    grouped: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    event_metadata: dict[str, dict] = {}
    for row in prices:
        event_id = str(row["provider_event_id"])
        bookmaker_key = str(row["bookmaker_key"])
        selection = str(row["selection"])
        grouped[(event_id, bookmaker_key)][selection] = row
        event_metadata[event_id] = {
            "fixture_event_id": row.get("fixture_event_id"),
            "provider_event_id": event_id,
            "sport_key": row.get("sport_key"),
            "commence_time": row.get("commence_time"),
            "home_team": row.get("home_team"),
            "away_team": row.get("away_team"),
        }

    event_results: list[dict] = []
    market_edges: list[float] = []
    winamax_priced_events = 0
    odds_to_check_events = 0

    for event_id, metadata in sorted(
        event_metadata.items(),
        key=lambda item: str(item[1].get("commence_time")),
    ):
        pinnacle = grouped.get((event_id, "pinnacle"))
        winamax = grouped.get((event_id, "winamax_fr"))
        if not pinnacle:
            event_results.append(
                {
                    **metadata,
                    "status": "reference_missing",
                    "reason": "Marché Pinnacle absent.",
                    "outcomes": [],
                }
            )
            continue

        fair_probabilities, pinnacle_margin = _fair_probabilities(pinnacle)
        if not winamax:
            odds_to_check_events += 1
            event_results.append(
                {
                    **metadata,
                    "status": "odds_to_check",
                    "reason": "Cote Winamax France absente de la collecte.",
                    "reference_bookmaker": "pinnacle",
                    "reference_margin": pinnacle_margin,
                    "outcomes": [
                        {
                            "selection": selection,
                            "reference_price": pinnacle[selection]["decimal_price"],
                            "reference_fair_probability": fair_probability,
                            "winamax_price": None,
                            "market_edge": None,
                        }
                        for selection, fair_probability in fair_probabilities.items()
                    ],
                }
            )
            continue

        if set(winamax) != set(pinnacle):
            event_results.append(
                {
                    **metadata,
                    "status": "selection_mismatch",
                    "reason": "Les issues Winamax et Pinnacle ne correspondent pas.",
                    "outcomes": [],
                }
            )
            continue

        winamax_priced_events += 1
        _, winamax_margin = _fair_probabilities(winamax)
        outcomes = []
        for selection, fair_probability in fair_probabilities.items():
            winamax_price = float(winamax[selection]["decimal_price"])
            market_edge = (fair_probability * winamax_price) - 1.0
            market_edges.append(market_edge)
            outcomes.append(
                {
                    "selection": selection,
                    "reference_price": pinnacle[selection]["decimal_price"],
                    "reference_fair_probability": fair_probability,
                    "winamax_price": winamax_price,
                    "winamax_implied_probability": 1.0 / winamax_price,
                    "market_edge": market_edge,
                }
            )
        event_results.append(
            {
                **metadata,
                "status": "priced",
                "reference_bookmaker": "pinnacle",
                "reference_margin": pinnacle_margin,
                "target_bookmaker": "winamax_fr",
                "target_margin": winamax_margin,
                "outcomes": outcomes,
            }
        )

    report_file = settings.reports_dir / f"odds_market_analysis_{batch_name}.json"
    report_file.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "target_bookmaker": "winamax_fr",
                "reference_bookmaker": "pinnacle",
                "event_count": len(event_results),
                "winamax_priced_event_count": winamax_priced_events,
                "odds_to_check_event_count": odds_to_check_events,
                "positive_market_edge_count": sum(edge > 0 for edge in market_edges),
                "events": event_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return MarketAnalysisReport(
        events=len(event_results),
        winamax_priced_events=winamax_priced_events,
        odds_to_check_events=odds_to_check_events,
        analyzed_outcomes=len(market_edges),
        positive_market_edges=sum(edge > 0 for edge in market_edges),
        min_market_edge=min(market_edges) if market_edges else None,
        max_market_edge=max(market_edges) if market_edges else None,
        report_file=report_file,
    )
