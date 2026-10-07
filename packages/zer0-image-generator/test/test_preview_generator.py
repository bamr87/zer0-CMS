#!/usr/bin/env python3
"""Unit tests for lib/zer0_image_generator/preview_generator.py (the engine).

Zero network: every provider/API test monkeypatches the module's HTTP layer.

    python3 test/test_preview_generator.py
"""

import argparse
import base64
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib" / "zer0_image_generator"))

import preview_generator as pg  # noqa: E402

pg.POST_GENERATION_SLEEP = 0


def parse(argv):
    return pg.parse_args(argv)


def make_settings(**kwargs):
    return pg.Settings(**kwargs)


class TestFlagSurface(unittest.TestCase):
    """Golden test: every invocation used by the Rakefile and VS Code tasks
    must keep parsing. Breaking any of these breaks rake preview:* / tasks."""

    GOLDEN = [
        ["--list-missing"],
        ["--dry-run", "--verbose"],
        ["--verbose"],
        ["--collection", "posts", "--verbose"],
        ["--collection", "docs", "--verbose"],
        ["--force", "--verbose"],
        ["--file", "pages/_posts/example.md", "--verbose"],
        ["--collection", "posts"],
        ["--collection", "all"],
        # Historical bash flag surface
        ["-d"], ["-v"], ["-f", "x.md"], ["-c", "posts"], ["-p", "openai"],
        ["--output-dir", "assets/images/previews"],
        ["-j", "4"], ["-e"],
        ["--enhance-prompt", "fix it"],
        ["--enhance-model", "gpt-image-2"],
        ["--enhance-fidelity", "high"],
        ["--enhance-format", "png"],
        # New additive flags
        ["-p", "local"], ["-p", "gemini"],
        ["--prompt-engine", "claude"], ["--prompt-engine", "template"],
        ["--prompt-engine", "xai"],
        ["--review", "claude"], ["--review", "none"], ["--review", "xai"],
        ["--rasterizer", "none"],
        ["-w", "2"],
        # Back-compat no-op from the previous engine's CLI
        ["--rate-limit", "5"],
        # Universal knobs (zer0-image-generator additions)
        ["--collections-dir", "pages"],
        ["--front-matter-key", "image"],
        ["--authors-file", "_data/people.yml"],
        ["--authors-file", ""],
    ]

    def test_golden_invocations_parse(self):
        for argv in self.GOLDEN:
            with self.subTest(argv=argv):
                parse(argv)

    def test_enhance_implication_rules(self):
        # --enhance-prompt / -fidelity / -format imply --enhance…
        self.assertTrue(parse(["--enhance-prompt", "x"]).enhance)
        self.assertTrue(parse(["--enhance-fidelity", "low"]).enhance)
        self.assertTrue(parse(["--enhance-format", "webp"]).enhance)
        # …but --enhance-model does NOT (historical behavior).
        self.assertFalse(parse(["--enhance-model", "gpt-image-2"]).enhance)


