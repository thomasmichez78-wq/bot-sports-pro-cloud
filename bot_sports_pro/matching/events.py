from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any


def normalize_team_name(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", ascii_name.lower())
    ignored = {"fc", "cf", "sc", "afc", "club", "fk", "ff", "bk"}
    useful_words = [word for word in words if word not in ignored]
    return " ".join(useful_words)


def team_similarity(left: str, right: str) -> float:
    normalized_left = normalize_team_name(left)
    normalized_right = normalize_team_name(right)
    sequence_score = SequenceMatcher(
        None,
        normalized_left,
        normalized_right,
    ).ratio()
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    if left_tokens and right_tokens and (
        left_tokens.issubset(right_tokens) or right_tokens.issubset(left_tokens)
    ):
        containment_score = 1.0 if left_tokens == right_tokens else 0.88
        return max(sequence_score, containment_score)
    return sequence_score


@dataclass(frozen=True, slots=True)
class MatchDecision:
    fixture_event_id: str
    odds_event_id: str | None
    status: str
    score: float | None
    reason: str


def match_fixture(
    fixture: dict[str, Any],
    odds_events: list[dict[str, Any]],
) -> MatchDecision:
    fixture_time = datetime.fromisoformat(fixture["starts_at"])
    candidates: list[tuple[float, dict[str, Any], float]] = []

    for event in odds_events:
        event_time = datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))
        time_gap_hours = abs((fixture_time - event_time).total_seconds()) / 3600
        if time_gap_hours > 8:
            continue

        direct_home = team_similarity(fixture["home_name"], event["home_team"])
        direct_away = team_similarity(fixture["away_name"], event["away_team"])
        reversed_home = team_similarity(fixture["home_name"], event["away_team"])
        reversed_away = team_similarity(fixture["away_name"], event["home_team"])

        direct_score = (direct_home + direct_away) / 2
        reversed_score = (reversed_home + reversed_away) / 2
        orientation_score = max(direct_score, reversed_score)
        if min(
            (direct_home, direct_away)
            if direct_score >= reversed_score
            else (reversed_home, reversed_away)
        ) < 0.72:
            continue

        time_score = max(0.0, 1.0 - (time_gap_hours / 8.0))
        total_score = (orientation_score * 0.90) + (time_score * 0.10)
        candidates.append((total_score, event, orientation_score))

    if not candidates:
        return MatchDecision(
            fixture_event_id=fixture["event_id"],
            odds_event_id=None,
            status="unmatched",
            score=None,
            reason="Aucun candidat compatible sur les équipes et l'horaire.",
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_event, name_score = candidates[0]
    if name_score < 0.82:
        return MatchDecision(
            fixture_event_id=fixture["event_id"],
            odds_event_id=best_event["id"],
            status="ambiguous",
            score=round(best_score, 4),
            reason="Ressemblance des noms insuffisante pour valider automatiquement.",
        )
    if len(candidates) > 1 and best_score - candidates[1][0] < 0.04:
        return MatchDecision(
            fixture_event_id=fixture["event_id"],
            odds_event_id=best_event["id"],
            status="ambiguous",
            score=round(best_score, 4),
            reason="Deux candidats sont trop proches.",
        )
    return MatchDecision(
        fixture_event_id=fixture["event_id"],
        odds_event_id=best_event["id"],
        status="matched",
        score=round(best_score, 4),
        reason="Équipes et horaire compatibles.",
    )
