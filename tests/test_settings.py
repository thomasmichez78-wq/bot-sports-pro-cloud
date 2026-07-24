from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bot_sports_pro.config.settings import AppSettings


class SettingsTests(unittest.TestCase):
    def test_loads_env_file_without_external_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "APP_TIMEZONE=Europe/Paris\nAPI_FOOTBALL_KEY=secret-test\n",
                encoding="utf-8",
            )
            settings = AppSettings.load(root)

            self.assertEqual(settings.timezone, "Europe/Paris")
            self.assertEqual(settings.api_football_key, "secret-test")
            self.assertIsNone(settings.odds_api_key)

    def test_ensure_directories_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings.load(Path(directory))
            settings.ensure_directories()
            settings.ensure_directories()
            self.assertTrue(settings.raw_dir.is_dir())
            self.assertTrue(settings.logs_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