class TestSettingsPrecedence(unittest.TestCase):
    SITE = {
        "provider": "openai",
        "model": "gpt-image-2",
        "style": "config style",
        "output_dir": "assets/images/previews",
        "enabled": True,
        "collections": ["posts", "docs"],
    }

    def resolve(self, argv, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            for key in ("AI_PROVIDER", "IMAGE_STYLE", "IMAGE_MODEL", "DRY_RUN",
                        "MAX_PARALLEL", "IMAGE_SIZE", "IMAGE_QUALITY"):
                if key not in (env or {}):
                    os.environ.pop(key, None)
            return pg.resolve_settings(parse(argv), {"preview_images": self.SITE})

    def test_config_wins_over_defaults(self):
        settings = self.resolve([])
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.style, "config style")
        self.assertEqual(settings.collections, ["posts", "docs"])

    def test_env_wins_over_config(self):
        settings = self.resolve([], env={"AI_PROVIDER": "xai", "IMAGE_STYLE": "env style"})
        self.assertEqual(settings.provider, "xai")
        self.assertEqual(settings.style, "env style")

    def test_cli_wins_over_env(self):
        settings = self.resolve(
            ["-p", "local", "--style", "cli style"],
            env={"AI_PROVIDER": "xai", "IMAGE_STYLE": "env style"},
        )
        self.assertEqual(settings.provider, "local")
        self.assertEqual(settings.style, "cli style")

    def test_defaults_when_config_empty(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("AI_PROVIDER", "IMAGE_MODEL", "IMAGE_STYLE",
                        "PROMPT_ENGINE", "REVIEW_ENGINE"):
                os.environ.pop(key, None)
            settings = pg.resolve_settings(parse([]), {})
        self.assertEqual(settings.provider, "openai")  # default renderer
        # Claude orchestrates by default (analysis + review)
        self.assertEqual(settings.prompt_engine, "claude")
        self.assertEqual(settings.review_engine, "claude")
        self.assertEqual(settings.collections, ["posts"])  # universal default
        self.assertEqual(settings.collections_dir, "")
        self.assertEqual(settings.front_matter_key, "preview")
        self.assertEqual(settings.authors_file, "_data/authors.yml")

    def test_review_engine_cli_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REVIEW_ENGINE", None)
            settings = pg.resolve_settings(parse(["--review", "none"]), {})
        self.assertEqual(settings.review_engine, "none")

    def _resolve_rasterizer(self, argv, config, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            if "IMAGE_RASTERIZER" not in (env or {}):
                os.environ.pop("IMAGE_RASTERIZER", None)
            return pg.resolve_settings(parse(argv), config).rasterizer

    def test_rasterizer_defaults_to_auto(self):
        self.assertEqual(self._resolve_rasterizer([], {}), "auto")

    def test_rasterizer_from_config_block(self):
        """A site declares SVG-only once in _config.yml, not per invocation."""
        config = {"preview_images": {"rasterizer": "none"}}
        self.assertEqual(self._resolve_rasterizer([], config), "none")

    def test_rasterizer_cli_and_env_beat_config(self):
        config = {"preview_images": {"rasterizer": "none"}}
        self.assertEqual(
            self._resolve_rasterizer([], config, env={"IMAGE_RASTERIZER": "rsvg"}), "rsvg")
        self.assertEqual(
            self._resolve_rasterizer(["--rasterizer", "magick"], config,
                                     env={"IMAGE_RASTERIZER": "rsvg"}), "magick")

    def test_author_overrides_apply_on_top(self):
        settings = self.resolve([])
        overrides = {"style": "noir", "model": "dall-e-3", "size": "1024x1024"}
        merged = pg.apply_preview_overrides(settings, overrides)
        self.assertEqual(merged.style, "noir")
        self.assertEqual(merged.model, "dall-e-3")
        self.assertEqual(merged.size, "1024x1024")
        # untouched fields survive
        self.assertEqual(merged.output_dir, settings.output_dir)


class TestAuthorOverrides(unittest.TestCase):
    AUTHORS_YAML = (
        "cassandra:\n"
        "  name: Cassandra\n"
        "  preview:\n"
        "    style: >-\n"
        "      noir graphic-novel,\n"
        "      high-contrast ink\n"
        "vega:\n"
        "  preview:\n"
        "    style: isometric 3D infographic\n"
    )

    def test_authors_yaml_folded_scalars(self):
        """zer0-mistakes-style authors.yml uses >- folded scalars — they must
        survive parsing intact (a mangled style prompt is invisible breakage),
        and read_authors must honor a custom authors_file path."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "team").mkdir()
            (root / "team" / "writers.yml").write_text(
                self.AUTHORS_YAML, encoding="utf-8")
            authors = pg.read_authors(root, "team/writers.yml")
            overrides = pg.author_preview_overrides(authors, "cassandra")
            self.assertIn("noir graphic-novel", overrides.get("style", ""))
            self.assertNotIn("\n", overrides.get("style", ""))  # folded → one line
            overrides_vega = pg.author_preview_overrides(authors, "vega")
            self.assertIn("isometric 3D infographic", overrides_vega.get("style", ""))

    def test_authors_file_empty_disables(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pg.read_authors(Path(tmp), ""), {})
            self.assertEqual(pg.read_authors(Path(tmp), "  "), {})

    def test_authors_file_missing_is_graceful(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pg.read_authors(Path(tmp), "_data/authors.yml"), {})

    def test_non_string_author_keys(self):
        authors = {"a": {"preview": {"style": "s"}}}
        self.assertEqual(pg.author_preview_overrides(authors, ["a", "b"]), {})
        self.assertEqual(pg.author_preview_overrides(authors, {"name": "x"}), {})
        self.assertEqual(pg.author_preview_overrides(authors, None), {})
        self.assertEqual(pg.author_preview_overrides(authors, "missing"), {})


class TestCollectionStyles(unittest.TestCase):
    """Per-collection style/theme overrides (`collection_styles:`) — each
    collection can render with its own visual identity."""

    STYLES = {
        "hacks": {"style": "circuit-board blueprint", "size": "1024x1024"},
        "docs": {"style": "clean isometric diagram",
                 "style_modifiers": "matte, technical"},
        "posts": "not-a-dict",     # malformed block → ignored
    }

    def test_collection_of_derives_from_path(self):
        self.assertEqual(pg.collection_of(Path("/site/pages/_docs/a.md")), "docs")
        self.assertEqual(
            pg.collection_of(Path("/site/pages/_posts/2026/b.md")), "posts")
        self.assertEqual(pg.collection_of(Path("/site/index.md")), "")

    def test_overrides_looked_up_by_collection(self):
        self.assertEqual(
            pg.collection_preview_overrides(self.STYLES, "hacks"),
            {"style": "circuit-board blueprint", "size": "1024x1024"})
        self.assertEqual(pg.collection_preview_overrides(self.STYLES, "posts"), {})
        self.assertEqual(pg.collection_preview_overrides(self.STYLES, "news"), {})
        self.assertEqual(pg.collection_preview_overrides(self.STYLES, ""), {})
        self.assertEqual(pg.collection_preview_overrides("nope", "hacks"), {})

    def test_unknown_keys_filtered(self):
        styles = {"docs": {"style": "x", "output_dir": "evil", "enabled": False}}
        self.assertEqual(
            pg.collection_preview_overrides(styles, "docs"), {"style": "x"})

    def test_resolve_settings_reads_map(self):
        config = {"preview_images": {"collection_styles": self.STYLES}}
        settings = pg.resolve_settings(parse([]), config)
        self.assertEqual(settings.collection_styles, self.STYLES)
        # non-map values are dropped, not crashed on
        config = {"preview_images": {"collection_styles": ["hacks"]}}
        self.assertEqual(pg.resolve_settings(parse([]), config).collection_styles, {})

    def test_author_beats_collection_beats_global(self):
        settings = pg.resolve_settings(parse([]), {"preview_images": {
            "style": "global-style",
            "collection_styles": {"docs": {"style": "docs-style",
                                           "size": "1024x1024"}},
        }})
        collection = pg.collection_preview_overrides(
            settings.collection_styles, "docs")
        author = {"style": "author-style"}
        merged = pg.apply_preview_overrides(settings, collection, author)
        self.assertEqual(merged.style, "author-style")   # author wins style...
        self.assertEqual(merged.size, "1024x1024")       # ...collection keeps size
        no_author = pg.apply_preview_overrides(settings, collection, {})
        self.assertEqual(no_author.style, "docs-style")


class TestUniversalKnobs(unittest.TestCase):
    """The knobs that make the engine portable beyond zer0-mistakes:
    collections_dir, front_matter_key, authors_file, collections: auto."""

    def resolve(self, argv, config):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("AI_PROVIDER", "IMAGE_MODEL", "IMAGE_STYLE"):
                os.environ.pop(key, None)
            return pg.resolve_settings(parse(argv), config)

    # -- collections_dir ------------------------------------------------------

    def test_collections_dir_defaults_to_site_root(self):
        self.assertEqual(self.resolve([], {}).collections_dir, "")

    def test_collections_dir_reads_jekyll_top_level(self):
        settings = self.resolve([], {"collections_dir": "pages"})
        self.assertEqual(settings.collections_dir, "pages")

    def test_collections_dir_block_overrides_top_level(self):
        config = {"collections_dir": "pages",
                  "preview_images": {"collections_dir": "content"}}
        self.assertEqual(self.resolve([], config).collections_dir, "content")

    def test_collections_dir_cli_wins(self):
        config = {"collections_dir": "pages"}
        settings = self.resolve(["--collections-dir", "site"], config)
        self.assertEqual(settings.collections_dir, "site")

    def test_collection_path_uses_collections_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = pg.Runner(make_settings(collections_dir=""), root)
            self.assertEqual(runner.collection_path("posts"), root / "_posts")
            runner = pg.Runner(make_settings(collections_dir="pages"), root)
            self.assertEqual(runner.collection_path("docs"), root / "pages" / "_docs")
            runner = pg.Runner(make_settings(collections_dir="content/site"), root)
            self.assertEqual(
                runner.collection_path("posts"), root / "content" / "site" / "_posts")

    # -- source (Jekyll's own top-level key) -----------------------------------

    def test_source_reroots_content(self):
        root = Path("/site")
        self.assertEqual(
            pg.apply_source_root(root, {"source": "pages"}), root / "pages")

    def test_source_absent_or_dot_keeps_root(self):
        root = Path("/site")
        self.assertEqual(pg.apply_source_root(root, {}), root)
        self.assertEqual(pg.apply_source_root(root, {"source": ""}), root)
        self.assertEqual(pg.apply_source_root(root, {"source": "."}), root)
        self.assertEqual(pg.apply_source_root(root, {"source": None}), root)

    def test_source_composes_with_collections_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pg.apply_source_root(Path(tmp), {"source": "pages"})
            runner = pg.Runner(make_settings(collections_dir=""), root)
            self.assertEqual(
                runner.collection_path("docs"), Path(tmp) / "pages" / "_docs")

    # -- front_matter_key ------------------------------------------------------

    def test_front_matter_key_from_config_and_cli(self):
        config = {"preview_images": {"front_matter_key": "image"}}
        self.assertEqual(self.resolve([], config).front_matter_key, "image")
        settings = self.resolve(["--front-matter-key", "thumbnail"], config)
        self.assertEqual(settings.front_matter_key, "thumbnail")

    def test_parse_front_matter_reads_configured_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.md"
            path.write_text("---\ntitle: T\nimage: /img/x.png\n---\nBody\n",
                            encoding="utf-8")
            cf = pg.parse_front_matter(path, "image")
            self.assertEqual(cf.preview, "/img/x.png")
            # default key does NOT see the image: value
            cf_default = pg.parse_front_matter(path)
            self.assertIsNone(cf_default.preview)

    def test_update_front_matter_writes_configured_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.md"
            path.write_text(
                "---\ntitle: T\ndescription: D\nimage: /old.png\n---\nBody\n",
                encoding="utf-8")
            self.assertTrue(pg.update_front_matter(path, "/new.png", key="image"))
            out = path.read_text(encoding="utf-8")
            self.assertIn("image: /new.png\n", out)
            self.assertNotIn("/old.png", out)

    def test_update_front_matter_inserts_configured_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.md"
            path.write_text("---\ntitle: T\ndescription: D\n---\nBody\n",
                            encoding="utf-8")
            self.assertTrue(pg.update_front_matter(path, "/new.png", key="image"))
            out = path.read_text(encoding="utf-8")
            self.assertIn("description: D\nimage: /new.png\n", out)
            self.assertNotIn("preview:", out)

    # -- authors_file ----------------------------------------------------------

    def test_authors_file_configurable_and_disableable(self):
        config = {"preview_images": {"authors_file": "team/writers.yml"}}
        self.assertEqual(self.resolve([], config).authors_file, "team/writers.yml")
        settings = self.resolve(["--authors-file", ""], config)
        self.assertEqual(settings.authors_file, "")

    # -- collections: auto -----------------------------------------------------

    def test_collections_auto_discovers_from_jekyll_map(self):
        config = {
            "collections": {"docs": {"output": True}, "notes": {}, "posts": {}},
            "preview_images": {"collections": "auto"},
        }
        settings = self.resolve([], config)
        self.assertEqual(settings.collections[0], "posts")
        self.assertEqual(sorted(settings.collections), ["docs", "notes", "posts"])
        self.assertEqual(len(settings.collections), 3)  # posts not duplicated

    def test_collections_auto_inside_list(self):
        config = {"collections": {"docs": {}},
                  "preview_images": {"collections": ["auto"]}}
        self.assertEqual(self.resolve([], config).collections, ["posts", "docs"])

    def test_collections_auto_without_jekyll_map(self):
        config = {"preview_images": {"collections": "auto"}}
        self.assertEqual(self.resolve([], config).collections, ["posts"])


class TestFrontMatterEditor(unittest.TestCase):
    def edit(self, text, value="/images/previews/new.png"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "post.md"
            path.write_bytes(text.encode("utf-8"))
            ok = pg.update_front_matter(path, value)
            result = path.read_bytes().decode("utf-8")
            leftovers = list(Path(tmp).glob("*.bak")) + list(Path(tmp).glob("*~"))
            return ok, result, leftovers

    def test_replaces_existing_preview(self):
        ok, out, leftovers = self.edit(
            "---\ntitle: T\npreview: /images/previews/old.png\n---\nBody\n")
        self.assertTrue(ok)
        self.assertIn("preview: /images/previews/new.png\n", out)
        self.assertNotIn("old.png", out)
        self.assertEqual(leftovers, [])

    def test_inserts_after_description(self):
        ok, out, _ = self.edit("---\ntitle: T\ndescription: D\nlayout: default\n---\nBody\n")
        self.assertTrue(ok)
        self.assertIn("description: D\npreview: /images/previews/new.png\nlayout: default\n", out)

    def test_inserts_after_folded_description(self):
        """Regression: folded scalars must not be split (the old sed/regex
        editors corrupted the following line)."""
        text = (
            "---\ntitle: T\n"
            "description: >-\n  line one\n  line two\n"
            "layout: default\n---\nBody\n"
        )
        ok, out, _ = self.edit(text)
        self.assertTrue(ok)
        self.assertIn(
            "description: >-\n  line one\n  line two\npreview: /images/previews/new.png\nlayout: default\n",
            out,
        )

    def test_inserts_after_title_without_description(self):
        ok, out, _ = self.edit("---\ntitle: T\nlayout: default\n---\nBody\n")
        self.assertTrue(ok)
        self.assertIn("title: T\npreview: /images/previews/new.png\nlayout: default\n", out)

    def test_body_preview_line_untouched(self):
        text = (
            "---\ntitle: T\npreview: /images/previews/old.png\n---\n"
            "Body text.\npreview: not-front-matter\nMore body.\n"
        )
        ok, out, _ = self.edit(text)
        self.assertTrue(ok)
        self.assertIn("preview: not-front-matter\n", out)  # body untouched
        self.assertEqual(out.count("new.png"), 1)

    def test_preserves_missing_trailing_newline(self):
        ok, out, _ = self.edit("---\ntitle: T\n---\nBody without newline")
        self.assertTrue(ok)
        self.assertTrue(out.endswith("Body without newline"))

    def test_crlf_preserved(self):
        text = "---\r\ntitle: T\r\ndescription: D\r\n---\r\nBody\r\n"
        ok, out, _ = self.edit(text)
        self.assertTrue(ok)
        self.assertIn("description: D\r\npreview: /images/previews/new.png\r\n", out)
        self.assertNotIn("\n\n", out.replace("\r\n", ""))

    def test_no_front_matter_refused(self):
        ok, out, _ = self.edit("Just a plain file\n")
        self.assertFalse(ok)
        self.assertEqual(out, "Just a plain file\n")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "post.md"
            path.write_text("---\ntitle: T\n---\n", encoding="utf-8")
            self.assertTrue(pg.update_front_matter(path, "/x.png", dry_run=True))
            self.assertEqual(path.read_text(encoding="utf-8"), "---\ntitle: T\n---\n")


class TestSlugAndPaths(unittest.TestCase):
    def test_slug_parity_vectors(self):
        cases = {
            "Auto-hide Navigation": "auto-hide-navigation",
            "Hello, World! 123": "hello-world-123",
            "  Spaces  Around  ": "spaces-around",
            "Café Déjà Vu": "caf-d-j-vu",
            "UPPER lower": "upper-lower",
        }
        for title, expected in cases.items():
            self.assertEqual(pg.generate_filename(title), expected)

    def test_slug_50_char_cut_after_trim(self):
        title = "x" * 49 + "-" + "y" * 30
        slug = pg.generate_filename(title)
        self.assertEqual(len(slug), 50)
        self.assertTrue(slug.startswith("x" * 49))

    def test_front_matter_path_strips_assets_prefix(self):
        settings = make_settings(output_dir="assets/images/previews")
        self.assertEqual(
            pg.preview_front_matter_path(settings, "slug.png"),
            "/images/previews/slug.png",
        )

    def test_front_matter_path_custom_dir(self):
        settings = make_settings(output_dir="static/previews")
        self.assertEqual(
            pg.preview_front_matter_path(settings, "slug.svg"),
            "/static/previews/slug.svg",
        )

    def test_check_preview_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets" / "images").mkdir(parents=True)
            (root / "assets" / "images" / "x.png").write_bytes(b"png")
            settings = make_settings()
            self.assertTrue(pg.check_preview_exists("/images/x.png", settings, root))
            self.assertTrue(pg.check_preview_exists("https://cdn.example/x.png", settings, root))
            self.assertFalse(pg.check_preview_exists("/images/missing.png", settings, root))
            self.assertFalse(pg.check_preview_exists(None, settings, root))


class TestOpenAIAdaptation(unittest.TestCase):
    def test_gpt_image_size_adaptation(self):
        self.assertEqual(
            pg.adapt_openai_size_quality("gpt-image-2", "1792x1024", "auto"),
            ("1536x1024", "auto"),
        )

    def test_dalle_quality_adaptation(self):
        self.assertEqual(
            pg.adapt_openai_size_quality("dall-e-3", "1792x1024", "auto"),
            ("1792x1024", "standard"),
        )

    def test_no_adaptation_needed(self):
        self.assertEqual(
            pg.adapt_openai_size_quality("gpt-image-2", "1536x1024", "auto"),
            ("1536x1024", "auto"),
        )


class TestModelFamily(unittest.TestCase):
    def test_family_detection(self):
        self.assertEqual(pg.model_family("claude-opus-4-8"), "claude")
        self.assertEqual(pg.model_family("gpt-image-2"), "openai")
        self.assertEqual(pg.model_family("dall-e-3"), "openai")
        self.assertEqual(pg.model_family("grok-2-image"), "xai")
        self.assertEqual(pg.model_family("gemini-2.5-flash-image"), "gemini")
        self.assertIsNone(pg.model_family("mystery-model"))

    def test_foreign_family_model_falls_back(self):
        settings = make_settings(model="claude-opus-4-8")
        self.assertEqual(pg.effective_model(settings, pg.PROVIDERS["openai"]), "gpt-image-2")

    def test_matching_family_kept(self):
        settings = make_settings(model="dall-e-3")
        self.assertEqual(pg.effective_model(settings, pg.PROVIDERS["openai"]), "dall-e-3")

    def test_empty_model_uses_provider_default(self):
        settings = make_settings(model="")
        self.assertEqual(
            pg.effective_model(settings, pg.PROVIDERS["xai"]), "grok-2-image"
        )

    def test_claude_model_under_renderer_falls_back(self):
        """A leftover `model: claude-*` (Claude is no longer a renderer) must
        fall back to the renderer's default, not be sent to the vendor API."""
        settings = make_settings(model="claude-opus-4-8")
        self.assertEqual(pg.effective_model(settings, pg.PROVIDERS["openai"]),
                         "gpt-image-2")


class TestSvgToolkit(unittest.TestCase):
    def _sanitize(self, body):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'
        return pg.sanitize_svg(svg)

    def test_strips_script_and_handlers(self):
        clean, notes = self._sanitize(
            '<script>alert(1)</script><rect onclick="evil()" width="5"/>'
        )
        self.assertNotIn("script", clean)
        self.assertNotIn("onclick", clean)
        self.assertTrue(notes)

    def test_strips_foreign_object_iframe_image(self):
        clean, _ = self._sanitize(
            "<foreignObject><div>x</div></foreignObject>"
            '<image href="https://evil/x.png"/><iframe/>'
        )
        for banned in ("foreignObject", "iframe", "<image"):
            self.assertNotIn(banned, clean)

    def test_external_href_removed_local_kept(self):
        clean, _ = self._sanitize(
            '<use href="#local"/><a href="https://evil.example">x</a>'
        )
        self.assertIn('href="#local"', clean)
        self.assertNotIn("evil.example", clean)

    def test_style_url_scrubbed(self):
        clean, _ = self._sanitize(
            '<rect style="fill:url(https://evil/f.svg)"/>'
            "<style>@import url(https://evil/x.css); .a{fill:url(#grad)}</style>"
        )
        self.assertNotIn("evil", clean)
        self.assertIn("url(#grad)", clean)

    def test_presentation_attribute_url_scrubbed(self):
        """fill=/filter=/mask= url() references are an SSRF vector when the
        SVG later renders in Chromium — external url() must not survive."""
        clean, notes = self._sanitize(
            '<rect fill="url(https://evil.example/track)" width="5"/>'
            '<circle filter="url(HTTPS://evil.example/f#x)" r="2"/>'
            '<path mask="url(#localmask)" d="M0 0"/>'
        )
        self.assertNotIn("evil.example", clean)
        self.assertIn('mask="url(#localmask)"', clean)
        self.assertTrue(any("url()" in n for n in notes))

    def test_doctype_and_entities_rejected(self):
        hostile = (
            '<!DOCTYPE svg [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
            '<svg xmlns="http://www.w3.org/2000/svg"><text>&b;</text></svg>'
        )
        with self.assertRaises(pg.SvgError):
            pg.sanitize_svg(hostile)

    def test_forces_banner_viewbox(self):
        clean, _ = self._sanitize("<rect/>")
        self.assertIn(f'viewBox="0 0 {pg.SVG_WIDTH} {pg.SVG_HEIGHT}"', clean)

    def test_rejects_non_svg_root(self):
        with self.assertRaises(pg.SvgError):
            pg.sanitize_svg("<html><body>nope</body></html>")

    def test_rejects_unparsable(self):
        with self.assertRaises(pg.SvgError):
            pg.sanitize_svg("<svg><unclosed")

    def test_local_template_is_valid_and_deterministic(self):
        svg_a = pg.render_local_svg("my-post", pg.seed_for("my-post"))
        svg_b = pg.render_local_svg("my-post", pg.seed_for("my-post"))
        self.assertEqual(svg_a, svg_b)
        clean, notes = pg.sanitize_svg(svg_a)
        self.assertEqual(notes, [])  # our own template must need no scrubbing
        self.assertIn("<svg", clean)
        # Accessibility floor (tools/svg/svg-check.py warns without these):
        self.assertIn('role="img"', clean)
        self.assertIn("Preview banner: my-post</title>", clean)

    def test_every_composition_renders_clean_at_banner_size(self):
        """All five must survive the sanitizer untouched and fill the frame —
        a composition authored at the wrong aspect gets squashed by the forced
        viewBox rather than rejected, so size is the thing to assert."""
        for name, render in pg.BANNER_COMPOSITIONS.items():
            svg = render(4242, pg.BANNER_PALETTES["neon"], "a-slug")
            clean, notes = pg.sanitize_svg(svg)
            self.assertEqual(notes, [], f"{name} needed scrubbing")
            self.assertIn(f'viewBox="0 0 {pg.SVG_WIDTH} {pg.SVG_HEIGHT}"', clean)
            self.assertIn('role="img"', clean)
            self.assertIn("Preview banner: a-slug</title>", clean)


class TestProviderLadder(unittest.TestCase):
    """`provider: auto` picks the best renderer the environment can reach."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def resolve(self, env):
        # HOME points at an empty tmpdir so a real Grok OAuth credentials file
        # on the machine running the suite cannot promote the xAI rung.
        settings = pg.resolve_auto_provider(
            pg.Settings(provider="auto"), {"HOME": self._tmpdir.name, **env})
        return settings.provider

    def test_nothing_wired_falls_to_the_shared_collection_default(self):
        self.assertEqual(self.resolve({}), "default")

    def test_claude_credential_alone_authors_svg(self):
        for key in pg.CLAUDE_CREDENTIAL_ENV:
            self.assertEqual(self.resolve({key: "x"}), "claude", key)

    def test_raster_key_wins_over_claude(self):
        self.assertEqual(
            self.resolve({"ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "x"}), "openai")

    def test_raster_preference_order(self):
        self.assertEqual(self.resolve({"GEMINI_API_KEY": "x"}), "gemini")
        self.assertEqual(
            self.resolve({"GEMINI_API_KEY": "x", "XAI_API_KEY": "x"}), "xai")

    def test_an_installed_cli_is_not_a_credential(self):
        """AnthropicClient accepts a `claude` binary on PATH, but auto must not:
        an installed CLI is not proof of a working login, and promoting off the
        default rung on that basis fails every page at generation time."""
        with mock.patch.object(pg.shutil, "which", return_value="/usr/bin/claude"):
            self.assertTrue(pg.AnthropicClient({}).available())
            self.assertEqual(self.resolve({}), "default")

    def test_explicit_provider_is_never_overridden(self):
        pinned = pg.resolve_auto_provider(
            pg.Settings(provider="local"), {"OPENAI_API_KEY": "x"})
        self.assertEqual(pinned.provider, "local")


class TestCollectionDefaultProvider(unittest.TestCase):
    """The key-free floor shares ONE banner per section rather than emitting N
    near-identical per-article images."""

    def ctx(self, section):
        return pg.RunContext(project_root=Path("."), env={},
                             article={"section": section})

    def test_every_page_in_a_section_shares_one_stem(self):
        provider = pg.PROVIDERS["default"]
        a = provider.output_stem("first-post", self.ctx("hacks"))
        b = provider.output_stem("totally-different-post", self.ctx("hacks"))
        self.assertEqual(a, b)
        self.assertEqual(a, "section-hacks")

    def test_sections_differ_from_each_other(self):
        provider = pg.PROVIDERS["default"]
        stems = {provider.output_stem("x", self.ctx(s))
                 for s in ("hacks", "tools", "field-notes", "docs")}
        self.assertEqual(len(stems), 4)

    def test_sectionless_pages_get_one_shared_default(self):
        provider = pg.PROVIDERS["default"]
        self.assertEqual(provider.output_stem("x", self.ctx("")), "section-default")

    def test_art_is_seeded_by_section_not_by_page(self):
        """The image is shared, so it must not vary with whichever page
        happened to trigger the write."""
        provider = pg.PROVIDERS["default"]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "section-hacks"
            r1 = provider.generate("", make_settings(rasterizer="none"), out,
                                   self.ctx("hacks"))
            first = r1.path.read_text()
            r2 = provider.generate("", make_settings(rasterizer="none"), out,
                                   self.ctx("hacks"))
            self.assertEqual(first, r2.path.read_text())


class TestBannerArtDirection(unittest.TestCase):
    """The content -> art mapping. This is art direction, so the tests pin the
    editorial intent (a shell hack looks like a schematic) rather than bytes."""

    def article(self, **over):
        base = {"slug": "a-post", "section": "", "categories": "", "title": "",
                "description": "", "body": ""}
        base.update(over)
        return base

    def test_section_decides_the_composition(self):
        for section, expected in (("hacks", "circuit"), ("tools", "pixelscene"),
                                  ("docs", "lowpoly"), ("field-notes", "flowfield")):
            composition, _ = pg.banner_theme_for(self.article(section=section))
            self.assertEqual(composition, expected, f"section {section}")

    def test_tags_and_title_decide_when_there_is_no_section(self):
        composition, _ = pg.banner_theme_for(
            self.article(categories="security token", title="Audit your secrets"))
        self.assertEqual(composition, "starfield")

    def test_whole_word_matching_only(self):
        """'decision' contains 'ci' and 'certain' contains 'ai'. Substring
        matching let those drag a whole dev blog toward one composition."""
        words = pg._banner_words("Decisions and efficiency, a specific certain case")
        for fragment in ("ci", "cd", "ai"):
            self.assertNotIn(fragment, words)

    def test_body_cannot_outvote_the_section(self):
        """A long body full of incidental vocabulary must not overrule the
        section the author deliberately filed the piece under."""
        composition, _ = pg.banner_theme_for(self.article(
            section="tools", title="An honest review",
            body=" ".join(["docker shell git deploy kernel server"] * 200)))
        self.assertEqual(composition, "pixelscene")

    def test_no_keywords_falls_back_to_the_seed(self):
        composition, palette = pg.banner_theme_for(
            self.article(title="A quiet piece", body="prose and nothing else"))
        self.assertIn(composition, pg.BANNER_COMPOSITION_ORDER)
        self.assertIn(palette, pg.BANNER_PALETTES)

    def test_same_article_same_bytes_changed_article_new_art(self):
        article = self.article(section="hacks", title="Order your Dockerfile")
        first = pg.render_local_svg("a-post", 0, article)
        self.assertEqual(first, pg.render_local_svg("a-post", 0, article))
        retitled = dict(article, title="A completely different headline")
        self.assertNotEqual(first, pg.render_local_svg("a-post", 0, retitled))

    def test_section_of_reads_the_directory_inside_the_collection(self):
        self.assertEqual(pg.section_of(Path("/s/pages/_posts/hacks/x.md")), "hacks")
        self.assertEqual(pg.section_of(Path("/s/pages/_docs/x.md")), "")


class TestAnthropicClient(unittest.TestCase):
    def client(self, env):
        with mock.patch.object(pg.shutil, "which", return_value=None):
            return pg.AnthropicClient(env)

    def test_oauth_token_mode_and_headers(self):
        client = self.client({"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x"})
        self.assertEqual(client.mode, "oauth")
        headers = client.headers()
        self.assertEqual(headers["Authorization"], "Bearer sk-ant-oat01-x")
        self.assertEqual(headers["anthropic-beta"], pg.OAUTH_BETA)
        self.assertEqual(headers["anthropic-version"], pg.ANTHROPIC_VERSION)

    def test_auth_token_mode(self):
        client = self.client({"ANTHROPIC_AUTH_TOKEN": "tok"})
        self.assertEqual(client.mode, "oauth")

    def test_api_key_mode_headers(self):
        client = self.client({"ANTHROPIC_API_KEY": "sk-ant-api"})
        self.assertEqual(client.mode, "api_key")
        headers = client.headers()
        self.assertEqual(headers["x-api-key"], "sk-ant-api")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("anthropic-beta", headers)

    def test_cli_fallback_mode(self):
        with mock.patch.object(pg.shutil, "which", return_value="/usr/local/bin/claude"):
            client = pg.AnthropicClient({})
        self.assertEqual(client.mode, "cli")

    def test_no_credentials(self):
        client = self.client({})
        self.assertFalse(client.available())

    def test_precedence_oauth_over_api_key(self):
        client = self.client({
            "CLAUDE_CODE_OAUTH_TOKEN": "oat", "ANTHROPIC_API_KEY": "key",
        })
        self.assertEqual(client.mode, "oauth")

    def test_complete_payload_shape(self):
        captured = {}

        def fake_http_json(url, payload, headers, timeout=900):
            captured["url"], captured["payload"], captured["headers"] = url, payload, headers
            return {"stop_reason": "end_turn",
                    "content": [{"type": "thinking", "thinking": ""},
                                {"type": "text", "text": "<svg/>"}]}

        client = self.client({"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            text = client.complete("system-2", "user prompt")
        self.assertEqual(text, "<svg/>")
        payload = captured["payload"]
        # Claude Code identity MUST be the first system block (OAuth gate).
        self.assertEqual(payload["system"][0]["text"], pg.CLAUDE_CODE_SYSTEM_PROMPT)
        self.assertEqual(payload["system"][1]["text"], "system-2")
        self.assertEqual(payload["model"], pg.DEFAULT_CLAUDE_MODEL)
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["max_tokens"], pg.CLAUDE_MAX_TOKENS)

    def test_effort_in_payload_and_default(self):
        captured = {}

        def fake_http_json(url, payload, headers, timeout=900):
            captured["payload"] = payload
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}]}

        client = self.client({"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            client.complete("s", "u", effort="low")
        self.assertEqual(captured["payload"]["output_config"], {"effort": "low"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            client.complete("s", "u")           # no effort → no output_config
        self.assertNotIn("output_config", captured["payload"])
        # engine default is "low"; empty string in config disables cleanly
        self.assertEqual(pg.resolve_settings(parse([]), {}).claude_effort, "low")
        settings = pg.resolve_settings(
            parse([]), {"preview_images": {"claude_effort": ""}})
        self.assertEqual(settings.claude_effort, "")

    def test_effort_stripped_on_400(self):
        calls = []

        def fake_http_json(url, payload, headers, timeout=900):
            calls.append(dict(payload))
            if "output_config" in payload:
                raise pg.HttpStatusError(
                    400,
                    b'{"error": {"message": "output_config is not supported"}}',
                    url)
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}]}

        client = self.client({"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            text = client.complete("s", "u", effort="low")
        self.assertEqual(text, "ok")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("output_config", calls[1])

    def test_refusal_raises(self):
        def fake_http_json(url, payload, headers, timeout=900):
            return {"stop_reason": "refusal", "stop_details": {"category": "cyber"},
                    "content": []}

        client = self.client({"ANTHROPIC_API_KEY": "k"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            with self.assertRaises(pg.ClaudeRefusal) as ctx:
                client.complete("s", "u")
        self.assertEqual(ctx.exception.category, "cyber")

    def test_thinking_400_retries_without_thinking(self):
        calls = []

        def fake_http_json(url, payload, headers, timeout=900):
            calls.append(dict(payload))
            if "thinking" in payload:
                raise pg.HttpStatusError(
                    400, b'{"error": {"message": "thinking is not supported"}}', url)
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}]}

        client = self.client({"ANTHROPIC_API_KEY": "k"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            self.assertEqual(client.complete("s", "u"), "ok")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("thinking", calls[1])

    def test_truncation_raises(self):
        def fake_http_json(url, payload, headers, timeout=900):
            return {"stop_reason": "max_tokens",
                    "content": [{"type": "text", "text": "<svg"}]}

        client = self.client({"ANTHROPIC_API_KEY": "k"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            with self.assertRaises(pg.ClaudeTruncated):
                client.complete("s", "u")

    def test_api_key_mode_omits_claude_code_block(self):
        """Parity with worker.js: the Claude Code identity block is an OAuth
        requirement and must NOT be injected for plain API keys."""
        captured = {}

        def fake_http_json(url, payload, headers, timeout=900):
            captured["payload"] = payload
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}]}

        client = self.client({"ANTHROPIC_API_KEY": "k"})
        with mock.patch.object(pg, "http_json", fake_http_json):
            client.complete("system-text", "u")
        system = captured["payload"]["system"]
        self.assertEqual(len(system), 1)
        self.assertEqual(system[0]["text"], "system-text")


class TestProviders(unittest.TestCase):
    def ctx(self, env=None, tmp=None):
        return pg.RunContext(project_root=Path(tmp or "."), env=env or {}, slug="test-post")

    def test_registry_contents(self):
        # Renderers only — Claude orchestrates and is deliberately NOT a provider.
        self.assertEqual(
            sorted(pg.PROVIDERS),
            ["claude", "default", "gemini", "local", "openai", "stability", "xai"]
        )

    def test_edit_unsupported_on_non_edit_providers(self):
        for name in ("xai", "stability", "gemini"):
            with self.assertRaises(pg.EditUnsupported):
                pg.PROVIDERS[name].edit(Path("x.png"), "p", make_settings(), self.ctx())

    def test_local_edit_is_a_credential_free_noop(self):
        result = pg.PROVIDERS["local"].edit(Path("x.png"), "p", make_settings(), self.ctx())
        self.assertTrue(result.ok)
        self.assertEqual(result.path, Path("x.png"))

    def test_openai_edit_fidelity_rules(self):
        """input_fidelity is omitted for gpt-image-2, included otherwise."""
        captured = {}

        def fake_multipart(url, fields, files, headers, timeout=900):
            captured["fields"], captured["files"] = fields, files
            return {"data": [{"b64_json": "aGk="}]}

        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "banner.png"
            img.write_bytes(pg.PNG_SIGNATURE + b"rest")
            env = {"OPENAI_API_KEY": "k"}

            with mock.patch.object(pg, "http_multipart", fake_multipart):
                settings = make_settings(enhance_model="gpt-image-2")
                result = pg.PROVIDERS["openai"].edit(img, "p", settings, self.ctx(env, tmp))
                self.assertTrue(result.ok)
                self.assertNotIn("input_fidelity", captured["fields"])
                self.assertEqual(captured["fields"]["size"], "auto")
                self.assertEqual(captured["files"][0][0], "image[]")

                settings = make_settings(enhance_model="gpt-image-1", enhance_fidelity="high")
                pg.PROVIDERS["openai"].edit(img, "p", settings, self.ctx(env, tmp))
                self.assertEqual(captured["fields"]["input_fidelity"], "high")

    def test_openai_generate_payload_and_b64(self):
        captured = {}

        def fake_json(url, payload, headers, timeout=900):
            captured["url"], captured["payload"] = url, payload
            return {"data": [{"b64_json": "aGVsbG8="}]}

        with tempfile.TemporaryDirectory() as tmp:
            out_base = Path(tmp) / "slug"
            settings = make_settings(model="gpt-image-2", size="1792x1024", quality="auto")
            with mock.patch.object(pg, "http_json", fake_json):
                result = pg.PROVIDERS["openai"].generate(
                    "prompt", settings, out_base, self.ctx({"OPENAI_API_KEY": "k"}, tmp))
            self.assertTrue(result.ok)
            self.assertEqual(captured["payload"]["size"], "1536x1024")  # adapted
            self.assertEqual(result.path.read_bytes(), b"hello")

    def test_local_provider_svg_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_base = Path(tmp) / "slug"
            settings = make_settings(rasterizer="none")
            result = pg.PROVIDERS["local"].generate(
                "prompt", settings, out_base, self.ctx({}, tmp))
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "svg")
        self.assertEqual(result.path.suffix, ".svg")

    def test_gemini_inline_data_decode(self):
        def fake_json(url, payload, headers, timeout=900):
            self.assertIn("x-goog-api-key", headers)
            self.assertNotIn("key=", url)  # never in the query string
            return {"candidates": [{"content": {"parts": [
                {"text": "here"}, {"inlineData": {"data": "aW1n"}}]}}]}

        with tempfile.TemporaryDirectory() as tmp:
            out_base = Path(tmp) / "slug"
            with mock.patch.object(pg, "http_json", fake_json):
                result = pg.PROVIDERS["gemini"].generate(
                    "p", make_settings(), out_base, self.ctx({"GEMINI_API_KEY": "g"}, tmp))
            self.assertTrue(result.ok)
            self.assertEqual(result.path.read_bytes(), b"img")


class TestXAIAuth(unittest.TestCase):
    """The xAI credential ladder: a Grok OAuth token first, XAI_API_KEY as the
    fallback — including the runtime retry when the OAuth token is rejected."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    # Every env carries HOME so credential-file discovery stays inside the
    # tmpdir — a real ~/.grok/auth.json on the machine running the suite must
    # never change what these assert.
    def env(self, **overrides):
        env = {"HOME": str(self.tmp)}
        env.update(overrides)
        return env

    def ctx(self, env):
        return pg.RunContext(project_root=self.tmp, env=env, slug="test-post")

    def write_credentials_file(self, payload, rel=".grok/auth.json"):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def generate(self, env, responses):
        """Run one generate() against a scripted response sequence. Entries are
        either exceptions to raise or dicts to return, one per HTTP call."""
        calls = []
        script = list(responses)

        def fake_json(url, payload, headers, timeout=900):
            calls.append({"url": url, "payload": payload, "headers": headers})
            entry = script.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return entry

        out_base = self.tmp / "slug"
        with mock.patch.object(pg, "http_json", fake_json), \
                mock.patch.object(pg, "with_retries", lambda fn, what: fn()):
            result = pg.PROVIDERS["xai"].generate(
                "prompt", make_settings(model=""), out_base, self.ctx(env))
        return result, calls

    @staticmethod
    def status_error(status, message):
        return pg.HttpStatusError(
            status, json.dumps({"error": {"message": message}}).encode(),
            "https://api.x.ai/v1/images/generations")

    @staticmethod
    def ok_response():
        return {"data": [{"b64_json": "R1JPSw=="}]}  # "GROK"

    def test_oauth_token_is_preferred_over_the_api_key(self):
        result, calls = self.generate(
            self.env(XAI_OAUTH_TOKEN="oauth-tok", XAI_API_KEY="xai-key"),
            [self.ok_response()])
        self.assertTrue(result.ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer oauth-tok"})
        self.assertEqual(calls[0]["url"], "https://api.x.ai/v1/images/generations")
        self.assertEqual(result.path.read_bytes(), b"GROK")

    def test_grok_oauth_token_alias(self):
        _, calls = self.generate(self.env(GROK_OAUTH_TOKEN="grok-tok"),
                                 [self.ok_response()])
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer grok-tok"})

    def test_api_key_alone_keeps_the_historical_request_shape(self):
        result, calls = self.generate(self.env(XAI_API_KEY="xai-key"),
                                      [self.ok_response()])
        self.assertTrue(result.ok)
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer xai-key"})
        self.assertEqual(calls[0]["payload"]["model"], "grok-2-image")
        self.assertEqual(calls[0]["payload"]["n"], 1)

    def test_rejected_oauth_token_falls_back_to_the_api_key(self):
        result, calls = self.generate(
            self.env(XAI_OAUTH_TOKEN="stale", XAI_API_KEY="xai-key"),
            [self.status_error(401, "invalid token"), self.ok_response()])
        self.assertTrue(result.ok, "the API key should render after the rejection")
        self.assertEqual([c["headers"]["Authorization"] for c in calls],
                         ["Bearer stale", "Bearer xai-key"])

    def test_forbidden_oauth_token_also_falls_back(self):
        result, calls = self.generate(
            self.env(XAI_OAUTH_TOKEN="t", XAI_API_KEY="k"),
            [self.status_error(403, "forbidden"), self.ok_response()])
        self.assertTrue(result.ok)
        self.assertEqual(len(calls), 2)

    def test_rejected_oauth_token_without_an_api_key_surfaces_the_error(self):
        result, calls = self.generate(self.env(XAI_OAUTH_TOKEN="stale"),
                                      [self.status_error(401, "invalid token")])
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "xAI API error: invalid token")
        self.assertEqual(len(calls), 1)

    def test_non_auth_failures_never_burn_the_fallback(self):
        # A 500 is the endpoint failing, not the credential — swapping tokens
        # would only double the load on an already-struggling API.
        result, calls = self.generate(
            self.env(XAI_OAUTH_TOKEN="t", XAI_API_KEY="k"),
            [self.status_error(500, "upstream down")])
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "xAI API error: upstream down")
        self.assertEqual(len(calls), 1)

    def test_imagine_model_is_sent_the_banner_aspect_ratio(self):
        calls = []

        def fake_json(url, payload, headers, timeout=900):
            calls.append(payload)
            return self.ok_response()

        with mock.patch.object(pg, "http_json", fake_json):
            for model in ("grok-imagine-image-2.0", ""):
                pg.PROVIDERS["xai"].generate(
                    "p", make_settings(model=model, size="1536x1024"),
                    self.tmp / "slug", self.ctx(self.env(XAI_API_KEY="k")))
        self.assertEqual(calls[0]["model"], "grok-imagine-image-2.0")
        self.assertEqual(calls[0]["aspect_ratio"], "3:2")
        # grok-2-image predates the parameter: its request shape is unchanged.
        self.assertEqual(calls[1]["model"], "grok-2-image")
        self.assertNotIn("aspect_ratio", calls[1])

    def test_aspect_ratio_is_the_nearest_imagine_ratio(self):
        imagine = "grok-imagine-image-2.0"
        self.assertEqual(pg.xai_aspect_ratio(imagine, "1792x1024"), "16:9")
        self.assertEqual(pg.xai_aspect_ratio(imagine, "1024x1536"), "2:3")
        self.assertEqual(pg.xai_aspect_ratio(imagine, "1024x1024"), "1:1")
        self.assertIsNone(pg.xai_aspect_ratio(imagine, "auto"))
        self.assertIsNone(pg.xai_aspect_ratio(imagine, "0x1024"))
        self.assertIsNone(pg.xai_aspect_ratio("grok-2-image", "1536x1024"))

    def test_jpeg_render_is_saved_under_a_jpg_name(self):
        jpeg = base64.b64encode(b"\xff\xd8\xff\xe0JFIF").decode("ascii")
        result, _ = self.generate(self.env(XAI_API_KEY="k"),
                                  [{"data": [{"b64_json": jpeg}]}])
        self.assertTrue(result.ok)
        self.assertEqual((result.kind, result.path.name), ("jpg", "slug.jpg"))
        self.assertTrue(result.path.is_file())
        self.assertFalse((self.tmp / "slug.png").exists())

    def test_image_media_type_reads_the_bytes(self):
        self.assertEqual(pg.image_media_type(b"\xff\xd8\xff\xe0"), "image/jpeg")
        self.assertEqual(pg.image_media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(pg.image_media_type(pg.PNG_SIGNATURE), "image/png")
        self.assertEqual(pg.image_media_type(b""), "image/png")

    def test_grok_review_labels_a_jpeg_as_jpeg(self):
        image = self.tmp / "render.jpg"
        image.write_bytes(b"\xff\xd8\xff\xe0JFIF")
        seen = []

        def fake_json(url, payload, headers, timeout=900):
            seen.append(payload)
            return {"choices": [{"message": {"content": "{}"}}]}

        with mock.patch.object(pg, "http_json", fake_json), \
                mock.patch.object(pg, "with_retries", lambda fn, what: fn()):
            pg.GrokClient(self.env(XAI_API_KEY="k")).complete_vision("s", "u", image)
        url = seen[0]["messages"][1]["content"][0]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))

    def test_prompt_cap_is_unchanged(self):
        calls = []

        def fake_json(url, payload, headers, timeout=900):
            calls.append(payload)
            return self.ok_response()

        with mock.patch.object(pg, "http_json", fake_json):
            pg.PROVIDERS["xai"].generate("x" * 1500, make_settings(model=""),
                                         self.tmp / "slug",
                                         self.ctx(self.env(XAI_API_KEY="k")))
        self.assertEqual(calls[0]["prompt"], "x" * 1000)

    def test_oauth_credentials_file_is_read_when_no_token_env_is_set(self):
        self.write_credentials_file({"access_token": "file-tok",
                                     "expires_at": time.time() + 3600})
        _, calls = self.generate(self.env(), [self.ok_response()])
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer file-tok"})

    def test_kilo_access_alias_is_accepted(self):
        self.write_credentials_file(
            {"xai": {"access": "kilo-tok",
                     "expires": int((time.time() + 3600) * 1000)}})
        _, calls = self.generate(self.env(), [self.ok_response()])
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer kilo-tok"})

    def test_nested_and_millisecond_expiry_shapes_are_accepted(self):
        self.write_credentials_file(
            {"xai": {"access_token": "nested-tok",
                     "expires_at": int((time.time() + 3600) * 1000)}})
        _, calls = self.generate(self.env(), [self.ok_response()])
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer nested-tok"})

    def test_expired_file_token_is_treated_as_absent(self):
        self.write_credentials_file({"access_token": "expired-tok",
                                     "expires_at": time.time() - 10})
        # No wasted request on a token we already know is dead.
        _, calls = self.generate(self.env(XAI_API_KEY="xai-key"),
                                 [self.ok_response()])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer xai-key"})

    # --- refresh: an expired token whose store can renew it (Kilo Code's login) ---

    KILO = ".local/share/kilo/auth.json"

    def write_kilo_store(self, **slot):
        record = {"type": "oauth", "access": "old-tok", "refresh": "old-refresh",
                  "client_id": "kilo-client",
                  "expires": int((time.time() - 60) * 1000)}
        record.update(slot)
        path = self.write_credentials_file({"xai": record, "other": {"keep": 1}},
                                           rel=self.KILO)
        os.chmod(path, 0o600)
        return path

    @staticmethod
    def jwt(claims):
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return f"e30.{body}.sig"

    def fake_token_endpoint(self, *responses):
        """Patch http_request with a scripted auth.x.ai: dicts answer 200 with
        that JSON, exceptions are raised. Returns the recorded calls."""
        calls, script = [], list(responses)

        def fake_request(url, method="GET", headers=None, data=None, timeout=120):
            calls.append({"url": url, "method": method, "headers": headers,
                          "form": urllib.parse.parse_qs(data.decode("utf-8"))})
            entry = script.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return 200, {}, json.dumps(entry).encode("utf-8")

        patcher = mock.patch.object(pg, "http_request", fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_expired_kilo_token_is_refreshed_and_saved_in_its_own_shape(self):
        path = self.write_kilo_store()
        refreshes = self.fake_token_endpoint(
            {"access_token": "new-tok", "refresh_token": "new-refresh", "expires_in": 7200})
        result, calls = self.generate(self.env(), [self.ok_response()])
        self.assertTrue(result.ok)
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer new-tok"})
        self.assertEqual(len(refreshes), 1)
        self.assertEqual(refreshes[0]["url"], "https://auth.x.ai/oauth2/token")
        self.assertEqual(refreshes[0]["method"], "POST")
        self.assertEqual(refreshes[0]["form"], {
            "grant_type": ["refresh_token"], "refresh_token": ["old-refresh"],
            "client_id": ["kilo-client"]})
        store = json.loads(path.read_text(encoding="utf-8"))
        slot = store["xai"]
        self.assertEqual((slot["access"], slot["refresh"], slot["type"]),
                         ("new-tok", "new-refresh", "oauth"))
        self.assertNotIn("access_token", slot)          # Kilo's key names kept
        self.assertGreater(slot["expires"], (time.time() + 7000) * 1000)  # still ms
        self.assertEqual(store["other"], {"keep": 1})   # the rest of the store kept
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        # The saved token is fresh, so the next run reads it without refreshing.
        _, again = self.generate(self.env(), [self.ok_response()])
        self.assertEqual(again[0]["headers"], {"Authorization": "Bearer new-tok"})
        self.assertEqual(len(refreshes), 1)

    def test_refresh_reads_client_id_from_the_jwt_when_the_store_has_none(self):
        path = self.write_kilo_store(client_id=None,
                                     access=self.jwt({"aud": ["jwt-client"]}))
        refreshes = self.fake_token_endpoint({"access_token": "new-tok"})
        result, calls = self.generate(self.env(), [self.ok_response()])
        self.assertTrue(result.ok)
        self.assertEqual(refreshes[0]["form"]["client_id"], ["jwt-client"])
        # No rotated refresh token in the answer: the stored one is kept.
        self.assertEqual(json.loads(path.read_text())["xai"]["refresh"], "old-refresh")

    def test_expired_refreshable_token_counts_as_configured_without_a_request(self):
        path = self.write_kilo_store()
        refreshes = self.fake_token_endpoint()   # any request would pop an empty script
        self.assertTrue(pg.PROVIDERS["xai"].is_configured(self.env()))
        self.assertEqual(pg.xai_auth_describe(self.env()),
                         f"Grok OAuth token ({path}; expired, refreshed on use)")
        self.assertEqual(refreshes, [])

    def test_failed_refresh_falls_back_to_the_api_key(self):
        path = self.write_kilo_store()
        before = path.read_text(encoding="utf-8")
        self.fake_token_endpoint(
            pg.HttpStatusError(400, b'{"error":"invalid_grant"}', pg.XAI_TOKEN_ENDPOINT))
        result, calls = self.generate(self.env(XAI_API_KEY="xai-key"), [self.ok_response()])
        self.assertTrue(result.ok)
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer xai-key"})
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_failed_refresh_without_a_fallback_is_an_error_not_a_request(self):
        self.write_kilo_store()
        self.fake_token_endpoint(pg.HttpStatusError(
            400, b'{"error":"invalid_grant","error_description":"echoed input"}',
            pg.XAI_TOKEN_ENDPOINT))
        result, calls = self.generate(self.env(), [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "xAI OAuth refresh failed "
                                       "(HTTP 400: invalid_grant); re-run your Grok login")
        self.assertEqual(calls, [])

    def test_iso_expiry_is_saved_as_iso(self):
        path = self.write_credentials_file(
            {"access_token": "old", "refresh_token": "r", "client_id": "c",
             "expires_at": "2020-01-01T00:00:00Z"})
        self.fake_token_endpoint({"access_token": "new", "expires_in": 3600})
        self.generate(self.env(), [self.ok_response()])
        saved = json.loads(path.read_text())
        self.assertEqual(saved["access_token"], "new")
        self.assertRegex(saved["expires_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsNotNone(pg.xai_auth_describe(self.env()))

    def test_grok_client_refreshes_before_its_first_call(self):
        self.write_kilo_store()
        self.fake_token_endpoint({"access_token": "chat-tok", "expires_in": 3600})
        seen = []

        def fake_json(url, payload, headers, timeout=900):
            seen.append(headers)
            return {"choices": [{"message": {"content": "brief"}}]}

        with mock.patch.object(pg, "http_json", fake_json), \
                mock.patch.object(pg, "with_retries", lambda fn, what: fn()):
            client = pg.GrokClient(self.env())
            self.assertTrue(client.available())
            self.assertEqual(client.complete("sys", "user"), "brief")
        self.assertEqual(seen, [{"Authorization": "Bearer chat-tok"}])

    def test_expires_in_needs_an_issue_time_to_mean_anything(self):
        path = self.write_credentials_file({"access_token": "lifetime-only",
                                            "expires_in": 3600})
        self.assertEqual(pg.xai_auth_describe(self.env()),
                         f"Grok OAuth token ({path})")
        self.write_credentials_file({"access_token": "aged", "expires_in": 3600,
                                     "created_at": "2020-01-01T00:00:00Z"})
        self.assertIsNone(pg.xai_auth_describe(self.env()))

    def test_credentials_file_env_override_wins_outright(self):
        self.write_credentials_file({"access_token": "default-location"})
        explicit = self.tmp / "elsewhere" / "grok.json"
        explicit.parent.mkdir(parents=True, exist_ok=True)
        explicit.write_text(json.dumps({"access_token": "explicit-location"}),
                            encoding="utf-8")
        _, calls = self.generate(self.env(GROK_OAUTH_CREDENTIALS=str(explicit)),
                                 [self.ok_response()])
        self.assertEqual(calls[0]["headers"],
                         {"Authorization": "Bearer explicit-location"})
        # A configured-but-missing path must not silently fall back to ~/.grok.
        self.assertIsNone(pg.xai_auth_describe(
            self.env(GROK_OAUTH_CREDENTIALS=str(self.tmp / "nope.json"))))

    def test_unreadable_credentials_file_is_skipped_not_fatal(self):
        self.write_credentials_file("not json at all")   # a bare JSON string
        self.assertIsNone(pg.xai_auth_describe(self.env()))
        (self.tmp / ".grok" / "auth.json").write_text("{{{ broken", encoding="utf-8")
        self.assertIsNone(pg.xai_auth_describe(self.env()))
        self.write_credentials_file({"refresh_token": "no access token here"})
        self.assertIsNone(pg.xai_auth_describe(self.env()))

    def test_xai_auth_pins_one_rung(self):
        both = dict(XAI_OAUTH_TOKEN="t", XAI_API_KEY="k")
        self.assertEqual(
            pg.xai_auth_describe(self.env(XAI_AUTH="api_key", **both)),
            "XAI_API_KEY (xAI API key)")
        self.assertEqual(
            pg.xai_auth_describe(self.env(XAI_AUTH="oauth", **both)),
            "XAI_OAUTH_TOKEN (Grok OAuth token)")
        self.assertFalse(pg.PROVIDERS["xai"].is_configured(
            self.env(XAI_AUTH="oauth", XAI_API_KEY="k")))
        # An unknown value is not a hard error; it degrades to the default ladder.
        self.assertEqual(
            pg.xai_auth_describe(self.env(XAI_AUTH="nonsense", **both)),
            "XAI_OAUTH_TOKEN (Grok OAuth token), falling back to "
            "XAI_API_KEY (xAI API key)")

    def test_base_url_override(self):
        _, calls = self.generate(
            self.env(XAI_BASE_URL="https://gateway.test/v1/", XAI_OAUTH_TOKEN="t"),
            [self.ok_response()])
        self.assertEqual(calls[0]["url"], "https://gateway.test/v1/images/generations")

    def test_is_configured_and_missing_hint(self):
        provider = pg.PROVIDERS["xai"]
        self.assertFalse(provider.is_configured(self.env()))
        self.assertTrue(provider.is_configured(self.env(XAI_API_KEY="k")))
        self.assertTrue(provider.is_configured(self.env(XAI_OAUTH_TOKEN="t")))
        self.write_credentials_file({"access_token": "file-tok"})
        self.assertTrue(provider.is_configured(self.env()))

        hint = provider.missing_hint(self.env())
        for expected in ("XAI_OAUTH_TOKEN", "XAI_API_KEY", "~/.grok/auth.json"):
            self.assertIn(expected, hint)

    def test_generate_without_any_credential_reports_the_hint(self):
        result, calls = self.generate(self.env(), [])
        self.assertFalse(result.ok)
        self.assertEqual(result.error, pg.XAI_MISSING_HINT)
        self.assertEqual(calls, [])

    def test_auto_provider_promotes_xai_on_an_oauth_token_alone(self):
        # resolve_auto_provider asks each renderer whether it is configured, so
        # an OAuth-only machine reaches the xAI rung with no XAI_API_KEY set.
        settings = pg.resolve_auto_provider(make_settings(provider="auto"),
                                            self.env(XAI_OAUTH_TOKEN="t"))
        self.assertEqual(settings.provider, "xai")


class _FakeClaude:
    """Duck-typed stand-in for AnthropicClient in orchestration tests."""

    def __init__(self, text_reply=None, vision_reply=None, raise_exc=None):
        self.text_reply = text_reply
        self.vision_reply = vision_reply
        self.raise_exc = raise_exc
        self.complete_calls = []
        self.vision_calls = []

    def available(self):
        return True

    def complete(self, system_text, user_text, model=None, max_tokens=None,
                 effort=""):
        self.complete_calls.append((system_text, user_text, model))
        if self.raise_exc:
            raise self.raise_exc
        return self.text_reply or ""

    def complete_vision(self, system_text, user_text, image_path, model=None,
                        max_tokens=None, effort=""):
        self.vision_calls.append((system_text, user_text, image_path, model))
        if self.raise_exc:
            raise self.raise_exc
        return self.vision_reply or ""


def make_content_file(tmp: Path) -> "pg.ContentFile":
    path = tmp / "post.md"
    path.write_text("---\ntitle: T\n---\nBody\n", encoding="utf-8")
    return pg.ContentFile(
        path=path, title="Auto-hide Navigation",
        description="Smart nav bar that hides on scroll",
        categories="docs, features", preview=None, author=None,
        content="The top navigation bar gets out of the way while you read.",
        front_matter={"title": "Auto-hide Navigation"},
    )


class TestClaudeOrchestration(unittest.TestCase):
    def test_article_brief_uses_art_director_and_article_context(self):
        client = _FakeClaude(text_reply="A pixel-art nav bar sliding away.")
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            brief = pg.claude_article_brief(client, cf, make_settings(), "base")
        self.assertEqual(brief, "A pixel-art nav bar sliding away.")
        system, user, model = client.complete_calls[0]
        self.assertEqual(system, pg.ART_DIRECTOR_SYSTEM)
        self.assertIn("Auto-hide Navigation", user)
        self.assertIn("hides on scroll", user)
        self.assertEqual(model, pg.DEFAULT_CLAUDE_MODEL)

    def test_article_brief_falls_back_on_failure(self):
        client = _FakeClaude(raise_exc=RuntimeError("boom"))
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            self.assertEqual(
                pg.claude_article_brief(client, cf, make_settings(), "base"), "base")

    def test_claude_model_setting_respected(self):
        client = _FakeClaude(text_reply="brief")
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            pg.claude_article_brief(
                client, cf, make_settings(claude_model="claude-sonnet-5"), "base")
        self.assertEqual(client.complete_calls[0][2], "claude-sonnet-5")

    def test_review_approve(self):
        client = _FakeClaude(
            vision_reply='{"verdict": "approve", "critique": "good", "revised_prompt": ""}')
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            img = Path(tmp) / "x.png"
            img.write_bytes(pg.PNG_SIGNATURE)
            approved, critique, revised = pg.claude_review_image(
                client, img, cf, "prompt", make_settings())
        self.assertTrue(approved)
        self.assertEqual(revised, "")
        self.assertEqual(client.vision_calls[0][0], pg.REVIEWER_SYSTEM)

    def test_review_revise(self):
        client = _FakeClaude(
            vision_reply='noise {"verdict": "revise", "critique": "wrong subject", '
                         '"revised_prompt": "better prompt"} trailing')
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            img = Path(tmp) / "x.png"
            img.write_bytes(pg.PNG_SIGNATURE)
            approved, critique, revised = pg.claude_review_image(
                client, img, cf, "prompt", make_settings())
        self.assertFalse(approved)
        self.assertEqual(revised, "better prompt")
        self.assertEqual(critique, "wrong subject")

    def test_review_garbage_counts_as_approval(self):
        client = _FakeClaude(vision_reply="I like it a lot!")
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            img = Path(tmp) / "x.png"
            img.write_bytes(pg.PNG_SIGNATURE)
            approved, _, revised = pg.claude_review_image(
                client, img, cf, "prompt", make_settings())
        self.assertTrue(approved)
        self.assertEqual(revised, "")

    def test_review_failure_counts_as_approval(self):
        client = _FakeClaude(raise_exc=RuntimeError("api down"))
        with tempfile.TemporaryDirectory() as tmp:
            cf = make_content_file(Path(tmp))
            img = Path(tmp) / "x.png"
            img.write_bytes(pg.PNG_SIGNATURE)
            approved, _, _ = pg.claude_review_image(
                client, img, cf, "prompt", make_settings())
        self.assertTrue(approved)

    def test_extract_json_object(self):
        self.assertEqual(pg._extract_json_object('x {"a": 1} y'), {"a": 1})
        self.assertIsNone(pg._extract_json_object("no json"))
        self.assertIsNone(pg._extract_json_object("{broken"))

    def test_complete_vision_api_payload(self):
        captured = {}

        def fake_http_json(url, payload, headers, timeout=900):
            captured["payload"] = payload
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "{}"}]}

        with mock.patch.object(pg.shutil, "which", return_value=None):
            client = pg.AnthropicClient({"ANTHROPIC_API_KEY": "k"})
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "x.png"
            img.write_bytes(b"PNGBYTES")
            with mock.patch.object(pg, "http_json", fake_http_json):
                client.complete_vision("sys", "user", img)
        content = captured["payload"]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[0]["source"]["media_type"], "image/png")
        self.assertEqual(
            content[0]["source"]["data"],
            __import__("base64").b64encode(b"PNGBYTES").decode("ascii"))
        self.assertEqual(content[1]["text"], "user")
        # api_key mode: no Claude Code identity block
        self.assertEqual(len(captured["payload"]["system"]), 1)


