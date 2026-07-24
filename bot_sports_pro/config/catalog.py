from __future__ import annotations

from bot_sports_pro.core.enums import Market, Sport

ENABLED_SPORTS: tuple[Sport, ...] = (Sport.FOOTBALL,)

MARKETS_BY_SPORT: dict[Sport, tuple[Market, ...]] = {
    Sport.FOOTBALL: (
        Market.HOME_DRAW_AWAY,
        Market.DOUBLE_CHANCE,
        Market.TOTAL,
        Market.ANYTIME_SCORER,
    ),
    Sport.TENNIS: (Market.MONEYLINE, Market.WIN_A_SET, Market.ACES),
    Sport.BASKETBALL: (Market.MONEYLINE, Market.HANDICAP, Market.TOTAL),
    Sport.RUGBY: (
        Market.HOME_DRAW_AWAY,
        Market.HANDICAP,
        Market.TOTAL,
        Market.ANYTIME_TRY_SCORER,
    ),
    Sport.NFL: (
        Market.MONEYLINE,
        Market.HANDICAP,
        Market.TOTAL,
        Market.ANYTIME_TOUCHDOWN,
    ),
    Sport.NHL: (
        Market.MONEYLINE,
        Market.REGULATION_HOME_DRAW_AWAY,
        Market.DOUBLE_CHANCE,
        Market.TOTAL,
        Market.ANYTIME_SCORER,
    ),
}
