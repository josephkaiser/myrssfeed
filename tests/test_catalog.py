import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from myrssfeed.services import catalog


class CatalogCategoryNormalizationTests(unittest.TestCase):
    def test_normalize_catalog_category_collapses_ai_ml_aliases(self):
        self.assertEqual(catalog.normalize_catalog_category("AI/ML"), "AI/ML")
        self.assertEqual(
            catalog.normalize_catalog_category("Artificial Intelligence & Machine Learning"),
            "AI/ML",
        )
        self.assertEqual(catalog.normalize_catalog_category(" aiml "), "AI/ML")

    def test_normalize_catalog_categories_in_db_updates_existing_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE feeds (category TEXT)")
        conn.execute("CREATE TABLE user_catalog (category TEXT)")
        conn.execute(
            "INSERT INTO feeds (category) VALUES (?)",
            ("Artificial Intelligence & Machine Learning",),
        )
        conn.execute("INSERT INTO user_catalog (category) VALUES (?)", ("aiml",))

        catalog.normalize_catalog_categories_in_db(conn)

        feed_category = conn.execute("SELECT category FROM feeds").fetchone()[0]
        user_category = conn.execute("SELECT category FROM user_catalog").fetchone()[0]
        self.assertEqual(feed_category, "AI/ML")
        self.assertEqual(user_category, "AI/ML")


if __name__ == "__main__":
    unittest.main()
