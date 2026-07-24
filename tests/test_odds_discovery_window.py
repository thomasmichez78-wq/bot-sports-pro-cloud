from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from bot_sports_pro.services.odds_discovery import discovery_window_utc


class OddsDiscoveryWindowTests(unittest.TestCase):
    def test_converts_paris_calendar_dates_to_exact_utc_window(self) -> None:
        start, end = discovery_window_utc(
            (date(2026, 7, 23), date(2026, 7, 24)),
            "Europe/Paris",
        )

        self.assertEqual(start, datetime(2026, 7, 22, 22, 0, 0, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 7, 24, 21, 59, 59, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
