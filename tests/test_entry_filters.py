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

from myrssfeed.services import entries


class EntryReadStatusTests(unittest.TestCase):
    def test_normalize_read_status_accepts_known_values(self):
        self.assertEqual(entries.normalize_read_status("ALL"), entries.READ_STATUS_ALL)
        self.assertEqual(entries.normalize_read_status("READ"), entries.READ_STATUS_READ)
        self.assertEqual(entries.normalize_read_status(" unread "), entries.READ_STATUS_UNREAD)

    def test_normalize_read_status_defaults_to_unread(self):
        self.assertEqual(entries.normalize_read_status("reviewed"), entries.READ_STATUS_UNREAD)
        self.assertEqual(entries.normalize_read_status(None), entries.READ_STATUS_UNREAD)

    def test_build_entry_filters_adds_unread_clause(self):
        filters, params = entries.build_entry_filters(
            None,
            None,
            None,
            None,
            entries.SOURCE_SCOPE_MY,
            None,
            entries.READ_STATUS_UNREAD,
        )

        self.assertIn("COALESCE(e.read, 0) = 0", filters)
        self.assertEqual(params, [])

    def test_build_entry_filters_adds_read_clause(self):
        filters, params = entries.build_entry_filters(
            None,
            None,
            None,
            None,
            entries.SOURCE_SCOPE_MY,
            None,
            entries.READ_STATUS_READ,
        )

        self.assertIn("COALESCE(e.read, 0) = 1", filters)
        self.assertEqual(params, [])

    def test_build_entry_filters_skips_read_clause_for_all(self):
        filters, params = entries.build_entry_filters(
            None,
            None,
            None,
            None,
            entries.SOURCE_SCOPE_MY,
            None,
            entries.READ_STATUS_ALL,
        )

        self.assertNotIn("COALESCE(e.read, 0) = 0", filters)
        self.assertNotIn("COALESCE(e.read, 0) = 1", filters)
        self.assertEqual(params, [])


if __name__ == "__main__":
    unittest.main()
