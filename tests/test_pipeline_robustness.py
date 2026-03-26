import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


def _install_apscheduler_stubs() -> None:
    apscheduler = _ensure_module("apscheduler")
    apscheduler.__path__ = []  # type: ignore[attr-defined]

    schedulers = _ensure_module("apscheduler.schedulers")
    schedulers.__path__ = []  # type: ignore[attr-defined]
    background = _ensure_module("apscheduler.schedulers.background")

    triggers = _ensure_module("apscheduler.triggers")
    triggers.__path__ = []  # type: ignore[attr-defined]
    cron = _ensure_module("apscheduler.triggers.cron")
    interval = _ensure_module("apscheduler.triggers.interval")

    class BackgroundScheduler:
        def __init__(self, *args, **kwargs):
            self.jobs = []

        def add_job(self, *args, **kwargs):
            self.jobs.append((args, kwargs))

        def remove_job(self, *args, **kwargs):
            return None

        def start(self):
            return None

        def shutdown(self, *args, **kwargs):
            return None

    class CronTrigger:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class IntervalTrigger:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    background.BackgroundScheduler = BackgroundScheduler
    cron.CronTrigger = CronTrigger
    interval.IntervalTrigger = IntervalTrigger
    apscheduler.schedulers = schedulers
    apscheduler.triggers = triggers
    schedulers.background = background
    triggers.cron = cron
    triggers.interval = interval


def _install_feedparser_stub() -> None:
    feedparser = _ensure_module("feedparser")

    def parse(*args, **kwargs):
        raise RuntimeError("feedparser.parse should not be called in helper tests")

    feedparser.parse = parse


def _install_uvicorn_stub() -> None:
    uvicorn = _ensure_module("uvicorn")

    def run(*args, **kwargs):
        return None

    uvicorn.run = run


def _install_fastapi_stub() -> None:
    fastapi = _ensure_module("fastapi")
    fastapi.__path__ = []  # type: ignore[attr-defined]
    responses = _ensure_module("fastapi.responses")
    staticfiles = _ensure_module("fastapi.staticfiles")
    templating = _ensure_module("fastapi.templating")
    pydantic = _ensure_module("pydantic")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail or "")
            self.status_code = status_code
            self.detail = detail

    class Request:
        pass

    class HTMLResponse:
        pass

    class FastAPI:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.routes = []

        def mount(self, *args, **kwargs):
            self.routes.append(("mount", args, kwargs))

        def _decorator(self, *args, **kwargs):
            def wrapper(func):
                self.routes.append(("route", args, kwargs, func.__name__))
                return func

            return wrapper

        get = post = patch = delete = _decorator

    class StaticFiles:
        def __init__(self, directory):
            self.directory = directory

    class _TemplateResponse:
        def __init__(self, template_name, context):
            self.template_name = template_name
            self.context = context

    class Jinja2Templates:
        def __init__(self, directory):
            self.directory = directory

        def TemplateResponse(self, template_name, context):
            return _TemplateResponse(template_name, context)

    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def model_dump(self, exclude_none=False):
            data = dict(self.__dict__)
            if exclude_none:
                data = {k: v for k, v in data.items() if v is not None}
            return data

    class HttpUrl(str):
        pass

    fastapi.FastAPI = FastAPI
    fastapi.HTTPException = HTTPException
    fastapi.Request = Request
    responses.HTMLResponse = HTMLResponse
    staticfiles.StaticFiles = StaticFiles
    templating.Jinja2Templates = Jinja2Templates
    pydantic.BaseModel = BaseModel
    pydantic.HttpUrl = HttpUrl


_install_feedparser_stub()
_install_apscheduler_stubs()
_install_uvicorn_stub()
_install_fastapi_stub()

compile_feed = importlib.import_module("scripts.compile_feed")
scheduler = importlib.import_module("scripts.scheduler")
main = importlib.import_module("main")
helpers = importlib.import_module("utils.helpers")
quality_score = importlib.import_module("scripts.quality_score")
newsletter_ingest = importlib.import_module("scripts.newsletter_ingest")


