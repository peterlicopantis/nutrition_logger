"""Fresh clones seed local foods without replacing personalized data."""
import json
import unittest
from unittest.mock import patch
import test_daily_foods as daily_tests
import app as melb


class LocalLibraryTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def test_missing_local_files_are_seeded_and_categories_derived(self):
        starter = self.foods_path.with_name("foods.default.json")
        starter.write_text(json.dumps(self.foods), encoding="utf-8")
        self.foods_path.unlink()
        self.foods_path.with_name("categories.json").unlink()
        with patch.object(melb, "DEFAULT_FOODS_PATH", starter):
            with melb.db() as conn:
                conn.execute("DELETE FROM food_library_versions")
            melb.init_db()
            self.assertEqual(set(melb.load_foods()), set(self.foods))
            self.assertEqual(melb.load_categories(), ["Dawg Bowl"])
            self.assertEqual(self.client.get("/foods").status_code, 200)
            self.assertEqual(self.client.get("/").status_code, 200)
        self.assertTrue(self.foods_path.exists())

    def test_existing_library_and_empty_library_are_never_replaced(self):
        missing_starter = self.foods_path.with_name("does-not-exist.json")
        with patch.object(melb, "DEFAULT_FOODS_PATH", missing_starter):
            before = self.foods_path.read_bytes()
            self.assertIn("Regular food", melb.load_foods())
            self.assertEqual(self.foods_path.read_bytes(), before)
            self.foods_path.write_text("{}", encoding="utf-8")
            self.assertEqual(melb.load_foods(), {})
            self.assertEqual(self.foods_path.read_text(encoding="utf-8"), "{}")
