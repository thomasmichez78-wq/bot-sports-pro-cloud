from __future__ import annotations

from enum import StrEnum


class Sport(StrEnum):
    FOOTBALL = "football"
    TENNIS = "tennis"
    BASKETBALL = "basketball"
    RUGBY = "rugby"
    NFL = "nfl"
    NHL = "nhl"


class Market(StrEnum):
    HOME_DRAW_AWAY = "1n2"
    REGULATION_HOME_DRAW_AWAY = "1n2_regulation"
    MONEYLINE = "moneyline"
    DOUBLE_CHANCE = "double_chance"
    HANDICAP = "handicap"
    TOTAL = "total"
    WIN_A_SET = "win_a_set"
    ACES = "aces"
    ANYTIME_SCORER = "anytime_scorer"
    ANYTIME_TRY_SCORER = "anytime_try_scorer"
    ANYTIME_TOUCHDOWN = "anytime_touchdown"


class SelectionStatus(StrEnum):
    VALIDATED = "validated"
    OPPORTUNITY = "opportunity"
    ODDS_TO_CHECK = "odds_to_check"
    FUN_BET = "fun_bet"
    NO_BET = "no_bet"


class Confidence(StrEnum):
    HIGH = "high"
    CORRECT = "correct"
    LOW = "low"
    INSUFFICIENT_DATA = "insufficient_data"
