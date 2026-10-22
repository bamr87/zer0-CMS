"""Tests for tools/check_absorption.py — the ADR 0006 gate.

Each test pins one way the absorption can go wrong silently: Ruby added in a
new place, Ruby growing under an old one, a directory deleted before its
capabilities moved, a capability marked done with nothing proving it, or one
dropped without the owner's word. Run: `python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_absorption", Path(__file__).resolve().parent.parent / "check_absorption.py"
)
ca = importlib.util.module_from_spec(_spec)
sys.modules["check_absorption"] = ca
_spec.loader.exec_module(ca)


def heads(mapping: dict[str, bytes]):
    return lambda path: mapping.get(path, b"")


class IsRubyTest(unittest.TestCase):
    def test_extensions_and_names(self):
        h = heads({})
        for path in ("a/b.rb", "x.rake", "config.ru", "v.html.erb", "g.gemspec", "s/Gemfile", "Gemfile.lock", "Rakefile", ".ruby-version"):
            self.assertTrue(ca.is_ruby(path, h), path)
        for path in ("a.py", "Gemfile.md", "README", "x.rbs.txt"):
            self.assertFalse(ca.is_ruby(path, h), path)

    def test_shebang_only_for_extensionless_files(self):
        h = heads({"bin/zer0": b"#!/usr/bin/env ruby\n", "bin/tool": b"#!/usr/bin/env python3\n", "x.sh": b"#!/usr/bin/env ruby\n"})
        self.assertTrue(ca.is_ruby("bin/zer0", h))
        self.assertFalse(ca.is_ruby("bin/tool", h))
        self.assertFalse(ca.is_ruby("x.sh", h))


class RatchetTest(unittest.TestCase):
    def test_within_ceiling_passes(self):
        errors, counts = ca.check_ratchet(["rails/a.rb", "rails/b.rb"], {"rails/": 2})
        self.assertEqual(errors, [])
        self.assertEqual(counts["rails/"], 2)

    def test_growth_fails(self):
        errors, _ = ca.check_ratchet(["rails/a.rb", "rails/b.rb"], {"rails/": 1})
        self.assertEqual(len(errors), 1)
        self.assertIn("grew", errors[0])

    def test_new_place_fails(self):
        errors, _ = ca.check_ratchet(["content/x.rb"], {"rails/": 5})
        self.assertIn("outside the ratchet", errors[0])

    def test_prefix_matches_whole_segments_and_longest_wins(self):
        self.assertIsNone(ca.owning_prefix("railsy/a.rb", ["rails/"]))
        self.assertEqual(ca.owning_prefix("rails/lib/a.rb", ["rails/", "rails/lib/"]), "rails/lib/")
        self.assertEqual(ca.owning_prefix("bin/zer0", ["bin/zer0"]), "bin/zer0")

    def test_tighten_never_raises_and_drops_zeroes(self):
        self.assertEqual(ca.tighten({"a/": 5, "b/": 2, "c/": 3}, Counter({"a/": 3, "b/": 4})), {"a/": 3, "b/": 2})

    def test_write_ratchet_rewrites_only_its_block(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.yml"
            p.write_text("schema: capabilities/v1\n# keep me\nruby_ratchet:\n  a/: 5\n  b/: 2\n\nsources: []\n")
            ca.write_ratchet(p, {"a/": 3})
            self.assertEqual(p.read_text(), "schema: capabilities/v1\n# keep me\nruby_ratchet:\n  a/: 3\n\nsources: []\n")


def source(path="apps/x", **cap):
    base = {"id": "x.one", "status": "missing", "target": "content/x"}
    base.update(cap)
    return {"id": "x", "path": path, "capabilities": [base]}


class LedgerTest(unittest.TestCase):
    def test_open_capability_with_source_present_passes(self):
        self.assertEqual(ca.check_ledger([source()], lambda p: True), [])

    def test_deleted_source_with_open_capability_fails(self):
        errors = ca.check_ledger([source()], lambda p: False)
        self.assertEqual(len(errors), 1)
        self.assertIn("is gone", errors[0])

    def test_deleted_source_fully_absorbed_passes(self):
        exists = lambda p: p == "content/tests/test_x.py"
        self.assertEqual(ca.check_ledger([source(status="done", proof="content/tests/test_x.py::test_it")], exists), [])

    def test_done_needs_existing_proof(self):
        self.assertIn("without a proof", ca.check_ledger([source(status="done")], lambda p: True)[0])
        self.assertIn("does not exist", ca.check_ledger([source(status="done", proof="nope.py")], lambda p: p == "apps/x")[0])

    def test_dropped_needs_owner(self):
        self.assertIn("decided_by", ca.check_ledger([source(status="dropped")], lambda p: True)[0])
        self.assertEqual(ca.check_ledger([source(status="dropped", decided_by="ADR 0006")], lambda p: True), [])

    def test_bad_status_missing_target_and_duplicates(self):
        self.assertIn("status", ca.check_ledger([source(status="later")], lambda p: True)[0])
        self.assertIn("no target", ca.check_ledger([source(target="")], lambda p: True)[0])
        twice = source()
        twice["capabilities"].append(dict(twice["capabilities"][0]))
        self.assertIn("duplicate", ca.check_ledger([twice], lambda p: True)[0])


class LedgerTargetTest(unittest.TestCase):
    def test_target_must_be_a_platform_capability(self):
        self.assertIn("not a platform capability", ca.check_ledger([source()], lambda p: True, {"other"})[0])
        self.assertEqual(ca.check_ledger([source()], lambda p: True, {"content/x"}), [])

    def test_dropped_rows_need_no_live_target(self):
        self.assertEqual(ca.check_ledger([source(status="dropped", decided_by="owner")], lambda p: True, set()), [])


def platform_cap(**surfaces):
    return {"id": "content.create", "what": "create pages", "surfaces": surfaces or {"studio": "missing"}}


class PlatformTest(unittest.TestCase):
    def test_valid_catalog_passes(self):
        self.assertEqual(ca.check_platform([platform_cap(studio="missing", api="partial")], lambda p: True), [])

    def test_unknown_surface_and_status_fail(self):
        errors = ca.check_platform([platform_cap(desktop="done", studio="soon")], lambda p: True)
        self.assertTrue(any("unknown surface" in e for e in errors))
        self.assertTrue(any("status 'soon'" in e for e in errors))

    def test_done_surface_needs_existing_proof(self):
        cap = platform_cap(api="done")
        self.assertIn("without a proof", ca.check_platform([cap], lambda p: True)[0])
        cap["proof"] = {"api": "content/tests/test_api.py::test_create"}
        self.assertEqual(ca.check_platform([cap], lambda p: p == "content/tests/test_api.py"), [])
        self.assertIn("does not exist", ca.check_platform([cap], lambda p: False)[0])

    def test_duplicates_and_missing_fields(self):
        errors = ca.check_platform([platform_cap(), platform_cap(), {"id": "x"}], lambda p: True)
        self.assertTrue(any("duplicate" in e for e in errors))
        self.assertTrue(any("no what" in e for e in errors))
        self.assertTrue(any("no surfaces" in e for e in errors))

    def test_parity_gaps_compare_studio_and_extension_only(self):
        caps = [platform_cap(studio="done", extension="missing"), dict(platform_cap(studio="done"), id="b"), dict(platform_cap(studio="partial", extension="partial"), id="c")]
        self.assertEqual(ca.parity_gaps(caps), ["content.create: studio done, extension missing"])


class FixtureTest(unittest.TestCase):
    def test_listed_fixture_must_exist(self):
        self.assertEqual(ca.check_fixtures(["a/Gemfile"], lambda p: True), [])
        self.assertIn("does not exist", ca.check_fixtures(["a/Gemfile"], lambda p: False)[0])


if __name__ == "__main__":
    unittest.main()
