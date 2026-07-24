from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bot_sports_pro.core.enums import Confidence, Market, SelectionStatus, Sport


def _validate_probability(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} doit être compris entre 0 et 1.")


@dataclass(frozen=True, slots=True)
class SourceStamp:
    name: str
    fetched_at: datetime
    confidence: float

    def __post_init__(self) -> None:
        _validate_probability(self.confidence, "confidence")


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    sport: Sport
    competition: str
    starts_at: datetime
    home_name: str
    away_name: str
    source: SourceStamp
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None:
            raise ValueError("starts_at doit contenir un fuseau horaire.")
        if not all((self.event_id, self.competition, self.home_name, self.away_name)):
            raise ValueError("Un événement doit contenir ses identifiants et participants.")


@dataclass(frozen=True, slots=True)
class Odds:
    event_id: str
    market: Market
    selection: str
    decimal_price: float
    bookmaker: str
    source: SourceStamp

    def __post_init__(self) -> None:
        if self.decimal_price <= 1.0:
            raise ValueError("Une cote décimale doit être strictement supérieure à 1.")

    @property
    def implied_probability(self) -> float:
        return 1.0 / self.decimal_price


@dataclass(frozen=True, slots=True)
class Analysis:
    event_id: str
    market: Market
    selection: str
    model_probability: float
    confidence: Confidence
    risks: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_probability(self.model_probability, "model_probability")


@dataclass(frozen=True, slots=True)
class Selection:
    event_id: str
    market: Market
    selection: str
    status: SelectionStatus
    confidence: Confidence
    model_probability: float | None = None
    decimal_price: float | None = None
    value_points: float | None = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.model_probability is not None:
            _validate_probability(self.model_probability, "model_probability")
        if self.decimal_price is not None and self.decimal_price <= 1.0:
            raise ValueError("decimal_price doit être strictement supérieure à 1.")
