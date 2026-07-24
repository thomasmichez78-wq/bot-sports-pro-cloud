from __future__ import annotations

import unittest

from bot_sports_pro.matching.events import (
    match_fixture,
    normalize_team_name,
    team_similarity,
)


class EventMatchingTests(unittest.TestCase):
    def test_normalizes_accents_and_common_club_suffixes(self) -> None:
        self.assertEqual(normalize_team_name("Paris FC"), "paris")
        self.assertEqual(normalize_team_name("Équipe CF"), "equipe")
        self.assertEqual(normalize_team_name("Viborg FF"), "viborg")
        self.assertEqual(normalize_team_name("Odense BK"), "odense")

    def test_recognizes_long_and_short_official_names(self) -> None:
        equivalent_names = (
            ("SJK", "SJK Seinäjoki"),
            ("Santa Fe", "Independiente Santa Fe"),
            ("Baltika", "FC Baltika Kaliningrad"),
            ("Aldosivi", "Aldosivi Mar del Plata"),
            ("Odense", "OB Odense BK"),
        )
        for short_name, long_name in equivalent_names:
            with self.subTest(short_name=short_name, long_name=long_name):
                self.assertGreaterEqual(team_similarity(short_name, long_name), 0.88)

    def test_matches_equivalent_event(self) -> None:
        fixture = {
            "event_id": "api-football:1",
            "starts_at": "2026-07-23T20:45:00+02:00",
            "home_name": "Paris FC",
            "away_name": "Olympique Lyonnais",
        }
        odds_events = [
            {
                "id": "odds-1",
                "commence_time": "2026-07-23T18:45:00Z",
                "home_team": "Paris",
                "away_team": "Olympique Lyonnais",
            }
        ]

        decision = match_fixture(fixture, odds_events)

        self.assertEqual(decision.status, "matched")
        self.assertEqual(decision.odds_event_id, "odds-1")

    def test_does_not_match_unrelated_teams(self) -> None:
        fixture = {
            "event_id": "api-football:1",
            "starts_at": "2026-07-23T20:45:00+02:00",
            "home_name": "Paris",
            "away_name": "Lyon",
        }
        odds_events = [
            {
                "id": "odds-1",
                "commence_time": "2026-07-23T18:45:00Z",
                "home_team": "Madrid",
                "away_team": "Barcelona",
            }
        ]

        self.assertEqual(match_fixture(fixture, odds_events).status, "unmatched")

    def test_matches_verified_provider_name_variants(self) -> None:
        verified_pairs = (
            ("FF Jaro", "SJK", "Jaro", "SJK Seinäjoki"),
            ("Santa Fe", "Caracas FC", "Independiente Santa Fe", "Caracas FC"),
            ("CSKA Moscow", "Baltika", "CSKA Moscow", "FC Baltika Kaliningrad"),
            (
                "Gimnasia M.",
                "Central Cordoba de Santiago",
                "Gimnasia Mendoza",
                "Central Córdoba",
            ),
            (
                "Defensa Y Justicia",
                "Aldosivi",
                "Defensa y Justicia",
                "Aldosivi Mar del Plata",
            ),
            ("Viborg", "Odense", "Viborg FF", "OB Odense BK"),
        )
        for index, (fixture_home, fixture_away, odds_home, odds_away) in enumerate(
            verified_pairs
        ):
            with self.subTest(fixture_home=fixture_home, fixture_away=fixture_away):
                fixture = {
                    "event_id": f"api-football:{index}",
                    "starts_at": "2026-07-24T19:00:00+02:00",
                    "home_name": fixture_home,
                    "away_name": fixture_away,
                }
                odds_events = [
                    {
                        "id": f"odds-{index}",
                        "commence_time": "2026-07-24T17:00:00Z",
                        "home_team": odds_home,
                        "away_team": odds_away,
                    }
                ]
                self.assertEqual(match_fixture(fixture, odds_events).status, "matched")


if __name__ == "__main__":
    unittest.main()
