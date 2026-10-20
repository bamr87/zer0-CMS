#!/usr/bin/env python3
"""Tests for the `claude` provider's illustration loop (engine 0.10).

plan → author → shape → look → critique → edit → commit, plus the
deterministic pieces underneath it: the strict lint gate, the stdlib TrueType
reader + text→paths, headline fitting, style cards, telemetry and --changed.

Zero network: the model is a scripted fake, and LOOK is stubbed unless a real
resvg/rsvg is on PATH (TestRealRender).

    python3 test/test_illustration_loop.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib" / "zer0_image_generator"))

import preview_generator as pg  # noqa: E402

pg.POST_GENERATION_SLEEP = 0

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024" width="1536" '
    'height="1024" role="img"><title>Probe over the Moon</title>'
    '<rect width="1536" height="1024" fill="#0b132b"/>'
    '<circle cx="1100" cy="380" r="220" fill="#5bc0be"/>'
    '<text x="768" y="900" font-family="Inter" font-weight="700" font-size="72" '
    'text-anchor="middle" fill="#e8f1f2">Chandrayaan-1 Reaches the Moon</text></svg>'
)
DANGLING_SVG = GOOD_SVG.replace('fill="#5bc0be"', 'fill="url(#glow)"')

PLAN_JSON = json.dumps({
    "subject": "A small probe arcing around a cratered moon",
    "focal_point": {"x": 0.7, "y": 0.35, "element": "the probe"},
    "palette": {"bg": "#0b132b", "shadow": "#1c2541", "low_mid": "#1c7293",
                "mid": "#5bc0be", "accent": "#9fd8d6", "highlight": "#e8f1f2"},
    "layers": [
        {"role": "background", "description": "starfield", "tokens": ["bg", "shadow"]},
        {"role": "subject", "description": "moon + probe", "tokens": ["mid", "highlight"]},
        {"role": "text", "description": "title block", "tokens": ["highlight"]},
    ],
    "symmetry_break": "the probe's single solar panel",
    "headline_placement": "bottom",
    "avoid": ["mission stats", "tiny labels"],
})


def critique(overall, holds=True, next_change="enlarge the probe"):
    return json.dumps({"works": "clear moon silhouette", "fails": ["probe too small"],
                       "next_change": next_change, "overall": overall,
                       "thumbnail_holds": holds})


class ScriptedClaude:
    """Duck-typed AnthropicClient: replies are consumed in call order, and
    every call records a usage entry the way the real client does."""

    def __init__(self, text_replies, vision_replies=()):
        self.text_replies = list(text_replies)
        self.vision_replies = list(vision_replies)
        self.text_calls = []
        self.vision_calls = []

    def available(self):
        return True

    def _usage(self, usage, model):
        if usage is not None:
            record = {"model": model, "input_tokens": 1000, "output_tokens": 500,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
            record["cost_usd"] = pg.usage_cost_usd(record)
            usage.append(record)

    def complete(self, system_text, user_text, model=None, max_tokens=None, effort="",
                 json_schema=None, usage=None):
        self.text_calls.append({"system": system_text, "user": user_text,
                                "schema": json_schema, "model": model})
        self._usage(usage, model)
        reply = self.text_replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def complete_vision(self, system_text, user_text, image_path, model=None,
                        max_tokens=None, effort="", json_schema=None, usage=None):
        self.vision_calls.append({"user": user_text, "images": image_path,
                                  "schema": json_schema})
        self._usage(usage, model)
        return self.vision_replies.pop(0)


def fake_look(svg, workdir, stem, settings, project_root):
    full, thumb = workdir / f"{stem}.png", workdir / f"{stem}-thumb.png"
    full.write_bytes(PNG_1PX)
    thumb.write_bytes(PNG_1PX)
    return full, thumb, "fake"


ARTICLE = {"slug": "chandrayaan-1", "section": "space", "categories": "space, india",
           "title": "Chandrayaan-1 Reaches the Moon",
           "description": "India's first lunar probe", "body": "The probe entered orbit."}


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        patcher = mock.patch.object(pg, "look_svg", side_effect=fake_look)
        self.look = patcher.start()
        self.addCleanup(patcher.stop)

    def ctx(self, client):
        return pg.RunContext(project_root=self.tmp, env={}, anthropic=client,
                             slug="chandrayaan-1", article=dict(ARTICLE))

    def settings(self, **kw):
        base = dict(provider="claude", rasterizer="none", style_card="retro-pixel",
                    claude_model="claude-sonnet-5-5")
        base.update(kw)
        return pg.Settings(**base)

    def generate(self, client, **kw):
        settings = self.settings(**kw)
        ctx = self.ctx(client)
        ctx.budget.cap_usd = settings.claude_budget_usd
        out_base = self.tmp / "out" / "chandrayaan-1"
        out_base.parent.mkdir(parents=True, exist_ok=True)
        return pg.PROVIDERS["claude"].generate("prompt", settings, out_base, ctx), client


class TestLoopHappyPath(LoopCase):
    def test_plan_author_critique_pass_commits_strict_clean_svg_with_paths(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG], [critique(8.5)])
        result, _ = self.generate(client)
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "svg")
        svg = result.path.read_text()
        self.assertNotIn("<text", svg)
        self.assertIn('aria-label="Chandrayaan-1 Reaches the Moon"', svg)
        report = pg.lint_svg(svg.encode(), "x", max_kb=300, strict=True)
        self.assertTrue(report.clean, report.findings())
        meta = result.meta
        self.assertTrue(meta["plan"])
        self.assertEqual(meta["calls"], 3)                 # plan, author, critique
        self.assertEqual(meta["rounds_used"], 0)
        self.assertEqual(meta["critic"]["overall"], 8.5)
        self.assertEqual(meta["text"]["converted"], 1)
        self.assertIsNone(meta["fallback"])
        self.assertEqual(len(meta["usage"]), 3)

    def test_plan_uses_structured_output_and_fixed_palette_wins(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG], [critique(9)])
        self.generate(client, palette=list(pg.BANNER_PALETTES["ember"]))
        self.assertIs(client.text_calls[0]["schema"], pg.PLAN_SCHEMA)
        self.assertIn('"headline_placement": "bottom"', client.text_calls[0]["user"])
        author_prompt = client.text_calls[1]["user"]
        self.assertIn('"bg": "#120b16"', author_prompt)     # policy palette, not the model's
        self.assertIn("FIXED PALETTE", author_prompt)
        self.assertIn("STYLE CARD — Style: Retro Pixel", author_prompt)

    def test_author_gets_a_precomputed_headline_in_the_card_font(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG], [critique(9)])
        self.generate(client)
        prompt = client.text_calls[1]["user"]
        self.assertIn('font-family="Press Start 2P"', prompt)
        headline = pg.plan_headline(ARTICLE["title"], "bottom", "press-start-2p")
        for line in headline.lines:
            self.assertIn(f'"{line}"', prompt)
        self.assertEqual(" ".join(headline.lines), ARTICLE["title"])

    def test_critique_sees_full_and_thumbnail_renders(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG], [critique(9)])
        self.generate(client)
        images = client.vision_calls[0]["images"]
        self.assertEqual(len(images), 2)
        self.assertTrue(str(images[1]).endswith("-thumb.png"))
        self.assertIs(client.vision_calls[0]["schema"], pg.CRITIQUE_SCHEMA)


class TestLoopRounds(LoopCase):
    def test_failing_critique_triggers_one_edit_and_keeps_the_better_draft(self):
        edited = GOOD_SVG.replace('r="220"', 'r="300"')
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG, edited], [critique(5, False), critique(8)])
        result, _ = self.generate(client)
        self.assertEqual(result.meta["rounds_used"], 1)
        self.assertEqual(result.meta["critic"]["overall"], 8)
        self.assertIn('r="300"', result.path.read_text())
        edit_prompt = client.text_calls[2]["user"]
        self.assertIn("REQUIRED NEXT CHANGE: enlarge the probe", edit_prompt)
        self.assertIn("does NOT hold", edit_prompt)

    def test_a_worse_edit_loses_best_of(self):
        edited = GOOD_SVG.replace('r="220"', 'r="20"')
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG, edited], [critique(6), critique(4)])
        result, _ = self.generate(client)
        self.assertIn('r="220"', result.path.read_text())
        self.assertEqual(result.meta["critic"]["overall"], 6)

    def test_thumbnail_failure_blocks_an_otherwise_passing_score(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG, GOOD_SVG],
                                [critique(9, holds=False), critique(9, holds=True)])
        result, _ = self.generate(client)
        self.assertEqual(result.meta["rounds_used"], 1)

    def test_require_thumbnail_off_accepts_the_score_alone(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG], [critique(9, holds=False)])
        result, _ = self.generate(client, claude_require_thumbnail=False)
        self.assertEqual(result.meta["rounds_used"], 0)

    def test_rounds_zero_is_one_shot_with_no_render_or_review(self):
        client = ScriptedClaude([GOOD_SVG])
        result, _ = self.generate(client, claude_rounds=0, claude_plan=False)
        self.assertTrue(result.ok)
        self.assertEqual(client.vision_calls, [])
        self.look.assert_not_called()
        self.assertEqual(result.meta["calls"], 1)

    def test_no_rasterizer_commits_unreviewed(self):
        self.look.side_effect = lambda *a, **k: None
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG])
        result, _ = self.generate(client)
        self.assertTrue(result.ok)
        self.assertIsNone(result.meta["critic"])


class TestLoopDegrades(LoopCase):
    def test_lint_failure_gets_one_fix_round(self):
        client = ScriptedClaude([PLAN_JSON, DANGLING_SVG, GOOD_SVG], [critique(9)])
        result, _ = self.generate(client)
        self.assertTrue(result.meta["fix_round"])
        self.assertIn("missing id(s): glow", client.text_calls[2]["user"])
        self.assertIsNone(result.meta["fallback"])

    def test_still_broken_after_fix_falls_back_to_local_art(self):
        client = ScriptedClaude([PLAN_JSON, DANGLING_SVG, DANGLING_SVG])
        result, _ = self.generate(client)
        self.assertTrue(result.ok)
        self.assertEqual(result.meta["fallback"], "lint")
        self.assertNotIn("url(#glow)", result.path.read_text())
        self.assertEqual(client.vision_calls, [])

    def test_author_exception_falls_back_to_local_art(self):
        client = ScriptedClaude([PLAN_JSON, RuntimeError("overloaded")])
        result, _ = self.generate(client)
        self.assertTrue(result.ok)
        self.assertEqual(result.meta["fallback"], "author_failed")

    def test_unusable_plan_still_authors(self):
        client = ScriptedClaude(["not json", GOOD_SVG], [critique(9)])
        result, _ = self.generate(client)
        self.assertFalse(result.meta["plan"])
        self.assertTrue(result.ok)
        self.assertIsNone(result.meta["fallback"])

    def test_budget_cap_skips_review_then_authoring(self):
        client = ScriptedClaude([PLAN_JSON, GOOD_SVG])
        # Each scripted call is 1000 in / 500 out on Sonnet ≈ $0.007; cap below two.
        result, _ = self.generate(client, claude_budget_usd=0.01)
        self.assertIn("critique", result.meta.get("budget_skipped", []))
        self.assertEqual(client.vision_calls, [])

    def test_exhausted_budget_never_calls_the_model(self):
        client = ScriptedClaude([])
        settings = self.settings(claude_budget_usd=0.001)
        ctx = self.ctx(client)
        ctx.budget.cap_usd = 0.001
        ctx.budget.spent_usd = 1.0
        result = pg.PROVIDERS["claude"].generate("p", settings, self.tmp / "o", ctx)
        self.assertEqual(result.meta["fallback"], "budget")
        self.assertEqual(client.text_calls, [])


class TestLintGate(unittest.TestCase):
    CASES = {
        "clean": GOOD_SVG.replace("<text", "<desc").replace("</text>", "</desc>"),
        "text": GOOD_SVG,
        "dangling": DANGLING_SVG,
        "no_viewbox": '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
        "broken": "<svg><rect></svg>",
        "raster": ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/'
                   '1999/xlink" viewBox="0 0 10 10" role="img"><title>t</title><image '
                   'xlink:href="data:image/png;base64,AAAA"/></svg>'),
    }

    def test_svg_check_cli_is_a_thin_wrapper_over_lint_svg(self):
        tool = REPO_ROOT / "tools" / "svg" / "svg-check.py"
        with tempfile.TemporaryDirectory() as tmp:
            for name, svg in self.CASES.items():
                path = Path(tmp) / f"{name}.svg"
                path.write_text(svg)
                for strict in (False, True):
                    args = [sys.executable, str(tool), str(path)] + (["--strict"] if strict else [])
                    proc = subprocess.run(args, capture_output=True, text=True)
                    report = pg.lint_svg(svg.encode(), str(path), strict=strict)
                    self.assertEqual(proc.returncode, 0 if report.clean else 1, name)
                    self.assertEqual(proc.stderr.splitlines(), report.stderr_lines(), name)
                    self.assertEqual(proc.stdout.splitlines(), report.stdout_lines(), name)

    def test_strict_flags_text_and_dangling_refs(self):
        self.assertIn(pg.LINT_TEXT_WARNING,
                      pg.lint_svg(GOOD_SVG.encode(), strict=True).warnings)
        self.assertNotIn(pg.LINT_TEXT_WARNING, pg.lint_svg(GOOD_SVG.encode()).warnings)
        dangling = pg.lint_svg(DANGLING_SVG.encode(), strict=True)
        self.assertFalse(dangling.clean)
        self.assertTrue(any("glow" in e for e in dangling.errors))

    def test_round_svg_precision_only_touches_geometry(self):
        svg = '<path d="M1.23456 2.5L3.999 -4.0001" opacity="0.12345"/>'
        self.assertEqual(pg.round_svg_precision(svg),
                         '<path d="M1.23 2.5L4 -4" opacity="0.12345"/>')


class TestFonts(unittest.TestCase):
    def test_bundled_fonts_parse(self):
        self.assertTrue(pg.fonts_available())
        for family in pg.BUNDLED_FONTS:
            font = pg.load_bundled_font(family)
            self.assertGreater(font.units_per_em, 0)
            self.assertGreater(font.advance(font.glyph_id("M")), 0)
            self.assertTrue(font.contours(font.glyph_id("A")))

    def test_composite_glyphs_resolve(self):
        font = pg.load_bundled_font("inter")
        plain = font.contours(font.glyph_id("e"))
        accented = font.contours(font.glyph_id("é"))
        self.assertGreater(len(accented), len(plain))

    def test_fmt2_is_floor_half_up(self):
        cases = {0.0: "0", -0.001: "0", 1.006: "1.01", 2.5: "2.5", -3.0: "-3",
                 -2.344: "-2.34", -2.346: "-2.35", 12.999: "13", 0.07: "0.07"}
        for value, expected in cases.items():
            self.assertEqual(pg._fmt2(value), expected, value)

    def test_glyph_run_path_is_stable(self):
        """Golden prefix — the Ruby twin is pinned to these exact bytes."""
        font = pg.load_bundled_font("inter-bold")
        d, advance, missing = pg.glyph_run_path(font, "Hi", 10, 100, 48)
        self.assertTrue(d.startswith("M12.6 100L12.6 65.08L19.82 65.08"), d[:60])
        self.assertEqual(missing, 0)
        self.assertAlmostEqual(advance, pg.text_advance(font, "Hi", 48))

    def test_missing_glyphs_are_counted_not_drawn(self):
        font = pg.load_bundled_font("inter")
        d, _adv, missing = pg.glyph_run_path(font, "a中", 0, 0, 20)
        self.assertEqual(missing, 1)
        self.assertTrue(d)

    def test_fit_headline_never_splits_words(self):
        font = pg.load_bundled_font("press-start-2p")
        title = "Chandrayaan-1 India's First Lunar Probe"
        lines, size = pg.fit_headline(font, title, 600, 3, 64, 24)
        self.assertEqual(" ".join(lines), title)
        for line in lines:
            for word in line.split():
                self.assertIn(word, title.split())
        self.assertLessEqual(len(lines), 3)
        self.assertGreaterEqual(size, 24)

    def test_fit_headline_respects_block_height(self):
        font = pg.load_bundled_font("inter-bold")
        lines, size = pg.fit_headline(font, "A B C D E F G H", 200, 3, 120, 20,
                                      max_height=200, leading=1.25)
        self.assertLessEqual(len(lines) * size * 1.25, 200)

    def test_resolve_font_family(self):
        self.assertEqual(pg.resolve_font_family("'Press Start 2P', monospace", "", "inter"),
                         "press-start-2p")
        self.assertEqual(pg.resolve_font_family("Helvetica", "bold", "inter"), "inter-bold")
        self.assertEqual(pg.resolve_font_family("Helvetica", "400", "press-start-2p"),
                         "press-start-2p")


class TestTextToPaths(unittest.TestCase):
    def convert(self, svg, mode="paths", family="inter"):
        clean, _ = pg.sanitize_svg(svg)
        return pg.svg_text_to_paths(clean, mode, family)

    def test_paths_mode_replaces_text_and_keeps_paint(self):
        r = self.convert(GOOD_SVG)
        self.assertEqual(r.converted, 1)
        self.assertNotIn("<text", r.svg)
        self.assertRegex(r.svg, r'<g fill="#e8f1f2" aria-label="Chandrayaan-1 Reaches the Moon">')

    def test_css_class_and_element_rules_resolve(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024"><style>'
               ".h{font-family:'Press Start 2P';font-size:40px} text{fill:#ff0}</style>"
               '<text class="h" x="10" y="100">HI</text></svg>')
        r = self.convert(svg)
        self.assertIn('class="h"', r.svg)
        self.assertIn('fill="#ff0"', r.svg)          # element rule copied across
        font = pg.load_bundled_font("press-start-2p")
        expected, _, _ = pg.glyph_run_path(font, "HI", 10, 100, 40)
        self.assertIn(f'd="{expected}"', r.svg)

    def test_tspans_become_paths_with_their_own_paint(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024">'
               '<text x="100" y="100" font-size="40" fill="#111">A <tspan fill="#f00">B'
               '</tspan><tspan x="100" dy="1.5em">C</tspan></text></svg>')
        r = self.convert(svg)
        self.assertEqual(r.svg.count("<path"), 3)
        self.assertIn('fill="#f00"', r.svg)
        self.assertIn('aria-label="A B C"', r.svg)

    def test_overlong_lines_are_scaled_into_the_frame(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024">'
               '<text x="768" y="500" font-size="200" text-anchor="middle">'
               'An absurdly long headline that cannot fit</text></svg>')
        r = self.convert(svg)
        self.assertEqual(r.fitted, 1)
        xs = [float(n) for n in re.findall(r"[ML](-?[\d.]+) ", r.svg)]
        self.assertGreaterEqual(min(xs), 0)
        self.assertLessEqual(max(xs), 1536)

    def test_text_near_the_edge_is_left_alone(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1536 1024">'
               '<text x="10" y="100" font-size="40">Edge</text></svg>')
        r = self.convert(svg)
        self.assertEqual(r.fitted, 0)
        self.assertRegex(r.svg, r'd="M1\d\.\d')

    def test_forbid_strips_and_keep_leaves(self):
        self.assertEqual(self.convert(GOOD_SVG, "forbid").stripped, 1)
        kept = self.convert(GOOD_SVG, "keep")
        self.assertIn("<text", kept.svg)

    def test_missing_fonts_degrade_to_strip(self):
        with mock.patch.object(pg, "FONTS_DIR", Path("/nonexistent")):
            r = self.convert(GOOD_SVG)
        self.assertEqual(r.stripped, 1)
        self.assertTrue(any("fonts not found" in n for n in r.notes))


class TestPlanAndCritique(unittest.TestCase):
    def test_validate_plan_normalizes(self):
        plan = pg.validate_plan(json.loads(PLAN_JSON), [])
        self.assertEqual(plan["palette"]["mid"], "#5bc0be")
        self.assertEqual(plan["headline_placement"], "bottom")
        bad = json.loads(PLAN_JSON)
        bad["focal_point"]["x"] = 7
        bad["headline_placement"] = "diagonal"
        plan = pg.validate_plan(bad, [])
        self.assertEqual(plan["focal_point"]["x"], 1.0)
        self.assertEqual(plan["headline_placement"], "bottom")
        self.assertIsNone(pg.validate_plan({"subject": ""}, []))

    def test_skeletons_validate(self):
        self.assertIsNotNone(pg.validate_plan(json.loads(pg.PLAN_SKELETON), []))
        self.assertIsNotNone(pg.validate_critique(json.loads(pg.CRITIQUE_SKELETON)))

    def test_validate_critique_clamps(self):
        c = pg.validate_critique({"overall": "12", "thumbnail_holds": "true", "fails": "x"})
        self.assertEqual(c["overall"], 10.0)
        self.assertTrue(c["thumbnail_holds"])
        self.assertEqual(c["fails"], [])
        self.assertIsNone(pg.validate_critique({"works": "x"}))

    def test_schema_files_match_the_engine(self):
        for name, schema in (("plan", pg.PLAN_SCHEMA), ("critique", pg.CRITIQUE_SCHEMA)):
            path = REPO_ROOT / "lib" / "zer0_image_generator" / "svg" / f"{name}.schema.json"
            doc = json.loads(path.read_text())
            for key in ("$schema", "$id", "title", "$comment"):
                doc.pop(key)
            self.assertEqual(doc, json.loads(json.dumps(schema)), name)

    def test_forge_workflow_critique_shape_matches(self):
        js = (REPO_ROOT / ".claude" / "workflows" / "svg-forge.js").read_text()
        block = re.search(r"const CRITIQUE_SCHEMA = \{(.*?)\n\}", js, re.S).group(1)
        required = re.search(r"required: \[([^\]]*)\]", block).group(1)
        self.assertEqual(sorted(re.findall(r"'(\w+)'", required)),
                         sorted(pg.CRITIQUE_SCHEMA["required"]))


class TestStyleCards(unittest.TestCase):
    def test_bundled_card_sections(self):
        card = pg.load_style_card("retro-pixel")
        self.assertEqual(card.font_family, "press-start-2p")
        author = card.text_for(pg.STYLE_CARD_AUTHOR_SECTIONS)
        self.assertIn("## Signature", author)
        self.assertNotIn("Seed recipe", author)
        self.assertIn("## Critique add-ons", card.text_for(pg.STYLE_CARD_CRITIC_SECTIONS))
        self.assertEqual(pg.load_style_card("flat-geometric").font_family, "inter")

    def test_unknown_card_is_none(self):
        self.assertIsNone(pg.load_style_card("no-such-card"))
        self.assertIsNone(pg.load_style_card(""))


class TestSettings(unittest.TestCase):
    def resolve(self, argv=(), config=None, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            return pg.resolve_settings(pg.parse_args(list(argv)),
                                       {"preview_images": config or {}})

    def test_defaults(self):
        s = self.resolve()
        self.assertTrue(s.claude_plan)
        self.assertEqual(s.claude_rounds, 1)
        self.assertEqual(s.claude_min_score, 7.0)
        self.assertEqual(s.svg_text, "paths")
        self.assertEqual(s.palette, [])

    def test_config_env_cli_precedence(self):
        config = {"claude_rounds": 2, "palette": "dusk", "claude_plan": False,
                  "style_card": "retro-pixel"}
        s = self.resolve(config=config)
        self.assertEqual(s.claude_rounds, 2)
        self.assertEqual(s.palette, pg.BANNER_PALETTES["dusk"])
        self.assertFalse(s.claude_plan)
        s = self.resolve(config=config, env={"CLAUDE_ROUNDS": "3"})
        self.assertEqual(s.claude_rounds, 3)
        s = self.resolve(["--rounds", "0", "--claude-plan", "--palette", "#000,#111"],
                         config=config, env={"CLAUDE_ROUNDS": "3"})
        self.assertEqual(s.claude_rounds, 0)
        self.assertTrue(s.claude_plan)
        self.assertEqual(s.palette, ["#000", "#111"])

    def test_palette_tokens(self):
        self.assertEqual(pg.palette_tokens(["#ABCDEF", "nope", "#123"]), ["#abcdef", "#123"])
        self.assertEqual(pg.palette_tokens(42), [])


class TestTelemetryAndChanged(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_record_shape(self):
        banner = self.tmp / "assets" / "b.svg"
        banner.parent.mkdir(parents=True)
        banner.write_text(GOOD_SVG)
        usage = [{"model": "claude-sonnet-5-5", "input_tokens": 100, "output_tokens": 50,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                  "cost_usd": 0.0007}]
        result = pg.ImageResult(True, "svg", banner, meta={
            "provider": "claude", "model": "claude-sonnet-5-5", "plan": True, "calls": 3,
            "rounds_used": 1, "critic": {"overall": 8, "thumbnail_holds": True, "fails": [],
                                         "next_change": "", "works": ""},
            "lint": {"clean": True, "errors": [], "warnings": []}, "usage": usage})
        record = pg.banner_telemetry_record(self.tmp, self.tmp / "a.md", "b", result,
                                            pg.Settings())
        self.assertEqual(record["schema"], "banner/v1")
        self.assertEqual(record["banner"], "assets/b.svg")
        self.assertEqual(record["tokens"], {"input": 100, "output": 50})
        self.assertEqual(record["critic"]["overall"], 8)
        for key in ("slug", "model", "rounds_used", "lint", "kb", "cost_usd", "fallback"):
            self.assertIn(key, record)
        json.dumps(record)

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self.tmp, check=True, capture_output=True)

    def test_changed_mode_replaces_placeholder_on_new_articles(self):
        if not shutil.which("git"):
            self.skipTest("git not available")
        self._git("init", "-q")
        (self.tmp / "_posts").mkdir()
        old = self.tmp / "_posts" / "old.md"
        old.write_text("---\ntitle: Old\npreview: /images/previews/old.svg\n---\nx\n")
        self._git("add", ".")
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        new = self.tmp / "_posts" / "new" / "fresh.md"
        new.parent.mkdir()
        new.write_text("---\ntitle: Fresh Post\npreview: /images/previews/section.svg\n"
                       "---\nbody\n")
        skipped = self.tmp / "_posts" / "new" / "skip.md"
        skipped.write_text("---\ntitle: Skip\n---\n")
        placeholder = self.tmp / "assets" / "images" / "previews" / "section.svg"
        placeholder.parent.mkdir(parents=True)
        placeholder.write_text(GOOD_SVG)
        found = dict(pg.git_changed_markdown(self.tmp, r"skip\.md"))
        self.assertEqual(list(found), [new])
        self.assertTrue(found[new])

        settings = pg.Settings(provider="local", rasterizer="none", changed=True,
                               parallel=1, telemetry=str(self.tmp / "t.jsonl"))
        runner = pg.Runner(settings, self.tmp, ctx=pg.RunContext(project_root=self.tmp, env={}))
        with mock.patch("builtins.print"):
            runner.run()
        self.assertIn("fresh-post.svg", new.read_text())
        line = json.loads((self.tmp / "t.jsonl").read_text().splitlines()[0])
        self.assertEqual(line["slug"], "fresh-post")
        self.assertEqual(line["provider"], "local")

    def test_inspect_lints_without_a_credential(self):
        banner = self.tmp / "b.svg"
        banner.write_text(GOOD_SVG)
        report = pg.inspect_banner(banner, pg.Settings(), pg.RunContext(self.tmp, {}))
        self.assertEqual(report["schema"], "banner-inspect/v1")
        self.assertFalse(report["lint"]["clean"])            # strict: <text> present
        self.assertEqual(report["features"]["text"], 1)
        self.assertIsNone(report["critic"])


class TestClientWire(unittest.TestCase):
    def client(self):
        with mock.patch.object(pg.shutil, "which", return_value=None):
            return pg.AnthropicClient({"ANTHROPIC_API_KEY": "k"})

    def test_schema_and_usage(self):
        client = self.client()
        captured = {}

        def fake_http(url, body, headers, timeout=0):
            captured.update(body)
            return {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 5}}

        usage = []
        with mock.patch.object(pg, "http_json", side_effect=fake_http):
            client.complete("s", "u", model="claude-sonnet-5-5", effort="low",
                            json_schema=pg.PLAN_SCHEMA, usage=usage)
        self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(captured["output_config"]["effort"], "low")
        self.assertEqual(usage[0]["input_tokens"], 10)
        self.assertAlmostEqual(usage[0]["cost_usd"], (10 * 2 + 5 * 10) / 1e6)

    def test_vision_sends_every_image_in_order(self):
        client = self.client()
        captured = {}
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.png", Path(tmp) / "b.png"
            a.write_bytes(PNG_1PX)
            b.write_bytes(PNG_1PX)

            def fake_http(url, body, headers, timeout=0):
                captured.update(body)
                return {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn"}

            with mock.patch.object(pg, "http_json", side_effect=fake_http):
                client.complete_vision("s", "u", [a, b])
        content = captured["messages"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["image", "image", "text"])


class TestRasterizerWidth(unittest.TestCase):
    def test_thumbnail_width_reaches_the_tool(self):
        calls = []
        with mock.patch.object(pg, "_which", side_effect=lambda t: t == "rsvg-convert"), \
                mock.patch.object(pg, "_run_quiet", side_effect=lambda cmd, **k: calls.append(cmd)):
            pg.rasterize_svg(Path("a.svg"), Path("a.png"), Path("."), "auto", 120)
        self.assertEqual(calls[0][:5], ["rsvg-convert", "-w", "120", "-h", "80"])

    def test_auto_never_reaches_for_npx(self):
        with mock.patch.object(pg, "_which", side_effect=lambda t: t == "npx"), \
                mock.patch.object(pg, "_run_quiet") as run:
            self.assertFalse(pg._resvg_attempt(Path("a"), Path("b"), 10, explicit=False))
            run.assert_not_called()


@unittest.skipUnless(shutil.which("resvg") or shutil.which("resvg-js")
                     or shutil.which("rsvg-convert"), "no local SVG rasterizer")
class TestRealRender(unittest.TestCase):
    def test_look_renders_full_and_thumbnail(self):
        shaped = pg.shape_svg(GOOD_SVG, "t", pg.Settings(), "inter")
        with tempfile.TemporaryDirectory() as tmp:
            look = pg.look_svg(shaped.svg, Path(tmp), "x", pg.Settings(), Path(tmp))
            self.assertIsNotNone(look)
            self.assertEqual(look[0].read_bytes()[:8], pg.PNG_SIGNATURE)
            self.assertEqual(look[1].read_bytes()[:8], pg.PNG_SIGNATURE)


if __name__ == "__main__":
    unittest.main(verbosity=1)