class TestRunnerReviewLoop(unittest.TestCase):
    def _run(self, review_replies, generate_results):
        """Drive Runner.process_file with mocked renderer + reviewer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets" / "images" / "previews").mkdir(parents=True)
            post = root / "post.md"
            post.write_text(
                "---\ntitle: Test Post\ndescription: D\n---\nBody\n",
                encoding="utf-8")

            settings = make_settings(
                provider="openai", prompt_engine="template",
                review_engine="claude", parallel=1)
            runner = pg.Runner(settings, root)

            calls = {"generate": []}

            def fake_generate(prompt, fsettings, out_base, fctx):
                calls["generate"].append(prompt)
                result = generate_results[len(calls["generate"]) - 1]
                if result:
                    png = out_base.with_suffix(".png")
                    png.write_bytes(pg.PNG_SIGNATURE + prompt.encode())
                    return pg.ImageResult(True, "png", png)
                return pg.ImageResult(False, error="render failed")

            reviews = iter(review_replies)

            def fake_review(client, image_path, cf, prompt, fsettings):
                return next(reviews)

            with mock.patch.object(pg.PROVIDERS["openai"], "generate", fake_generate), \
                 mock.patch.object(pg, "claude_review_image", fake_review), \
                 mock.patch.object(pg.RunContext, "claude",
                                   lambda self: _FakeClaude(text_reply="x")):
                runner.process_file(post)

            png = root / "assets" / "images" / "previews" / "test-post.png"
            content = png.read_bytes() if png.exists() else b""
            return calls["generate"], runner.stats, content

    def test_approved_image_generates_once(self):
        prompts, stats, _ = self._run(
            review_replies=[(True, "fine", "")],
            generate_results=[True])
        self.assertEqual(len(prompts), 1)
        self.assertEqual(stats.generated, 1)
        self.assertEqual(stats.errors, 0)

    def test_revision_regenerates_with_claude_prompt(self):
        prompts, stats, content = self._run(
            review_replies=[(False, "wrong subject", "REVISED BRIEF")],
            generate_results=[True, True])
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[1], "REVISED BRIEF")
        self.assertIn(b"REVISED BRIEF", content)  # second render kept
        self.assertEqual(stats.generated, 1)

    def test_failed_revision_keeps_first_image(self):
        prompts, stats, content = self._run(
            review_replies=[(False, "meh", "REVISED BRIEF")],
            generate_results=[True, False])
        self.assertEqual(len(prompts), 2)
        self.assertNotIn(b"REVISED BRIEF", content)  # first render kept
        self.assertEqual(stats.generated, 1)
        self.assertEqual(stats.errors, 0)


class TestMultipartBuilder(unittest.TestCase):
    def test_fields_and_files_encoded(self):
        body, content_type = pg.build_multipart(
            {"prompt": "hello"}, [("image[]", "a.png", b"BYTES", "image/png")]
        )
        self.assertIn("multipart/form-data; boundary=", content_type)
        boundary = content_type.split("boundary=")[1]
        self.assertIn(f"--{boundary}".encode(), body)
        self.assertIn(b'name="prompt"\r\n\r\nhello', body)
        self.assertIn(b'filename="a.png"', body)
        self.assertIn(b"BYTES", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))


class TestHttpUserAgent(unittest.TestCase):
    """Every request names the engine unless the caller names a client: a CDN
    rejects urllib's stock signature (Cloudflare `error code: 1010` on api.x.ai)."""

    def sent_request(self, headers):
        seen = []

        class Response:
            status, headers = 200, {}

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            seen.append(req)
            return Response()

        with mock.patch.object(pg.urllib.request, "urlopen", fake_urlopen):
            pg.http_request("https://api.x.ai/v1/images/generations", "POST", headers, b"{}")
        return seen[0]

    def test_default_user_agent(self):
        self.assertEqual(self.sent_request({}).get_header("User-agent"),
                         "zer0-image-generator")

    def test_caller_user_agent_wins(self):
        req = self.sent_request({"user-agent": "custom/1"})
        self.assertEqual(req.get_header("User-agent"), "custom/1")


