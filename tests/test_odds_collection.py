from __future__ import annotations

import unittest

from bot_sports_pro.services.odds_collection import _normalize_h2h_prices


class OddsCollectionTests(unittest.TestCase):
    def test_normalizes_low_decimal_odds_without_filtering(self) -> None:
        payloads = [
            (
                "soccer_test",
                [
                    {
                        "id": "odds-1",
                        "commence_time": "2026-07-23T18:00:00Z",
                        "home_team": "A",
                        "away_team": "B",
                        "bookmakers": [
                            {
                                "key": "book",
                                "title": "Book",
                                "markets": [
                                    {
                                        "key": "h2h",
                                        "last_update": "2026-07-23T10:00:00Z",
                                        "outcomes": [
                                            {"name": "A", "price": 1.20},
                                            {"name": "Draw", "price": 4.0},
                                            {"name": "B", "price": 8.0},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            )
        ]

        prices, rejected, events = _normalize_h2h_prices(
            payloads,
            {"odds-1": "api-football:1"},
        )

        self.assertEqual(rejected, [])
        self.assertEqual(len(prices), 3)
        self.assertEqual(prices[0]["decimal_price"], 1.20)
        self.assertEqual(events, {"odds-1"})


if __name__ == "__main__":
    unittest.main()