class CompileFeedHelperTests(unittest.TestCase):
    def test_normalize_link_strips_fragment_and_whitespace(self):
        self.assertEqual(
            compile_feed._normalize_link("  https://example.com/article#section  "),
            "https://example.com/article",
        )

    def test_normalize_link_truncates_very_long_urls(self):
        url = "https://example.com/" + ("a" * 5000)
        normalized = compile_feed._normalize_link(url)
        self.assertIsNotNone(normalized)
        self.assertLessEqual(len(normalized), 2048)

    def test_normalize_text_strips_and_truncates(self):
        self.assertEqual(compile_feed._normalize_text("  hello world  ", max_len=20), "hello world")
        self.assertEqual(compile_feed._normalize_text("abcdef", max_len=3), "abc")
        self.assertEqual(compile_feed._normalize_text(None), "")

    def test_parse_date_prefers_feedparser_tuple(self):
        iso = compile_feed._parse_date(None, (2024, 1, 15, 12, 30, 0, 0, 0, 0))
        self.assertEqual(iso, "2024-01-15T12:30:00+00:00")


class PipelineContinuationTests(unittest.TestCase):
    def setUp(self):
        self._orig_exception = scheduler.logger.exception
        scheduler.logger.exception = lambda *args, **kwargs: None

    def tearDown(self):
        scheduler.logger.exception = self._orig_exception

    def test_pipeline_continues_after_stage_failure(self):
        calls = []

        def failing_compile():
            calls.append("compile_feed")
            raise RuntimeError("boom")

        def make_stage(name):
            def run_stage():
                calls.append(name)

            return run_stage

        stages = [
            ("compile_feed", failing_compile),
            ("newsletter_ingest", make_stage("newsletter_ingest")),
            ("metadata_enrichment", make_stage("metadata_enrichment")),
            ("wordrank", make_stage("wordrank")),
            ("quality_score", make_stage("quality_score")),
            ("visualization", make_stage("visualization")),
        ]

        had_error = scheduler._run_pipeline_stages(stages)

        self.assertTrue(had_error)
        self.assertEqual(calls, ["compile_feed", "newsletter_ingest", "metadata_enrichment", "wordrank", "quality_score", "visualization"])

    def test_pipeline_marks_success_when_all_stages_pass(self):
        calls = []

        def make_stage(name):
            def run_stage():
                calls.append(name)

            return run_stage

        stages = [
            ("compile_feed", make_stage("compile_feed")),
            ("newsletter_ingest", make_stage("newsletter_ingest")),
            ("metadata_enrichment", make_stage("metadata_enrichment")),
            ("wordrank", make_stage("wordrank")),
            ("quality_score", make_stage("quality_score")),
            ("visualization", make_stage("visualization")),
        ]

        had_error = scheduler._run_pipeline_stages(stages)

        self.assertFalse(had_error)
        self.assertEqual(calls, ["compile_feed", "newsletter_ingest", "metadata_enrichment", "wordrank", "quality_score", "visualization"])


class PipelineIntervalScheduleTests(unittest.TestCase):
    def setUp(self):
        self._orig_main_db_file = main.DB_FILE
        self._orig_helpers_db_file = helpers.DB_FILE
        self._tmpdir = TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "rss.db")
        main.DB_FILE = db_path
        helpers.DB_FILE = db_path
        main.init_db()

    def tearDown(self):
        main.DB_FILE = self._orig_main_db_file
        helpers.DB_FILE = self._orig_helpers_db_file
        self._tmpdir.cleanup()

    def test_defaults_to_fifteen_minutes(self):
        self.assertEqual(scheduler._parse_pipeline_refresh_minutes(), 15)

    def test_legacy_daily_schedule_maps_to_daily_interval(self):
        helpers.set_setting("pipeline_schedule_frequency", "daily")
        helpers.set_setting("pipeline_schedule_time", "06:00")

        self.assertEqual(scheduler._parse_pipeline_refresh_minutes(), 1440)

    def test_new_interval_setting_wins_over_legacy_values(self):
        helpers.set_setting("pipeline_schedule_frequency", "daily")
        helpers.set_setting("pipeline_refresh_minutes", "45")

        self.assertEqual(scheduler._parse_pipeline_refresh_minutes(), 45)