class TestHttpErrorParsing(unittest.TestCase):
    def test_error_message_extraction(self):
        exc = pg.HttpStatusError(
            429, b'{"error": {"message": "slow down"}}', "https://api")
        self.assertEqual(exc.message(), "slow down")
        self.assertEqual(exc.status, 429)

    def test_non_json_body(self):
        exc = pg.HttpStatusError(500, b"<html>oops</html>", "https://api")
        self.assertIn("oops", exc.message())

    def test_retry_after_prefers_http_header(self):
        """Providers send Retry-After as an HTTP header — it must be read."""
        exc = pg.HttpStatusError(429, b"{}", "https://api",
                                 headers={"Retry-After": "31"})
        self.assertEqual(exc.retry_after(), 31.0)

    def test_retry_after_json_fallback_and_default(self):
        exc = pg.HttpStatusError(429, b'{"retry_after": 7}', "https://api")
        self.assertEqual(exc.retry_after(), 7.0)
        self.assertEqual(pg.HttpStatusError(500, b"x", "u").retry_after(), 0.0)

    def test_with_retries_honors_retry_after_header(self):
        calls = {"n": 0}
        sleeps = []

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise pg.HttpStatusError(429, b"{}", "u",
                                         headers={"retry-after": "5"})
            return "done"

        with mock.patch.object(pg.time, "sleep", sleeps.append):
            self.assertEqual(pg.with_retries(flaky, "test"), "done")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [5.0])  # header wait wins over the 2s ladder


