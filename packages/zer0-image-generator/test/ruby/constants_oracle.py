#!/usr/bin/env python3
"""Dump the ported constants from preview_generator.py as JSON so the Ruby
constants test can diff its own copies byte-for-byte against the oracle."""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ORACLE = os.path.join(HERE, "..", "..", "lib", "zer0_image_generator",
                      "preview_generator.py")
spec = importlib.util.spec_from_file_location("pg", ORACLE)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)

print(json.dumps({
    "DEFAULTS": pg.DEFAULTS,
    "ENHANCE_DEFAULTS": pg.ENHANCE_DEFAULTS,
    "DEFAULT_ENHANCE_PROMPT": pg.DEFAULT_ENHANCE_PROMPT,
    "ANTHROPIC_API_URL": pg.ANTHROPIC_API_URL,
    "ANTHROPIC_VERSION": pg.ANTHROPIC_VERSION,
    "OAUTH_BETA": pg.OAUTH_BETA,
    "CLAUDE_CODE_SYSTEM_PROMPT": pg.CLAUDE_CODE_SYSTEM_PROMPT,
    "DEFAULT_CLAUDE_MODEL": pg.DEFAULT_CLAUDE_MODEL,
    "CLAUDE_MAX_TOKENS": pg.CLAUDE_MAX_TOKENS,
    "MODEL_FAMILIES": pg.MODEL_FAMILIES,
    "SVG_WIDTH": pg.SVG_WIDTH,
    "SVG_HEIGHT": pg.SVG_HEIGHT,
    "RETRO_PALETTES": pg.RETRO_PALETTES,
    "COMPOSITION_VARIANTS": pg.COMPOSITION_VARIANTS,
    "ART_DIRECTOR_SYSTEM": pg.ART_DIRECTOR_SYSTEM,
    "REVIEWER_SYSTEM": pg.REVIEWER_SYSTEM,
    "PNG_SIGNATURE": list(pg.PNG_SIGNATURE),
    "POST_GENERATION_SLEEP": pg.POST_GENERATION_SLEEP,
    "OVERRIDE_KEYS": list(pg.OVERRIDE_KEYS),
}, sort_keys=True, ensure_ascii=False))