class FeedDiversityRankingTests(unittest.TestCase):
    def setUp(self):
        self._orig_db_file = main.DB_FILE
        self._tmpdir = TemporaryDirectory()
        main.DB_FILE = str(Path(self._tmpdir.name) / "rss.db")
        main.init_db()
        self.request = SimpleNamespace(cookies={})

    def tearDown(self):
        main.DB_FILE = self._orig_db_file
        self._tmpdir.cleanup()

    def _insert_feed(self, conn, url: str, title: str) -> int:
        cur = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            (url, title),
        )
        return int(cur.lastrowid)

    def _insert_entry(
        self,
        conn,
        feed_id: int,
        title: str,
        published: datetime,
        *,
        score: float = 0.5,
        quality_score: float = 0.5,
    ) -> None:
        slug = title.lower().replace(" ", "-")
        conn.execute(
            """
            INSERT INTO entries (
                feed_id, title, link, published, summary, score, quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feed_id,
                title,
                f"https://example.com/{slug}",
                published.isoformat(),
                f"Summary for {title}",
                score,
                quality_score,
            ),
        )

    def test_spammy_feed_is_interleaved_by_source_diversity(self):
        conn = main.get_db()
        spam_id = self._insert_feed(conn, "https://spam.example/rss", "Spammy Source")
        other_ids = [
            self._insert_feed(conn, "https://alpha.example/rss", "Alpha"),
            self._insert_feed(conn, "https://beta.example/rss", "Beta"),
            self._insert_feed(conn, "https://gamma.example/rss", "Gamma"),
        ]

        base = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        for idx in range(5):
            self._insert_entry(
                conn,
                spam_id,
                f"Spam Post {idx}",
                base - timedelta(minutes=idx),
            )
        for idx, feed_id in enumerate(other_ids):
            self._insert_entry(
                conn,
                feed_id,
                f"Other Post {idx}",
                base - timedelta(minutes=10 + idx),
            )
        conn.commit()
        conn.close()

        entries = main.list_entries(self.request, limit=8, offset=0)
        top_four_feed_ids = [entry["feed_id"] for entry in entries[:4]]

        self.assertGreaterEqual(len(set(top_four_feed_ids)), 3)
        self.assertLessEqual(top_four_feed_ids.count(spam_id), 2)

    def test_same_provider_domain_does_not_repeat_three_times(self):
        conn = main.get_db()
        provider_ids = [
            self._insert_feed(conn, "https://provider.example/a/rss", "Provider A"),
            self._insert_feed(conn, "https://provider.example/b/rss", "Provider B"),
            self._insert_feed(conn, "https://provider.example/c/rss", "Provider C"),
        ]
        other_ids = [
            self._insert_feed(conn, "https://alpha.example/rss", "Alpha"),
            self._insert_feed(conn, "https://beta.example/rss", "Beta"),
            self._insert_feed(conn, "https://gamma.example/rss", "Gamma"),
        ]

        base = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        for idx, feed_id in enumerate(provider_ids):
            for post_idx in range(3):
                self._insert_entry(
                    conn,
                    feed_id,
                    f"Provider {idx} Post {post_idx}",
                    base - timedelta(minutes=(idx * 2) + post_idx),
                    score=0.95,
                    quality_score=0.9,
                )
        for idx, feed_id in enumerate(other_ids):
            self._insert_entry(
                conn,
                feed_id,
                f"Other Post {idx}",
                base - timedelta(minutes=20 + idx),
                score=0.4,
                quality_score=0.4,
            )
        conn.commit()
        conn.close()

        entries = main.list_entries(self.request, limit=6, offset=0)
        domains = [entry["feed_domain"] for entry in entries[:6]]

        max_run = 1
        run = 1
        for prev, curr in zip(domains, domains[1:]):
            run = run + 1 if curr == prev else 1
            max_run = max(max_run, run)

        self.assertLessEqual(max_run, 2)

    def test_today_items_stay_at_the_top(self):
        conn = main.get_db()
        today_ids = [
            self._insert_feed(conn, "https://today-a.example/rss", "Today A"),
            self._insert_feed(conn, "https://today-b.example/rss", "Today B"),
            self._insert_feed(conn, "https://today-c.example/rss", "Today C"),
            self._insert_feed(conn, "https://today-d.example/rss", "Today D"),
        ]
        older_ids = [
            self._insert_feed(conn, "https://old-a.example/rss", "Old A"),
            self._insert_feed(conn, "https://old-b.example/rss", "Old B"),
            self._insert_feed(conn, "https://old-c.example/rss", "Old C"),
            self._insert_feed(conn, "https://old-d.example/rss", "Old D"),
        ]

        today = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        older = today - timedelta(days=1)

        for idx, feed_id in enumerate(today_ids):
            self._insert_entry(
                conn,
                feed_id,
                f"Today Post {idx}",
                today - timedelta(minutes=idx),
                score=0.4,
                quality_score=0.4,
            )

        for idx, feed_id in enumerate(older_ids):
            self._insert_entry(
                conn,
                feed_id,
                f"Older Post {idx}",
                older - timedelta(minutes=idx),
                score=0.99,
                quality_score=0.99,
            )

        conn.commit()
        conn.close()

        entries = main.list_entries(self.request, limit=8, offset=0)
        top_four_days = [entry["published"][:10] for entry in entries[:4]]

        self.assertTrue(all(day == "2026-03-17" for day in top_four_days))

    def test_random_seed_is_stable_until_reseeded(self):
        conn = main.get_db()
        feed_ids = [
            self._insert_feed(conn, "https://seed-a.example/rss", "Seed A"),
            self._insert_feed(conn, "https://seed-b.example/rss", "Seed B"),
            self._insert_feed(conn, "https://seed-c.example/rss", "Seed C"),
            self._insert_feed(conn, "https://seed-d.example/rss", "Seed D"),
        ]

        stamp = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        for idx, feed_id in enumerate(feed_ids):
            for post_idx in range(2):
                self._insert_entry(
                    conn,
                    feed_id,
                    f"Seed Post {idx}-{post_idx}",
                    stamp,
                    score=0.5,
                    quality_score=0.5,
                )
        conn.commit()
        conn.close()

        seed_one = SimpleNamespace(cookies={"myrssfeed_random_seed": "12345"})
        seed_two = SimpleNamespace(cookies={"myrssfeed_random_seed": "67890"})

        first = [entry["id"] for entry in main.list_entries(seed_one, limit=8, offset=0)]
        second = [entry["id"] for entry in main.list_entries(seed_one, limit=8, offset=0)]
        rerolled = [entry["id"] for entry in main.list_entries(seed_two, limit=8, offset=0)]
        index_ids = [entry["id"] for entry in main.index(seed_one).context["entries"]]

        self.assertEqual(first, second)
        self.assertEqual(index_ids, first)
        self.assertNotEqual(first, rerolled)

    def test_initial_render_matches_paged_api_order(self):
        conn = main.get_db()
        feed_ids = [
            self._insert_feed(conn, "https://delta.example/rss", "Delta"),
            self._insert_feed(conn, "https://epsilon.example/rss", "Epsilon"),
            self._insert_feed(conn, "https://zeta.example/rss", "Zeta"),
        ]

        base = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        published_offsets = [0, 1, 2, 10, 11, 12]
        feed_cycle = [feed_ids[0], feed_ids[0], feed_ids[1], feed_ids[1], feed_ids[2], feed_ids[2]]
        for idx, (feed_id, minutes) in enumerate(zip(feed_cycle, published_offsets)):
            self._insert_entry(
                conn,
                feed_id,
                f"Article {idx}",
                base - timedelta(minutes=minutes),
            )
        conn.commit()
        conn.close()

        initial_response = main.index(self.request)
        initial_ids = [entry["id"] for entry in initial_response.context["entries"]]

        page_1 = main.list_entries(self.request, limit=3, offset=0)
        page_2 = main.list_entries(self.request, limit=3, offset=3)
        combined_ids = [entry["id"] for entry in page_1 + page_2]

        self.assertEqual(initial_ids[: len(combined_ids)], combined_ids)


class FeedScopeToggleTests(unittest.TestCase):
    def setUp(self):
        self._orig_db_file = main.DB_FILE
        self._tmpdir = TemporaryDirectory()
        main.DB_FILE = str(Path(self._tmpdir.name) / "rss.db")
        main.init_db()
        self.request = SimpleNamespace(cookies={})

    def tearDown(self):
        main.DB_FILE = self._orig_db_file
        self._tmpdir.cleanup()

    def _insert_feed(self, conn, url: str, title: str, subscribed: int) -> int:
        cur = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, ?)",
            (url, title, subscribed),
        )
        return int(cur.lastrowid)

    def _insert_entry(self, conn, feed_id: int, title: str, published: datetime) -> None:
        slug = title.lower().replace(" ", "-")
        conn.execute(
            """
            INSERT INTO entries (feed_id, title, link, published, summary)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                feed_id,
                title,
                f"https://example.com/{slug}",
                published.isoformat(),
                f"Summary for {title}",
            ),
        )

    def test_my_scope_excludes_discover_only_feeds(self):
        conn = main.get_db()
        subscribed_id = self._insert_feed(conn, "https://subscribed.example/rss", "Subscribed", 1)
        hidden_id = self._insert_feed(conn, "https://hidden.example/rss", "Hidden", 0)
        catalog_url = next(iter(sorted(main._STATIC_CATALOG_URLS)), None)
        self.assertIsNotNone(catalog_url)
        catalog_id = conn.execute("SELECT id FROM feeds WHERE url = ?", (catalog_url,)).fetchone()["id"]

        published = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        self._insert_entry(conn, subscribed_id, "Subscribed Story", published)
        self._insert_entry(conn, hidden_id, "Hidden Story", published - timedelta(minutes=1))
        self._insert_entry(conn, catalog_id, "Catalog Story", published - timedelta(minutes=2))
        conn.commit()
        conn.close()

        rows = main.list_entries(self.request, scope="my", limit=10, offset=0)
        feed_ids = {row["feed_id"] for row in rows}

        self.assertIn(subscribed_id, feed_ids)
        self.assertNotIn(hidden_id, feed_ids)
        self.assertNotIn(catalog_id, feed_ids)

    def test_discover_scope_includes_catalogue_feeds(self):
        conn = main.get_db()
        subscribed_id = self._insert_feed(conn, "https://subscribed.example/rss", "Subscribed", 1)
        hidden_id = self._insert_feed(conn, "https://hidden.example/rss", "Hidden", 0)
        catalog_url = next(iter(sorted(main._STATIC_CATALOG_URLS)), None)
        self.assertIsNotNone(catalog_url)
        catalog_id = conn.execute("SELECT id FROM feeds WHERE url = ?", (catalog_url,)).fetchone()["id"]

        published = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        self._insert_entry(conn, subscribed_id, "Subscribed Story", published)
        self._insert_entry(conn, hidden_id, "Hidden Story", published - timedelta(minutes=1))
        self._insert_entry(conn, catalog_id, "Catalog Story", published - timedelta(minutes=2))
        conn.commit()
        conn.close()

        rows = main.list_entries(self.request, scope="discover", limit=10, offset=0)
        feed_ids = {row["feed_id"] for row in rows}

        self.assertIn(subscribed_id, feed_ids)
        self.assertIn(catalog_id, feed_ids)
        self.assertNotIn(hidden_id, feed_ids)

    def test_index_exposes_scope_urls(self):
        response = main.index(self.request, q="alpha", days="30", scope="discover")
        context = response.context

        self.assertEqual(context["source_scope"], "discover")
        self.assertIn("scope=my", context["my_feed_url"])
        self.assertIn("scope=discover", context["discover_feed_url"])
        self.assertIn("scope=discover", context["clear_url"])