class TestDotenv(unittest.TestCase):
    def _load(self, content, pre_env):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text(content, encoding="utf-8")
            with mock.patch.dict(os.environ, pre_env, clear=False):
                for key in ("PG_TEST_A", "PG_TEST_B", "PG_TEST_C"):
                    if key not in pre_env:
                        os.environ.pop(key, None)
                pg._load_dotenv(start=Path(tmp))
                return {k: os.environ.get(k) for k in
                        ("PG_TEST_A", "PG_TEST_B", "PG_TEST_C")}

    def test_empty_env_var_does_not_shadow_dotenv(self):
        """docker/VS Code forward `-e KEY=${env:KEY}` as empty strings; a real
        value in .env must still win over an EMPTY exported variable."""
        result = self._load("PG_TEST_A=real-value\n", {"PG_TEST_A": ""})
        self.assertEqual(result["PG_TEST_A"], "real-value")

    def test_nonempty_env_var_wins(self):
        result = self._load("PG_TEST_A=file-value\n", {"PG_TEST_A": "env-value"})
        self.assertEqual(result["PG_TEST_A"], "env-value")

    def test_inline_comment_and_quotes(self):
        result = self._load(
            'PG_TEST_A=sk-token  # prod key\nPG_TEST_B="quoted # not comment"\n'
            "PG_TEST_C='single'\n", {})
        self.assertEqual(result["PG_TEST_A"], "sk-token")
        self.assertEqual(result["PG_TEST_B"], "quoted # not comment")
        self.assertEqual(result["PG_TEST_C"], "single")


class TestValidateCredentials(unittest.TestCase):
    def test_unknown_provider_errors_even_in_dry_run(self):
        settings = make_settings(provider="bogus", dry_run=True)
        ctx = pg.RunContext(project_root=Path("."), env={})
        with self.assertRaises(SystemExit):
            pg.validate_credentials(settings, ctx)

    def test_known_provider_skips_credential_check_in_dry_run(self):
        settings = make_settings(provider="openai", dry_run=True)
        ctx = pg.RunContext(project_root=Path("."), env={})  # no key set
        pg.validate_credentials(settings, ctx)  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
