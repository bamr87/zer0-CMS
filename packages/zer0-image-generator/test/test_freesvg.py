#!/usr/bin/env python3
"""Unit tests for tools/svg/freesvg.py — no network; _http is mocked."""
import base64
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "svg"))
import freesvg  # noqa: E402

GOOD_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img">'
            '<title>t</title><rect width="10" height="10"/></svg>')


def fake_jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"e30.{payload}.sig"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Isolated fake repo root with a real svg-check.py so lint subprocesses work
        os.makedirs(os.path.join(self.tmp, "tools", "svg", "library"))
        shutil.copy(os.path.join(REPO, "tools", "svg", "svg-check.py"),
                    os.path.join(self.tmp, "tools", "svg", "svg-check.py"))
        self.manifest = os.path.join(self.tmp, "tools", "svg", "library", "MANIFEST.json")
        with open(self.manifest, "w") as f:
            json.dump({"entries": []}, f)
        self.env = mock.patch.dict(os.environ, {
            "FREESVG_CACHE_DIR": os.path.join(self.tmp, "cache"),
            "FREESVG_MANIFEST": self.manifest,
            "FREESVG_EMAIL": "u@example.com",
            "FREESVG_PASSWORD": "pw",
        })
        self.env.start()
        self.root = mock.patch.object(freesvg, "ROOT", self.tmp)
        self.root.start()
        self.calls = []

    def tearDown(self):
        self.root.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def http_ok(self, responses):
        """responses: list of (matcher-substring, status, payload) consumed by match."""
        def side_effect(method, url, body=None, token=None):
            self.calls.append((method, url))
            for substr, status, payload in responses:
                if substr in url:
                    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                    return status, raw
            raise AssertionError(f"unexpected url {url}")
        return mock.patch.object(freesvg, "_http", side_effect=side_effect)


LOGIN = ("auth/login", 200, {"token": fake_jwt(9999999999)})


class TestAuth(Base):
    def test_missing_credentials_is_actionable(self):
        with mock.patch.dict(os.environ, {"FREESVG_EMAIL": "", "FREESVG_PASSWORD": ""}):
            with self.assertRaises(freesvg.AuthError) as ctx:
                freesvg.get_token()
        self.assertIn("FREESVG_EMAIL", str(ctx.exception))

    def test_token_cached_and_reused(self):
        with self.http_ok([LOGIN, ("search", 200, {"data": []})]):
            freesvg.search("cat")
            freesvg.search("dog")
        logins = [c for c in self.calls if "auth/login" in c[1]]
        self.assertEqual(len(logins), 1)
        mode = os.stat(os.path.join(freesvg.cache_dir(), "token.json")).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_401_triggers_one_relogin_retry(self):
        state = {"n": 0}
        def side_effect(method, url, body=None, token=None):
            self.calls.append((method, url))
            if "auth/login" in url:
                return 200, json.dumps({"token": fake_jwt(9999999999)}).encode()
            state["n"] += 1
            if state["n"] == 1:
                return 401, b'{"error":"Unauthenticated."}'
            return 200, json.dumps({"data": [{"id": 1}]}).encode()
        with mock.patch.object(freesvg, "_http", side_effect=side_effect):
            items, _ = freesvg.search("cat")
        self.assertEqual(items, [{"id": 1}])
        self.assertEqual(len([c for c in self.calls if "auth/login" in c[1]]), 2)