class NewsletterIngestTests(unittest.TestCase):
    def setUp(self):
        self._orig_main_db_file = main.DB_FILE
        self._orig_helpers_db_file = helpers.DB_FILE
        self._tmpdir = TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "rss.db")
        main.DB_FILE = db_path
        helpers.DB_FILE = db_path
        main.init_db()

        self.message = EmailMessage()
        self.message["Subject"] = "Daily Briefing"
        self.message["From"] = "Newsletters <news@example.com>"
        self.message["To"] = "newsletter@example.com"
        self.message["Message-ID"] = "<abc123@example.com>"
        self.message["Date"] = "Tue, 17 Mar 2026 12:00:00 +0000"
        self.message.set_content(
            "View the newsletter online at https://example.com/newsletter"
        )
        self.message.add_alternative(
            """
            <html>
              <body>
                <p>Hello from the newsletter.</p>
                <p><a href="https://example.com/newsletter">View online</a></p>
              </body>
            </html>
            """,
            subtype="html",
        )

        helpers.set_setting("newsletter_imap_host", "imap.example.com")
        helpers.set_setting("newsletter_imap_port", "993")
        helpers.set_setting("newsletter_imap_username", "newsletter@example.com")
        helpers.set_setting("newsletter_imap_password", "secret")
        helpers.set_setting("newsletter_imap_folder", "INBOX")
        helpers.set_setting("newsletter_enabled", "true")

    def tearDown(self):
        main.DB_FILE = self._orig_main_db_file
        helpers.DB_FILE = self._orig_helpers_db_file
        self._tmpdir.cleanup()

    def test_newsletter_ingest_is_idempotent_for_repeated_messages(self):
        raw_message = self.message.as_bytes()

        class FakeIMAP:
            def __init__(self, host, port):
                self.host = host
                self.port = port

            def login(self, username, password):
                return ("OK", [b"logged in"])

            def select(self, folder):
                self.folder = folder
                return ("OK", [b"1"])

            def search(self, charset, query):
                return ("OK", [b"1"])

            def fetch(self, msg_id, query):
                return ("OK", [(b"1 (RFC822)", raw_message)])

            def close(self):
                return ("OK", [])

            def logout(self):
                return ("BYE", [])

        original_imap = newsletter_ingest.imaplib.IMAP4_SSL
        newsletter_ingest.imaplib.IMAP4_SSL = FakeIMAP
        try:
            newsletter_ingest.run_newsletter_ingest()
            newsletter_ingest.run_newsletter_ingest()
        finally:
            newsletter_ingest.imaplib.IMAP4_SSL = original_imap

        conn = main.get_db()
        feed_row = conn.execute(
            "SELECT id FROM feeds WHERE COALESCE(kind, 'rss') = 'newsletter'"
        ).fetchone()
        self.assertIsNotNone(feed_row)

        entry_rows = conn.execute(
            """
            SELECT title, link, source_uid, summary, full_content
            FROM entries
            ORDER BY id ASC
            """
        ).fetchall()
        status_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'newsletter_last_status'"
        ).fetchone()
        conn.close()

        self.assertEqual(len(entry_rows), 1)
        self.assertEqual(entry_rows[0]["title"], "Daily Briefing")
        self.assertEqual(entry_rows[0]["link"], "https://example.com/newsletter")
        self.assertEqual(entry_rows[0]["source_uid"], "abc123@example.com")
        self.assertIn("Hello from the newsletter.", entry_rows[0]["summary"])
        self.assertIn("<p>", entry_rows[0]["full_content"])
        self.assertEqual(status_row["value"], "success")

    def test_manual_newsletter_sync_runs_even_when_polling_is_disabled(self):
        raw_message = self.message.as_bytes()

        class FakeIMAP:
            def __init__(self, host, port):
                self.host = host
                self.port = port

            def login(self, username, password):
                return ("OK", [b"logged in"])

            def select(self, folder):
                self.folder = folder
                return ("OK", [b"1"])

            def search(self, charset, query):
                return ("OK", [b"1"])

            def fetch(self, msg_id, query):
                return ("OK", [(b"1 (RFC822)", raw_message)])

            def close(self):
                return ("OK", [])

            def logout(self):
                return ("BYE", [])

        helpers.set_setting("newsletter_enabled", "false")

        original_imap = newsletter_ingest.imaplib.IMAP4_SSL
        newsletter_ingest.imaplib.IMAP4_SSL = FakeIMAP
        try:
            newsletter_ingest.run_newsletter_ingest(require_enabled=False)
        finally:
            newsletter_ingest.imaplib.IMAP4_SSL = original_imap

        conn = main.get_db()
        entry_rows = conn.execute(
            """
            SELECT title, link, source_uid
            FROM entries
            ORDER BY id ASC
            """
        ).fetchall()
        status_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'newsletter_last_status'"
        ).fetchone()
        conn.close()

        self.assertEqual(len(entry_rows), 1)
        self.assertEqual(entry_rows[0]["title"], "Daily Briefing")
        self.assertEqual(status_row["value"], "success")


