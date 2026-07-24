from __future__ import annotations

import unittest

from bot_sports_pro.services.odds_market_analysis import _fair_probabilities


class OddsMarketAnalysisTests(unittest.TestCase):
    def test_removes_bookmaker_margin_and_keeps_low_odds(self) -> None:
        outcomes = {
            "Home": {"decimal_price": 1.20},
            "Draw": {"decimal_price": 6.00},
            "Away": {"decimal_price": 10.00},
        }

        fair, margin = _fair_probabilities(outcomes)

        self.assertAlmostEqual(sum(fair.values()), 1.0)
        self.assertGreater(margin, 0.0)
        self.assertGreater(fair["Home"], fair["Draw"])

    def test_rejects_incomplete_one_x_two_market(self) -> None:
        with self.assertRaises(ValueError):
            _fair_probabilities(
                {
                    "Home": {"decimal_price": 1.80},
                    "Away": {"decimal_price": 2.10},
                }
            )


if __name__ == "__main__":
    unittest.main()