class TestCache(Base):
    def test_search_second_call_hits_cache_not_network(self):
        with self.http_ok([LOGIN, ("search", 200, {"data": [{"id": 5, "title": "Cat"}]})]):
            items1, cached1 = freesvg.search("cat")
            n_after_first = len(self.calls)
            items2, cached2 = freesvg.search("cat")
        self.assertEqual(items1, items2)
        self.assertFalse(cached1)
        self.assertTrue(cached2)
        self.assertEqual(len(self.calls), n_after_first)

    def test_search_ttl_expiry_refetches(self):
        with self.http_ok([LOGIN, ("search", 200, {"data": []})]):
            freesvg.search("cat")
            n_after_first = len(self.calls)
            with mock.patch.object(freesvg, "_now",
                                   return_value=freesvg.time.time() + freesvg.SEARCH_TTL + 1):
                # token exp is huge, so only the search refetches
                freesvg.search("cat")
        self.assertGreater(len(self.calls), n_after_first)

    def test_offline_serves_stale_with_warning(self):
        with self.http_ok([LOGIN, ("search", 200, {"data": [{"id": 9}]})]):
            freesvg.search("cat")
        def offline(method, url, body=None, token=None):
            raise OSError("no route to host")
        with mock.patch.object(freesvg, "_http", side_effect=offline):
            with mock.patch.object(freesvg, "warn") as w:
                items, cached = freesvg.search("cat", refresh=True)
        self.assertEqual(items, [{"id": 9}])
        self.assertTrue(cached)
        self.assertTrue(any("stale" in str(c) for c in w.call_args_list))


class TestFetchPromote(Base):
    def item_responses(self, item):
        return [LOGIN, (f"/svg/7", 200, {"data": [item]})]

    def test_fetch_inline_svg_then_immutable(self):
        item = {"id": 7, "title": "Rocket Art", "svg": GOOD_SVG}
        with self.http_ok(self.item_responses(item)):
            path = freesvg.fetch("7")
            n_after_first = len(self.calls)
            path2 = freesvg.fetch("7")
        self.assertEqual(path, path2)
        self.assertEqual(len(self.calls), n_after_first)
        with open(path) as f:
            self.assertIn("<svg", f.read())

    def test_fetch_via_url_field(self):
        item = {"id": 7, "title": "X", "file": "https://freesvg.org/storage/img/x.svg"}
        with self.http_ok(self.item_responses(item) + [("storage/img/x.svg", 200, GOOD_SVG.encode())]):
            path = freesvg.fetch("7")
        self.assertTrue(os.path.exists(path))

    def test_fetch_unknown_shape_names_fields(self):
        item = {"id": 7, "weird": "value"}
        with self.http_ok(self.item_responses(item)):
            with self.assertRaises(RuntimeError) as ctx:
                freesvg.fetch("7")
        self.assertIn("weird", str(ctx.exception))

    def test_promote_appends_manifest_entry_once(self):
        item = {"id": 7, "title": "Rocket Art", "tags": ["rocket", "space"], "svg": GOOD_SVG}
        with self.http_ok(self.item_responses(item)):
            rel = freesvg.promote("7")
            rel2 = freesvg.promote("7")
        self.assertEqual(rel, rel2)
        self.assertEqual(rel, "tools/svg/library/external/freesvg/freesvg-rocket-art.svg")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, rel)))
        with open(self.manifest) as f:
            entries = json.load(f)["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["license"], "CC0 / Public domain")
        self.assertIn("freesvg", entries[0]["tags"])

    def test_promote_refuses_lint_errors(self):
        item = {"id": 7, "title": "Bad", "svg": "<svg><rect/></svg>"}  # no viewBox
        with self.http_ok(self.item_responses(item)):
            with self.assertRaises(RuntimeError) as ctx:
                freesvg.promote("7")
        self.assertIn("lint", str(ctx.exception))
        with open(self.manifest) as f:
            self.assertEqual(json.load(f)["entries"], [])


class TestPrune(Base):
    def test_prune_removes_oldest_first(self):
        files_dir = os.path.join(freesvg.cache_dir(), "files")
        os.makedirs(files_dir)
        for i, age in enumerate((300, 200, 100)):
            p = os.path.join(files_dir, f"{i}.svg")
            with open(p, "wb") as f:
                f.write(b"x" * 1024)
            past = freesvg.time.time() - age
            os.utime(p, (past, past))
        removed, total = freesvg.prune(max_mb=2 / 1024)  # keep ~2KB
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(os.path.join(files_dir, "0.svg")))

    def test_slugify(self):
        self.assertEqual(freesvg._slugify("Rocket  Art! (v2)"), "rocket-art-v2")


if __name__ == "__main__":
    unittest.main(verbosity=1)