class QualityScoreLabelTests(unittest.TestCase):
    def setUp(self):
        self._orig_main_db_file = main.DB_FILE
        self._orig_helpers_db_file = helpers.DB_FILE
        self._tmpdir = TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "rss.db")
        main.DB_FILE = db_path
        helpers.DB_FILE = db_path
        main.init_db()

    def tearDown(self):
        main.DB_FILE = self._orig_main_db_file
        helpers.DB_FILE = self._orig_helpers_db_file
        self._tmpdir.cleanup()

    def test_run_quality_score_backfills_label_and_color(self):
        conn = main.get_db()
        feed_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://example.com/rss", "Example"),
        ).lastrowid
        conn.executemany(
            """
            INSERT INTO entries (
                feed_id, title, link, published, summary
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    feed_id,
                    "Deep Dive into Reliable RSS Pipelines and Long-Term Label Storage",
                    "https://example.com/high",
                    "2026-03-17T12:00:00+00:00",
                    "This article explains how to keep metadata compact, recomputable, and cheap to render over a very long archive."
                    " It includes deployment notes, storage tradeoffs, and practical scaling guidance for large feed collections.",
                ),
                (
                    feed_id,
                    "Click here",
                    "https://example.com/low",
                    "2026-03-17T11:00:00+00:00",
                    "Act now for a limited time offer.",
                ),
            ],
        )
        conn.commit()
        conn.close()

        quality_score.run_quality_score()

        conn = main.get_db()
        rows = conn.execute(
            """
            SELECT title, quality_score, assessment_label, assessment_label_color
            FROM entries
            ORDER BY published DESC
            """
        ).fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["assessment_label"], "high")
        self.assertEqual(rows[0]["assessment_label_color"], "#2f9e44")
        self.assertGreaterEqual(rows[0]["quality_score"], 0.72)
        self.assertEqual(rows[1]["assessment_label"], "low")
        self.assertEqual(rows[1]["assessment_label_color"], "#c92a2a")
        self.assertLess(rows[1]["quality_score"], 0.45)

    def test_run_quality_score_penalizes_tracked_links(self):
        conn = main.get_db()
        feed_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://example.com/rss", "Example"),
        ).lastrowid

        # Keep content identical; only the link differs.
        title = "Morning briefing: technology updates"
        summary = (
            "Device logs describe the new release plans for teams. "
            "Cloud engineers discuss deployment and APIs."
        )

        clean_link = "https://example.com/article"
        tracked_link = (
            "https://example.com/article?utm_source=promo&utm_medium=email&ref=abc&affiliate=999"
        )

        conn.executemany(
            """
            INSERT INTO entries (
                feed_id, title, link, published, summary
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (feed_id, title, clean_link, "2026-03-17T12:00:00+00:00", summary),
                (feed_id, title, tracked_link, "2026-03-17T11:00:00+00:00", summary),
            ],
        )
        conn.commit()
        conn.close()

        quality_score.run_quality_score()

        conn = main.get_db()
        rows = conn.execute(
            "SELECT link, quality_score FROM entries ORDER BY id ASC"
        ).fetchall()
        conn.close()

        clean_row = next(r for r in rows if r["link"] == clean_link)
        tracked_row = next(r for r in rows if r["link"] == tracked_link)

        self.assertLess(tracked_row["quality_score"], clean_row["quality_score"])
        self.assertLess(
            tracked_row["quality_score"],
            clean_row["quality_score"] - 0.05,
        )


