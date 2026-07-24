from __future__ import annotations

import unittest
from pathlib import Path

from bot_sports_pro.services.odds_discovery import OddsDiscoveryReport


class OddsDiscoveryReportTests(unittest.TestCase):
    def test_separates_fixture_and_provider_coverage(self) -> None:
        report = OddsDiscoveryReport(
            active_competitions=36,
            provider_events=33,
            fixtures=410,
            matched=13,
            ambiguous=0,
            unmatched=397,
            provider_matched=13,
            provider_unmatched=20,
            failed_competitions=(),
            report_file=Path("report.json"),
        )

        text = report.to_text()

        self.assertIn("Couverture univers brut        : 3.2%", text)
        self.assertIn("Couverture fournisseur         : 39.4%", text)
        self.assertIn("Événements fournisseur orphelins: 20", text)


if __name__ == "__main__":
    unittest.main()
