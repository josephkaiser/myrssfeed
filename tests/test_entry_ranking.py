import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


def _install_fastapi_stub() -> None:
    fastapi = _ensure_module("fastapi")

    class Request:
        pass

    fastapi.Request = Request


_install_fastapi_stub()


from myrssfeed.services.entries.ranking import annotate_entries_for_ranking


class EntryRankingSignalTests(unittest.TestCase):
    def test_richer_metadata_gets_more_confident_rank(self):
        rows = [
            {
                "id": 1,
                "feed_id": 10,
                "title": "Market update",
                "summary": "Stocks fell.",
                "link": "https://alpha.example/a",
                "quality_score": 0.62,
                "assessment_label": "normal",
                "score": 0.0,
                "liked": 0,
            },
            {
                "id": 2,
                "feed_id": 10,
                "title": "Market update and policy reaction from central banks",
                "summary": (
                    "Stocks fell after a volatile session, but bond markets steadied as traders "
                    "reassessed rate expectations. Analysts said the move reflected both policy "
                    "uncertainty and stronger demand for safer assets."
                ),
                "link": "https://alpha.example/b",
                "og_image_url": "https://alpha.example/img.jpg",
                "quality_score": 0.62,
                "assessment_label": "normal",
                "score": 0.0,
                "liked": 0,
            },
        ]

        ranked = annotate_entries_for_ranking(rows, feed_stats={}, global_stats={"liked_count": 0})

        self.assertGreater(ranked[1]["metadata_confidence"], ranked[0]["metadata_confidence"])
        self.assertGreater(ranked[1]["base_rank"], ranked[0]["base_rank"])

    def test_feed_prior_breaks_ties_toward_consistent_source(self):
        rows = [
            {
                "id": 1,
                "feed_id": 10,
                "title": "Daily briefing",
                "summary": "A concise but complete market roundup with policy context and sector moves.",
                "link": "https://alpha.example/a",
                "quality_score": 0.55,
                "assessment_label": "normal",
                "score": 0.0,
                "liked": 0,
            },
            {
                "id": 2,
                "feed_id": 20,
                "title": "Daily briefing",
                "summary": "A concise but complete market roundup with policy context and sector moves.",
                "link": "https://beta.example/a",
                "quality_score": 0.55,
                "assessment_label": "normal",
                "score": 0.0,
                "liked": 0,
            },
        ]
        feed_stats = {
            10: {
                "feed_id": 10,
                "entry_count": 18,
                "quality_count": 18,
                "avg_quality": 0.82,
                "recent_quality_count": 6,
                "recent_quality": 0.86,
                "avg_score": 0.0,
                "like_rate": 0.05,
            },
            20: {
                "feed_id": 20,
                "entry_count": 18,
                "quality_count": 18,
                "avg_quality": 0.24,
                "recent_quality_count": 6,
                "recent_quality": 0.22,
                "avg_score": 0.0,
                "like_rate": 0.0,
            },
        }
        global_stats = {
            "liked_count": 0,
            "avg_quality": 0.5,
            "avg_score": 0.0,
            "like_rate": 0.02,
        }

        ranked = annotate_entries_for_ranking(rows, feed_stats=feed_stats, global_stats=global_stats)

        self.assertGreater(ranked[0]["feed_prior"], ranked[1]["feed_prior"])
        self.assertGreater(ranked[0]["base_rank"], ranked[1]["base_rank"])

    def test_zero_wordrank_is_neutral_when_no_likes_exist(self):
        rows = [
            {
                "id": 1,
                "feed_id": 10,
                "title": "Solid article",
                "summary": "A detailed summary with enough context to look trustworthy and useful.",
                "link": "https://alpha.example/a",
                "quality_score": 0.66,
                "assessment_label": "normal",
                "score": 0.0,
                "liked": 0,
            },
            {
                "id": 2,
                "feed_id": 10,
                "title": "Solid article",
                "summary": "A detailed summary with enough context to look trustworthy and useful.",
                "link": "https://alpha.example/b",
                "quality_score": 0.66,
                "assessment_label": "normal",
                "score": 0.95,
                "liked": 0,
            },
        ]

        ranked = annotate_entries_for_ranking(rows, feed_stats={}, global_stats={"liked_count": 0})

        self.assertAlmostEqual(ranked[0]["base_rank"], ranked[1]["base_rank"], places=6)


if __name__ == "__main__":
    unittest.main()