class QualityFilterUsesQualityScoreTests(unittest.TestCase):
    def setUp(self):
        self._orig_main_db_file = main.DB_FILE
        self._orig_helpers_db_file = helpers.DB_FILE
        self._tmpdir = TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "rss.db")
        main.DB_FILE = db_path
        helpers.DB_FILE = db_path
        main.init_db()
        self.request = SimpleNamespace(cookies={})

    def tearDown(self):
        main.DB_FILE = self._orig_main_db_file
        helpers.DB_FILE = self._orig_helpers_db_file
        self._tmpdir.cleanup()

    def test_quality_level_filters_using_quality_score(self):
        conn = main.get_db()
        feed_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://example.com/rss", "Example"),
        ).lastrowid

        # Both entries have very short title/summary so they fail the old
        # length-based filter; only quality_score differentiates them.
        base_published = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        conn.executemany(
            """
            INSERT INTO entries (
                feed_id, title, link, published, summary, score, quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    feed_id,
                    "Bad",
                    "https://example.com/bad",
                    (base_published).isoformat(),
                    "No",
                    0.5,
                    0.1,
                ),
                (
                    feed_id,
                    "Good",
                    "https://example.com/good",
                    (base_published - timedelta(minutes=1)).isoformat(),
                    "Ok",
                    0.5,
                    0.9,
                ),
            ],
        )
        conn.commit()
        conn.close()

        rows = main.list_entries(self.request, limit=10, offset=0, quality_level=1)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["quality_score"], 0.35)


class QualityScoreMajorPublicationBiasTests(unittest.TestCase):
    def setUp(self):
        self._orig_main_db_file = main.DB_FILE
        self._orig_helpers_db_file = helpers.DB_FILE
        self._tmpdir = TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "rss.db")
        main.DB_FILE = db_path
        helpers.DB_FILE = db_path
        main.init_db()

    def tearDown(self):
        main.DB_FILE = self._orig_main_db_file
        helpers.DB_FILE = self._orig_helpers_db_file
        self._tmpdir.cleanup()

    def test_major_publication_boosts_quality_score(self):
        conn = main.get_db()

        wsj_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://www.wsj.com/rss", "WSJ"),
        ).lastrowid
        other_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://example.com/rss", "Example"),
        ).lastrowid

        # Identical content: only domain prior differs.
        title = "Daily market briefing analysis"
        summary = (
            "This short report covers market policy and trading activity. "
            "A second note summarizes key economic movements and coverage decisions."
        )
        link_a = "https://example.com/article-a"
        link_b = "https://example.com/article-b"
        published = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        conn.executemany(
            """
            INSERT INTO entries (
                feed_id, title, link, published, summary
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (wsj_id, title, link_a, published.isoformat(), summary),
                (other_id, title, link_b, (published - timedelta(minutes=1)).isoformat(), summary),
            ],
        )
        conn.commit()
        conn.close()

        quality_score.run_quality_score()

        conn = main.get_db()
        wsj_quality = conn.execute(
            "SELECT quality_score FROM entries WHERE feed_id = ? ORDER BY id DESC LIMIT 1",
            (wsj_id,),
        ).fetchone()["quality_score"]
        other_quality = conn.execute(
            "SELECT quality_score FROM entries WHERE feed_id = ? ORDER BY id DESC LIMIT 1",
            (other_id,),
        ).fetchone()["quality_score"]
        conn.close()

        self.assertGreater(wsj_quality, other_quality)
        self.assertGreaterEqual(wsj_quality - other_quality, 0.04)


