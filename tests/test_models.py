from __future__ import annotations

import unittest
from datetime import UTC, datetime

from bot_sports_pro.core.enums import Market
from bot_sports_pro.core.models import Odds, SourceStamp


class OddsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SourceStamp("test", datetime.now(UTC), 1.0)

    def test_implied_probability_for_low_odds(self) -> None:
        odds = Odds("event-1", Market.MONEYLINE, "domicile", 1.20, "test", self.source)
        self.assertAlmostEqual(odds.implied_probability, 0.8333333333)

    def test_odds_must_be_above_one(self) -> None:
        with self.assertRaises(ValueError):
            Odds("event-1", Market.MONEYLINE, "domicile", 1.0, "test", self.source)


if __name__ == "__main__":
    unittest.main()