class QualityScoreMajorSimilarityTests(unittest.TestCase):
    def setUp(self):
        self._orig_main_db_file = main.DB_FILE
        self._orig_helpers_db_file = helpers.DB_FILE
        self._tmpdir = TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "rss.db")
        main.DB_FILE = db_path
        helpers.DB_FILE = db_path
        main.init_db()
        self.request = SimpleNamespace(cookies={})

    def tearDown(self):
        main.DB_FILE = self._orig_main_db_file
        helpers.DB_FILE = self._orig_helpers_db_file
        self._tmpdir.cleanup()

    def test_similarity_signature_promotes_similar_content(self):
        conn = main.get_db()

        # Two non-major entries: one "NYT-like" (contains NYT signature token),
        # and one "not like it" (different signature token).
        wsj_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://www.wsj.com/rss", "WSJ"),
        ).lastrowid
        other_id = conn.execute(
            "INSERT INTO feeds (url, title, subscribed) VALUES (?, ?, 1)",
            ("https://example.com/rss", "Example"),
        ).lastrowid

        signature_a = "nytsignaturetoken"
        signature_b = "othersignaturetoken"

        title_common = "breaking market policy analysis"
        summary_common = (
            "This editorial covers market policy and trading activity. "
            "A second note summarizes key economic movements and coverage decisions."
        )
        link_a = "https://example.com/article-a"
        link_b = "https://example.com/article-b"
        published = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        conn.executemany(
            """
            INSERT INTO entries (
                feed_id, title, link, published, summary
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                # Major source entry establishes the signature words.
                (wsj_id, f"{signature_a} {title_common}", link_a, published.isoformat(), summary_common),
                # Similar content: contains signature_a.
                (other_id, f"{signature_a} {title_common}", link_a, (published - timedelta(minutes=1)).isoformat(), summary_common),
                # Dissimilar content: contains signature_b.
                (other_id, f"{signature_b} {title_common}", link_b, (published - timedelta(minutes=2)).isoformat(), summary_common),
            ],
        )
        conn.commit()
        conn.close()

        quality_score.run_quality_score()

        conn = main.get_db()
        sim_quality = conn.execute(
            """
            SELECT quality_score
            FROM entries
            WHERE feed_id = ?
              AND title LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (other_id, f"%{signature_a}%"),
        ).fetchone()["quality_score"]
        dissim_quality = conn.execute(
            """
            SELECT quality_score
            FROM entries
            WHERE feed_id = ?
              AND title LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (other_id, f"%{signature_b}%"),
        ).fetchone()["quality_score"]
        conn.close()

        self.assertGreater(sim_quality, dissim_quality)


if __name__ == "__main__":
    unittest.main()
