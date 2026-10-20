#!/usr/bin/env python3
"""zer0-image-generator — AI preview/social-image engine for any Jekyll site.

This single file IS the engine. It ships two ways and behaves identically in
both: vendored inside the `zer0-image-generator` Ruby gem (invoked as
`jekyll preview-images` from any Jekyll site) and standalone (curl this one
file anywhere and run it with python3). Lineage: extracted from the
zer0-mistakes theme's consolidated engine (`scripts/lib/preview_generator.py`,
PR bamr87/zer0-mistakes#296) and generalized — every zer0-ism is now a config
knob with zer0-compatible defaults:

    knob                _config.yml `preview_images:` key    default
    -----------------   ----------------------------------   -----------------
    collections dir     collections_dir (or Jekyll's own     "" (site root,
                        top-level collections_dir)           Jekyll default)
    front-matter key    front_matter_key                     preview
    author overrides    authors_file ("" disables)           _data/authors.yml
    collections         collections (list, or "auto" to      [posts]
                        discover from Jekyll's collections:)
    collection styles   collection_styles (map of            {} (global style)
                        collection → style/style_modifiers/
                        size/quality/model overrides)

Architecture — Claude ORCHESTRATES, an image model RENDERS:

    stage      role                                     engine / credential
    --------   --------------------------------------   ----------------------------------
    analyze    Claude reads the article and writes a    CLAUDE_CODE_OAUTH_TOKEN →
               vivid art-direction brief for the        ANTHROPIC_AUTH_TOKEN →
               renderer (prompt_engine: claude)         ANTHROPIC_API_KEY → `claude` CLI
    produce    a raster image model renders the brief   the selected provider (below)
    review     Claude looks at the produced image       same Claude credential chain
               (vision) and, if it misrepresents the
               article, requests ONE refined
               regeneration (review_engine: claude)

    provider   renderer                                 credential
    --------   --------------------------------------   ----------------------------------
    openai     gpt-image-2 / dall-e-3 (+ --enhance      OPENAI_API_KEY
    (default)  via /v1/images/edits)
    xai        grok-2-image                             XAI_API_KEY
    stability  Stable Diffusion XL (v1 API)             STABILITY_API_KEY
    gemini     gemini-2.5-flash-image                   GEMINI_API_KEY
    local      deterministic template SVG → PNG         none (CI-safe; skips
                                                        analyze/review)

Claude never renders pixels itself (the Anthropic API has no image-generation
endpoint); with no Claude credential the analyze/review stages degrade
gracefully to the built-in template prompt with a warning — the renderer still
runs. The SVG toolkit (sanitizer + rsvg/inkscape/magick/Playwright rasterizer
chain) serves the zero-credential `local` provider.

Configuration priority (per file):
    author preview overrides (authors_file) > CLI args > environment
    variables > _config.yml `preview_images:` > built-in defaults

Usage (from a Jekyll site root — via the gem or the bare file):
    jekyll preview-images --list-missing
    python3 preview_generator.py --dry-run --verbose
    python3 preview_generator.py --collection posts
    python3 preview_generator.py -f _posts/my-post.md --force
    python3 preview_generator.py --provider local -f <file>
    python3 preview_generator.py --front-matter-key image --review none ...

Dependencies: Python 3.9+ stdlib + PyYAML (`pip3 install pyyaml`). No other
packages — HTTP goes through urllib, multipart bodies are hand-rolled.

Exit codes: 0 = success; 1 = validation failure or any per-file errors.
"""

import argparse
import base64
import functools
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import zlib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # checked in ensure_yaml() after --help handling
    yaml = None


# =============================================================================
# Constants
# =============================================================================

# Built-in fallbacks — used only when a key is absent from _config.yml, env,
# and CLI. Claude orchestration (analysis + review) is on by default and
# degrades gracefully without a Claude credential.
DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "provider": "openai",
    "model": "",  # empty → the active provider's default_model()
    "size": "1536x1024",
    "quality": "auto",
    "style": (
        "retro pixel art, 8-bit video game aesthetic, vibrant colors, "
        "nostalgic, clean pixel graphics"
    ),
    "style_modifiers": (
        "pixelated, retro gaming style, CRT screen glow effect, "
        "limited color palette"
    ),
    "output_dir": "assets/images/previews",
    "assets_prefix": "/assets",
    "auto_prefix": True,
    "collections": ["posts"],    # or "auto": discover from Jekyll `collections:`
    "collections_dir": "",       # Jekyll's collections_dir (zer0-mistakes: "pages")
    "front_matter_key": "preview",  # jekyll-seo-tag users typically want "image"
    "authors_file": "_data/authors.yml",  # "" disables author overrides
    "prompt_engine": "claude",   # claude analyzes the article; falls back to template
    "review_engine": "claude",   # claude vision-reviews the render; `none` disables
    "claude_model": "",          # empty → DEFAULT_CLAUDE_MODEL
    "claude_effort": "low",      # output_config.effort for brief/review calls
                                 # (short creative tasks; "" sends no effort)
    "rasterizer": "auto",        # SVG→PNG tool for the SVG providers (local,
                                 # claude): auto|rsvg|resvg|inkscape|magick
                                 # |playwright|none. "none" is SVG-only mode —
                                 # the vector banner IS the deliverable and no
                                 # PNG is made.
    # ---- the `claude` provider's illustration loop -------------------------
    # plan → author → shape → look → critique → (edit → look → critique)* →
    # commit best. See ClaudeSvgProvider and docs/ILLUSTRATION-LOOP.md.
    "style_card": "",            # tools/svg/library/styles/<name>.md (or a
                                 # path); "" = the prose style string only
    "palette": [],               # 6 tokens [bg, shadow, low-mid, mid, accent,
                                 # highlight], or a BANNER_PALETTES name; [] =
                                 # let the plan/card choose
    "claude_plan": True,         # JSON scene-graph plan before authoring
    "claude_rounds": 1,          # critique-driven edit rounds; 0 = one-shot
                                 # (no render, no vision call)
    "claude_min_score": 7,       # critic `overall` (0-10) that ends the loop
    "claude_require_thumbnail": True,  # ...and only if it reads at 120px
    "svg_text": "paths",         # paths: <text> → <path> with a bundled font;
                                 # keep: leave <text>; forbid: strip it
    "svg_max_kb": 300,           # strict-lint size budget for a committed banner
    "look_rasterizer": "auto",   # the tool the loop LOOKS through (independent
                                 # of `rasterizer`, which decides the OUTPUT)
    "claude_budget_usd": 0,      # per-run spend cap for the loop; 0 = uncapped
}

# Enhance mode (OpenAI /v1/images/edits — see OpenAIProvider.edit)
ENHANCE_DEFAULTS: Dict[str, str] = {
    "model": "gpt-image-2",
    "quality": "auto",
    "fidelity": "high",
    "format": "png",
}
DEFAULT_ENHANCE_PROMPT = (
    "Improve this preview banner image: fix any misspelled, garbled, or "
    "incorrect text so it reads clearly and accurately. Sharpen visual details "
    "and improve composition while preserving the original art style, color "
    "palette, and theme. Ensure the image is clean and professional."
)

# Anthropic wire constants — keep in sync with templates/deploy/chat-proxy/worker.js.
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OAUTH_BETA = "oauth-2025-04-20"
# Claude Code OAuth tokens require the FIRST system block to identify as Claude
# Code, otherwise the API rejects the call with a misleading `rate_limit_error`.
CLAUDE_CODE_SYSTEM_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_MAX_TOKENS = 16000  # non-streaming ceiling; SVG banners fit comfortably

# Model-name prefix → provider family. Used to ignore a configured/author model
# that belongs to a different vendor than the active provider (never send a
# request that is guaranteed to 400).
MODEL_FAMILIES: Dict[str, str] = {
    "claude-": "claude",
    "gpt-image-": "openai",
    "dall-e-": "openai",
    "grok-": "xai",
    "stable-": "stability",
    "sd3": "stability",
    "gemini-": "gemini",
    "imagen-": "gemini",
}

# Banner geometry for SVG-producing providers (claude, local).
SVG_WIDTH, SVG_HEIGHT = 1536, 1024

# Curated retro palettes: (sky/background, far, mid, near, accent, glow).
# Selected deterministically per slug so re-runs stay visually stable.
RETRO_PALETTES: List[List[str]] = [
    ["#1a1a2e", "#16213e", "#0f3460", "#533483", "#e94560", "#f9ed69"],
    ["#0d1b2a", "#1b263b", "#415a77", "#778da9", "#e0e1dd", "#ffb703"],
    ["#2d132c", "#801336", "#c72c41", "#ee4540", "#f9d276", "#f4f4f4"],
    ["#10002b", "#3c096c", "#7b2cbf", "#c77dff", "#e0aaff", "#72efdd"],
    ["#001219", "#005f73", "#0a9396", "#94d2bd", "#e9d8a6", "#ee9b00"],
    ["#03071e", "#370617", "#9d0208", "#dc2f02", "#f48c06", "#ffba08"],
    ["#0b132b", "#1c2541", "#3a506b", "#5bc0be", "#6fffe9", "#ff6b6b"],
    ["#232931", "#393e46", "#4ecca3", "#a5ecd7", "#eeeeee", "#f95959"],
    ["#1f0a24", "#571089", "#ab51e3", "#f7aef8", "#b388eb", "#8093f1"],
    ["#141e30", "#243b55", "#3c6382", "#82ccdd", "#f8c291", "#e55039"],
]

COMPOSITION_VARIANTS: List[str] = [
    "a low horizon with a huge rising sun disk banded by scanlines",
    "layered diagonal mountain silhouettes receding into haze",
    "a vaporwave perspective grid floor vanishing toward the horizon",
    "floating terraced islands with cascading pixel waterfalls",
    "a night starfield with a large ringed planet arcing across the frame",
    "a stepped city skyline of blocky towers with lit windows",
    "rolling desert dunes with a lone monolith and long shadows",
    "an ocean of chunky pixel waves under drifting square clouds",
]

# System prompt for Claude's ART-DIRECTOR role (prompt_engine: claude): read
# the article, then write the brief a raster image model will render. NOTE:
# "no text" matches the long-standing prompt rule of this feature — image
# models garble lettering.
ART_DIRECTOR_SYSTEM = """You are an art director for a technical blog. You will be given an article
(title, description, tags, an excerpt) plus mandatory style directions. Your
job is to design ONE preview banner image and describe it to an AI image
model.

Respond with ONLY the image-generation prompt — no preamble, no quotes, no
markdown. One vivid paragraph of at most 130 words that:
- captures the article's actual SUBJECT as a concrete visual metaphor or
  scene (specific objects, actions and spatial arrangement — never a generic
  'technology background');
- specifies composition for a wide banner (what sits left/center/right,
  foreground/background, focal point);
- weaves in the given art style and palette directions verbatim in spirit;
- states that the image must contain NO text, letters, words, numbers, logos
  or UI copy of any kind."""

# System prompt for Claude's REVIEWER role (review_engine: claude): look at
# the rendered image and decide whether it represents the article.
REVIEWER_SYSTEM = """You are reviewing an AI-generated blog preview banner against the article it
illustrates. Judge three things: (1) does the image clearly evoke the
article's actual subject, (2) does it follow the requested art style, and
(3) is it free of text/lettering artifacts and visual glitches.

Respond with ONLY a JSON object, no markdown fences:
{"verdict": "approve" | "revise",
 "critique": "<one or two sentences on what is wrong or right>",
 "revised_prompt": "<empty when approving; otherwise a complete replacement
image-generation prompt (max 130 words) that fixes the problems while keeping
the required style and the no-text rule>"}

Approve unless the image genuinely misrepresents the subject, breaks the
style, or contains text/glitches — minor taste differences are not grounds
for revision."""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def image_media_type(data: bytes) -> str:
    """The MIME type a raster's own bytes declare. Providers do not all answer
    PNG (xAI Imagine answers JPEG), and vision APIs check the label."""
    if data[:3] == JPEG_SIGNATURE:
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"

# Pause after each successful non-dry generation (Bash parity: polite pacing
# between paid API calls). Tests set this to 0.
POST_GENERATION_SLEEP = 2.0


# =============================================================================
# Terminal output
# =============================================================================

class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    PURPLE = "\033[0;35m"
    BOLD = "\033[1m"
    NC = "\033[0m"


VERBOSE = False
_log_file = None  # type: Optional[Any]

_LEVEL_COLORS = {
    "info": Colors.BLUE,
    "step": Colors.CYAN,
    "success": Colors.GREEN,
    "warning": Colors.YELLOW,
    "error": Colors.RED,
    "debug": Colors.PURPLE,
}


def log(msg: str, level: str = "info") -> None:
    color = _LEVEL_COLORS.get(level, Colors.NC)
    stream = sys.stderr if level in ("warning", "error", "debug") else sys.stdout
    print(f"{color}[{level.upper()}]{Colors.NC} {msg}", file=stream)
    if _log_file:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        _log_file.write(f"{stamp} [{level.upper()}] {msg}\n")
        _log_file.flush()


def info(msg: str) -> None:
    log(msg, "info")


def step(msg: str) -> None:
    log(msg, "step")


def success(msg: str) -> None:
    log(msg, "success")


def warn(msg: str) -> None:
    log(msg, "warning")


def debug(msg: str) -> None:
    if VERBOSE:
        log(msg, "debug")


def error_exit(msg: str) -> "NoReturn":  # noqa: F821 - typing.NoReturn (3.9 compat)
    log(msg, "error")
    sys.exit(1)


def print_header(title: str) -> None:
    line = "=" * 64
    print(f"\n{Colors.CYAN}{line}{Colors.NC}")
    print(f"  {Colors.GREEN}{title}{Colors.NC}")
    print(f"{Colors.CYAN}{line}{Colors.NC}\n")


# =============================================================================
# Environment / interrupts
# =============================================================================

_interrupted = False


def _signal_handler(signum, frame):  # noqa: ARG001
    global _interrupted
    _interrupted = True
    print(f"\n{Colors.YELLOW}⚠️  Interrupt received. Finishing current tasks...{Colors.NC}")


def _load_dotenv(start: Optional[Path] = None) -> None:
    """Load .env from cwd (or `start`) up to 4 parents.

    Non-empty exported env vars win over .env; an EMPTY env var is treated as
    unset (docker/VS Code tasks forward `-e KEY=${env:KEY}` which materializes
    empty strings that must not shadow a real value in .env).
    """
    search_dir = start or Path.cwd()
    for _ in range(5):
        env_file = search_dir / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if value[:1] in ("'", '"') and value[-1:] == value[:1]:
                        value = value[1:-1]  # matched surrounding quotes
                    else:
                        value = value.split(" #", 1)[0].rstrip()  # inline comment
                    if key and not os.environ.get(key):
                        os.environ[key] = value
            except OSError:
                pass
            return
        if search_dir.parent == search_dir:
            break
        search_dir = search_dir.parent


def ensure_yaml() -> None:
    if yaml is None:
        error_exit(
            "PyYAML is required (front matter, _config.yml and _data/authors.yml "
            "parsing). Install it with ONE of:\n"
            "    pip3 install pyyaml\n"
            "    python3 -m pip install --user pyyaml\n"
            "    docker-compose exec jekyll pip3 install --break-system-packages pyyaml"
        )


# =============================================================================
# HTTP layer (urllib only — no third-party HTTP deps)
# =============================================================================

class HttpStatusError(Exception):
    """Non-2xx HTTP response, with parsed body + headers when possible."""

    def __init__(self, status: int, body: bytes, url: str,
                 headers: Optional[Dict[str, str]] = None):
        self.status = status
        self.body = body
        self.url = url
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        super().__init__(f"HTTP {status} from {url}: {self.message()[:300]}")

    def retry_after(self) -> float:
        """Server-requested backoff: the Retry-After header (what Anthropic/
        OpenAI/xAI actually send on 429), falling back to a JSON body field."""
        try:
            header = self.headers.get("retry-after")
            if header:
                return float(header)
        except (TypeError, ValueError):
            pass
        data = self.json()
        if isinstance(data, dict):
            try:
                return float(data.get("retry_after", 0) or 0)
            except (TypeError, ValueError):
                pass
        return 0.0

    def json(self) -> Optional[dict]:
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    def message(self) -> str:
        data = self.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
            if data.get("detail"):
                return str(data["detail"])
        return self.body.decode("utf-8", "replace")[:500]


# Sent on every request that does not name its own client. api.x.ai and
# auth.x.ai sit behind Cloudflare, whose bot rules answer urllib's stock
# `Python-urllib/3.x` with a 403 page or `error code: 1010`.
HTTP_USER_AGENT = "zer0-image-generator"


def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: int = 120,
) -> Tuple[int, Dict[str, str], bytes]:
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if not req.has_header("User-agent"):  # urllib stores names capitalize()d
        req.add_header("User-Agent", HTTP_USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        raise HttpStatusError(exc.code, body, url,
                              dict(exc.headers.items()) if exc.headers else None) from None


def http_json(
    url: str, payload: dict, headers: Dict[str, str], timeout: int = 900
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **headers}
    _, _, raw = http_request(url, "POST", hdrs, body, timeout)
    return json.loads(raw.decode("utf-8"))


def build_multipart(
    fields: Dict[str, str], files: List[Tuple[str, str, bytes, str]]
) -> Tuple[bytes, str]:
    """Encode multipart/form-data. files: (field, filename, content, mime)."""
    boundary = f"----zer0-{uuid.uuid4().hex}"
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(str(value).encode("utf-8"))
        buf.write(b"\r\n")
    for name, filename, content, mime in files:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
        buf.write(content)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def http_multipart(
    url: str,
    fields: Dict[str, str],
    files: List[Tuple[str, str, bytes, str]],
    headers: Dict[str, str],
    timeout: int = 900,
) -> dict:
    body, content_type = build_multipart(fields, files)
    hdrs = {"Content-Type": content_type, **headers}
    _, _, raw = http_request(url, "POST", hdrs, body, timeout)
    return json.loads(raw.decode("utf-8"))


def download_to(url: str, dest: Path, timeout: int = 120) -> None:
    _, _, raw = http_request(url, "GET", {}, None, timeout)
    dest.write_bytes(raw)


RETRYABLE_STATUSES = {429, 500, 502, 503, 529}


def with_retries(fn, what: str, attempts: int = 4):
    """Run fn(); retry transport errors and retryable HTTP statuses.

    Backoff 2s/4s/8s (or the server's Retry-After when larger, capped 60s).
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except HttpStatusError as exc:
            if exc.status not in RETRYABLE_STATUSES or attempt == attempts:
                raise
            wait = min(max(delay, exc.retry_after()), 60.0)
            warn(f"{what}: HTTP {exc.status}, retrying in {wait:.0f}s "
                 f"(attempt {attempt}/{attempts})")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt == attempts:
                raise
            wait = delay
            warn(f"{what}: {exc.__class__.__name__}: {exc}; retrying in {wait:.0f}s "
                 f"(attempt {attempt}/{attempts})")
        time.sleep(wait)
        delay *= 2


# =============================================================================
# Config layer
# =============================================================================

def find_project_root() -> Path:
    """Site root: two parents above this file when vendored at
    <site>/scripts/lib/ (curl layout); else walk up from cwd — the gem layout,
    where the engine lives far from the site and `jekyll` runs at the root."""
    script_root = Path(__file__).resolve().parent.parent.parent
    if (script_root / "_config.yml").is_file():
        return script_root
    probe = Path.cwd()
    for _ in range(6):
        if (probe / "_config.yml").is_file():
            return probe
        if probe.parent == probe:
            break
        probe = probe.parent
    return script_root


def load_yaml_file(path: Path) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # malformed YAML must not kill the whole run
        warn(f"Could not parse {path.name}: {exc}")
        return {}


def apply_source_root(project_root: Path, config: Dict[str, Any]) -> Path:
    """Honor Jekyll's top-level `source:` key: content (collections, assets,
    _data) lives under <root>/<source> while _config.yml stays at the root —
    e.g. zer0-pages sets `source: pages`. Disk-side only: URL-space values
    (front-matter paths, assets_prefix) are unaffected."""
    source = str(config.get("source") or "").strip().strip("/")
    if source and source != ".":
        return project_root / source
    return project_root


def read_config(project_root: Path) -> Dict[str, Any]:
    """The site's full _config.yml — resolve_settings extracts the
    `preview_images:` block plus the top-level Jekyll keys it honors
    (`collections_dir`, `collections`)."""
    return load_yaml_file(project_root / "_config.yml")


def read_authors(project_root: Path, authors_file: str) -> Dict[str, Any]:
    """Author-override map. `authors_file` is project-root-relative; an empty
    value disables the feature (universal sites rarely have authors.yml)."""
    if not (authors_file or "").strip():
        return {}
    return load_yaml_file(project_root / authors_file.strip().lstrip("/"))


# Settings fields an override block (author preview: / collection_styles:)
# may replace per file.
OVERRIDE_KEYS = ("style", "style_modifiers", "size", "quality", "model")


def _filter_override_block(block: Any) -> Dict[str, str]:
    """Keep only the recognized override keys with non-empty values."""
    if not isinstance(block, dict):
        return {}
    return {
        key: str(value).strip()
        for key, value in block.items()
        if key in OVERRIDE_KEYS and value is not None and str(value).strip()
    }


def author_preview_overrides(authors: Dict[str, Any], author_key: Any) -> Dict[str, str]:
    """`preview:` override block for an author key (style/style_modifiers/size/
    quality/model). `author:` may be a list or mapping in some posts — only a
    plain string key can index authors.yml; anything else has no override."""
    if not isinstance(author_key, str) or not author_key:
        return {}
    author = authors.get(author_key)
    if not isinstance(author, dict):
        return {}
    return _filter_override_block(author.get("preview"))


def collection_of(path: Path) -> str:
    """The file's collection, from the nearest `_<name>` ancestor directory
    (Jekyll's collection layout) — '' for files outside any collection."""
    for parent in Path(path).resolve().parents:
        name = parent.name
        if name.startswith("_") and len(name) > 1:
            return name[1:]
    return ""


def section_of(path: Path) -> str:
    """The file's section — the directory immediately INSIDE its collection
    (`pages/_posts/hacks/x.md` -> 'hacks') — or '' when the collection holds
    its files flat. Sites that fold several kinds of writing into one
    collection carry the editorial distinction here, and it is the strongest
    single signal for what a banner should look like."""
    resolved = Path(path).resolve()
    parts = resolved.parts
    for i, name in enumerate(parts):
        if name.startswith("_") and len(name) > 1:
            # parts[i+1] is a directory only when something follows it.
            return parts[i + 1] if i + 2 < len(parts) else ""
    return ""


def article_art_context(cf: "ContentFile", slug: str) -> Dict[str, str]:
    """The page context the local renderer derives its art from."""
    return {
        "slug": slug,
        "section": section_of(cf.path) or collection_of(cf.path),
        "title": cf.title or "",
        "description": cf.description or "",
        "categories": cf.categories or "",
        "body": cf.content or "",
    }


def collection_preview_overrides(
    collection_styles: Dict[str, Any], collection: str
) -> Dict[str, str]:
    """`collection_styles:` override block for a collection — same keys as
    author overrides, so each collection can carry its own visual theme."""
    if not collection or not isinstance(collection_styles, dict):
        return {}
    return _filter_override_block(collection_styles.get(collection))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


@dataclass
class Settings:
    """Fully-resolved run settings (before per-file author overrides)."""

    provider: str = DEFAULTS["provider"]
    model: str = DEFAULTS["model"]
    size: str = DEFAULTS["size"]
    quality: str = DEFAULTS["quality"]
    style: str = DEFAULTS["style"]
    style_modifiers: str = DEFAULTS["style_modifiers"]
    output_dir: str = DEFAULTS["output_dir"]
    assets_prefix: str = DEFAULTS["assets_prefix"]
    auto_prefix: bool = DEFAULTS["auto_prefix"]
    enabled: bool = True
    collections: List[str] = field(default_factory=lambda: list(DEFAULTS["collections"]))
    collections_dir: str = DEFAULTS["collections_dir"]
    collection_styles: Dict[str, Any] = field(default_factory=dict)
    front_matter_key: str = DEFAULTS["front_matter_key"]
    authors_file: str = DEFAULTS["authors_file"]
    prompt_engine: str = DEFAULTS["prompt_engine"]
    review_engine: str = DEFAULTS["review_engine"]
    claude_model: str = DEFAULTS["claude_model"]
    claude_effort: str = DEFAULTS["claude_effort"]

    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    list_only: bool = False
    parallel: int = 4
    batch: int = 0

    file: str = ""
    collection: str = ""

    enhance: bool = False
    enhance_prompt: str = ""
    enhance_model: str = ENHANCE_DEFAULTS["model"]
    enhance_quality: str = ENHANCE_DEFAULTS["quality"]
    enhance_fidelity: str = ENHANCE_DEFAULTS["fidelity"]
    enhance_format: str = ENHANCE_DEFAULTS["format"]

    rasterizer: str = "auto"
    provider_explicit: bool = False

    # The `claude` provider's illustration loop (see DEFAULTS).
    style_card: str = DEFAULTS["style_card"]
    palette: List[str] = field(default_factory=list)
    claude_plan: bool = DEFAULTS["claude_plan"]
    claude_rounds: int = DEFAULTS["claude_rounds"]
    claude_min_score: float = float(DEFAULTS["claude_min_score"])
    claude_require_thumbnail: bool = DEFAULTS["claude_require_thumbnail"]
    svg_text: str = DEFAULTS["svg_text"]
    svg_max_kb: float = float(DEFAULTS["svg_max_kb"])
    look_rasterizer: str = DEFAULTS["look_rasterizer"]
    claude_budget_usd: float = float(DEFAULTS["claude_budget_usd"])
    telemetry: str = ""               # JSONL path ("-" = stdout); "" = off
    changed: bool = False             # illustrate git-new/modified markdown
    exclude_re: str = ""              # --changed: skip matching status lines


# Truthy spellings for booleans that arrive as strings (env vars, CLI values,
# quoted YAML). Anything else — including "" — is false.
_TRUE_WORDS = ("1", "true", "yes", "on")


def _setting_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in _TRUE_WORDS


def _setting_number(value: Any, default: float) -> float:
    """A float from config/env/CLI; unparseable values fall back to default
    rather than aborting the run (a typo in _config.yml must not cost the
    tick its banners)."""
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_HEX_TOKEN = re.compile(r"\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")


def palette_tokens(value: Any) -> List[str]:
    """Normalize a palette setting to a list of hex tokens.

    Accepts a YAML list of hex strings, a comma/space separated string of hex
    tokens, or the NAME of one of the engine's BANNER_PALETTES. Invalid
    entries are dropped; an unusable value yields [] (no palette constraint).
    """
    if isinstance(value, str):
        name = value.strip()
        if name in BANNER_PALETTES:
            return list(BANNER_PALETTES[name])
        value = [part for part in re.split(r"[\s,]+", name) if part]
    if not isinstance(value, list):
        return []
    tokens = [str(v).strip() for v in value]
    return [t.lower() for t in tokens if _HEX_TOKEN.match(t)]


def resolve_settings(args: argparse.Namespace, config: Dict[str, Any]) -> Settings:
    """Merge CLI > env > _config.yml `preview_images:` > DEFAULTS into a
    Settings object. `config` is the site's FULL _config.yml dict — the block
    is extracted here, and two top-level Jekyll keys are honored as fallbacks:
    `collections_dir` and (for `collections: auto`) the `collections:` map."""

    site = config.get("preview_images")
    if not isinstance(site, dict):
        site = {}

    def cfg(key: str, default: Any) -> Any:
        value = site.get(key)
        return default if value is None else value

    def pick(cli_value: Optional[str], env_name: str, cfg_key: str) -> str:
        if cli_value is not None:
            return cli_value
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
        return str(cfg(cfg_key, DEFAULTS[cfg_key]))

    def layered(cli_value: Any, env_name: str, cfg_key: str) -> Any:
        """pick() without the str(): CLI > non-empty env > config > default,
        returning the raw value so lists, numbers and booleans survive."""
        if cli_value is not None:
            return cli_value
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
        return cfg(cfg_key, DEFAULTS[cfg_key])

    # collections_dir: block override > Jekyll's own top-level key > default.
    collections_dir = cfg(
        "collections_dir", config.get("collections_dir") or DEFAULTS["collections_dir"]
    )
    if args.collections_dir is not None:
        collections_dir = args.collections_dir

    collections = cfg("collections", DEFAULTS["collections"])
    if collections == "auto" or (
        isinstance(collections, list) and "auto" in collections
    ):
        # Discover from Jekyll's own collections: map; posts always exists.
        declared = config.get("collections")
        names = list(declared.keys()) if isinstance(declared, dict) else []
        collections = ["posts"] + [n for n in names if n != "posts"]
    if not isinstance(collections, list) or not collections:
        collections = list(DEFAULTS["collections"])

    parallel_env = os.environ.get("MAX_PARALLEL", "")
    parallel = args.parallel if args.parallel is not None else (
        int(parallel_env) if parallel_env.isdigit() else 4
    )

    settings = Settings(
        provider=pick(args.provider, "AI_PROVIDER", "provider"),
        model=pick(args.model, "IMAGE_MODEL", "model"),
        size=pick(None, "IMAGE_SIZE", "size"),
        quality=pick(None, "IMAGE_QUALITY", "quality"),
        style=pick(args.style, "IMAGE_STYLE", "style"),
        style_modifiers=pick(None, "IMAGE_STYLE_MODIFIERS", "style_modifiers"),
        output_dir=pick(args.output_dir, "OUTPUT_DIR", "output_dir"),
        assets_prefix=(
            args.assets_prefix if args.assets_prefix is not None
            else str(cfg("assets_prefix", DEFAULTS["assets_prefix"]))
        ),
        auto_prefix=(
            False if args.no_auto_prefix
            else bool(cfg("auto_prefix", DEFAULTS["auto_prefix"]))
        ),
        enabled=bool(cfg("enabled", True)),
        collections=[str(c) for c in collections],
        collection_styles=(
            cfg("collection_styles", {})
            if isinstance(cfg("collection_styles", {}), dict) else {}
        ),
        collections_dir=str(collections_dir or "").strip().strip("/"),
        front_matter_key=(
            args.front_matter_key
            or str(cfg("front_matter_key", DEFAULTS["front_matter_key"])).strip()
            or DEFAULTS["front_matter_key"]
        ),
        authors_file=(
            args.authors_file if args.authors_file is not None
            else str(cfg("authors_file", DEFAULTS["authors_file"]) or "")
        ),
        prompt_engine=pick(args.prompt_engine, "PROMPT_ENGINE", "prompt_engine"),
        review_engine=pick(args.review, "REVIEW_ENGINE", "review_engine"),
        claude_model=str(cfg("claude_model", "") or ""),
        claude_effort=str(cfg("claude_effort", DEFAULTS["claude_effort"]) or ""),
        dry_run=args.dry_run or _env_flag("DRY_RUN"),
        verbose=args.verbose or _env_flag("VERBOSE"),
        force=args.force or _env_flag("FORCE"),
        list_only=args.list_missing or _env_flag("LIST_ONLY"),
        parallel=parallel,
        batch=args.batch or 0,
        file=args.file or "",
        collection=args.collection or "",
        enhance=args.enhance or _env_flag("ENHANCE"),
        enhance_prompt=args.enhance_prompt or "",
        enhance_model=(
            args.enhance_model or os.environ.get("ENHANCE_MODEL")
            or ENHANCE_DEFAULTS["model"]
        ),
        enhance_quality=(
            args.enhance_quality or os.environ.get("ENHANCE_QUALITY")
            or ENHANCE_DEFAULTS["quality"]
        ),
        enhance_fidelity=(
            args.enhance_fidelity or os.environ.get("ENHANCE_FIDELITY")
            or ENHANCE_DEFAULTS["fidelity"]
        ),
        enhance_format=(
            args.enhance_format or os.environ.get("ENHANCE_FORMAT")
            or ENHANCE_DEFAULTS["format"]
        ),
        rasterizer=pick(args.rasterizer, "IMAGE_RASTERIZER", "rasterizer"),
        provider_explicit=args.provider is not None or bool(os.environ.get("AI_PROVIDER")),
        style_card=pick(args.style_card, "IMAGE_STYLE_CARD", "style_card").strip(),
        palette=palette_tokens(layered(args.palette, "IMAGE_PALETTE", "palette")),
        claude_plan=_setting_bool(layered(args.claude_plan, "CLAUDE_PLAN", "claude_plan")),
        claude_rounds=max(0, int(_setting_number(
            layered(args.claude_rounds, "CLAUDE_ROUNDS", "claude_rounds"),
            float(DEFAULTS["claude_rounds"])))),
        claude_min_score=_setting_number(
            layered(args.claude_min_score, "CLAUDE_MIN_SCORE", "claude_min_score"),
            float(DEFAULTS["claude_min_score"])),
        claude_require_thumbnail=_setting_bool(layered(
            args.claude_require_thumbnail, "CLAUDE_REQUIRE_THUMBNAIL",
            "claude_require_thumbnail")),
        svg_text=pick(args.svg_text, "SVG_TEXT", "svg_text").strip().lower(),
        svg_max_kb=_setting_number(
            layered(args.svg_max_kb, "SVG_MAX_KB", "svg_max_kb"),
            float(DEFAULTS["svg_max_kb"])),
        look_rasterizer=pick(args.look_rasterizer, "LOOK_RASTERIZER", "look_rasterizer"),
        claude_budget_usd=_setting_number(
            layered(args.claude_budget_usd, "CLAUDE_BUDGET_USD", "claude_budget_usd"),
            float(DEFAULTS["claude_budget_usd"])),
        telemetry=(args.telemetry if args.telemetry is not None
                   else os.environ.get("PREVIEW_TELEMETRY", "")),
        changed=bool(args.changed),
        exclude_re=(args.exclude_re if args.exclude_re is not None
                    else os.environ.get("PREVIEW_EXCLUDE_RE", "")),
    )
    return settings


def apply_preview_overrides(
    settings: Settings, *override_blocks: Dict[str, str]
) -> Settings:
    """Per-file settings copy with override blocks applied in order — later
    blocks win (pass collection styles first, author overrides on top)."""
    merged: Dict[str, str] = {}
    for block in override_blocks:
        merged.update(block or {})
    if not merged:
        return settings
    return replace(
        settings,
        **{key: merged.get(key, getattr(settings, key)) for key in OVERRIDE_KEYS},
    )


def file_preview_settings(settings: Settings, cf: "ContentFile",
                          authors: Dict[str, Any]) -> Settings:
    """The per-file settings: global → collection_styles[collection] →
    author preview: block (most specific wins)."""
    coll_overrides = collection_preview_overrides(
        settings.collection_styles, collection_of(cf.path))
    author_overrides = author_preview_overrides(authors, cf.author)
    result = apply_preview_overrides(settings, coll_overrides, author_overrides)
    if coll_overrides:
        info(f"  ↳ Collection '{collection_of(cf.path)}' preview style applied")
    if author_overrides:
        info(f"  ↳ Author '{cf.author}' preview overrides applied "
             f"({settings.authors_file})")
    return result


def model_family(model: str) -> Optional[str]:
    m = (model or "").strip().lower()
    for prefix, family in MODEL_FAMILIES.items():
        if m.startswith(prefix):
            return family
    return None


def effective_model(settings: Settings, provider: "Provider") -> str:
    """Configured model when it belongs to the provider's family, else the
    provider default (with a warning) — never emit a guaranteed-400 request."""
    model = (settings.model or "").strip()
    if not model:
        return provider.default_model()
    family = model_family(model)
    if family is not None and family != provider.name:
        warn(
            f"Model '{model}' belongs to the '{family}' family; using "
            f"{provider.name} default '{provider.default_model()}' instead"
        )
        return provider.default_model()
    return model


# =============================================================================
# Front-matter layer
# =============================================================================

@dataclass
class ContentFile:
    path: Path
    title: str
    description: str
    categories: str
    preview: Optional[str]
    author: Any
    content: str
    front_matter: Dict[str, Any]


_FM_OPEN = re.compile(r"\A---[ \t]*\r?\n")


def split_front_matter(text: str) -> Optional[Tuple[int, int, str]]:
    """Return (fm_start, fm_end, fm_text) — offsets of the raw front-matter
    body between the opening and closing `---` fences — or None."""
    open_match = _FM_OPEN.match(text)
    if not open_match:
        return None
    fm_start = open_match.end()
    close = re.compile(r"^---[ \t]*\r?$", re.M).search(text, fm_start)
    if not close:
        return None
    return fm_start, close.start(), text[fm_start:close.start()]


def parse_front_matter(path: Path, fm_key: str = "preview") -> Optional[ContentFile]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        warn(f"Failed to read {path}: {exc}")
        return None

    parts = split_front_matter(text)
    if not parts:
        debug(f"No front matter found in: {path}")
        return None
    fm_start, fm_end = parts[0], parts[1]

    try:
        data = yaml.safe_load(parts[2])
    except yaml.YAMLError as exc:
        warn(f"Failed to parse YAML in {path}: {exc}")
        return None
    if not isinstance(data, dict):
        return None

    categories = data.get("categories", [])
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, list):
        categories = []

    body_start = text.find("\n", fm_end)
    body = text[body_start + 1:] if body_start != -1 else ""

    return ContentFile(
        path=path,
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
        categories=", ".join(str(c) for c in categories),
        preview=data.get(fm_key) if isinstance(data.get(fm_key), str) else None,
        author=data.get("author"),
        content=body,
        front_matter=data,
    )


def update_front_matter(path: Path, preview_path: str, dry_run: bool = False,
                        key: str = "preview") -> bool:
    """Set `<key>:` inside the front-matter block ONLY (first match).

    Replaces an existing `<key>:` line, else inserts after the first
    `description:` line, else after the first `title:` line. Everything outside
    the front-matter block is preserved byte-for-byte (the former sed/regex
    implementations operated file-wide and could corrupt body lines that start
    with the key). Writes a transient `.bak`, replaces atomically, removes
    the `.bak` on success.
    """
    if dry_run:
        info(f"[DRY RUN] Would update {key} in {path} to: {preview_path}")
        return True

    try:
        # Bytes round-trip: Path.read_text() would translate CRLF → LF.
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        warn(f"Failed to read {path}: {exc}")
        return False

    parts = split_front_matter(text)
    if not parts:
        warn(f"No front matter block in {path}; not updating")
        return False
    fm_start, fm_end, fm_text = parts

    eol = "\r\n" if "\r\n" in fm_text else "\n"
    lines = fm_text.splitlines(keepends=True)

    def find_key(prefix: str) -> int:
        for idx, line in enumerate(lines):
            if line.startswith(prefix):
                return idx
        return -1

    def end_of_block(idx: int) -> int:
        """Index just past a key line and any indented continuation lines
        (folded/literal scalars, nested maps)."""
        j = idx + 1
        while j < len(lines) and (lines[j].startswith((" ", "\t"))
                                  or lines[j].strip() == ""):
            # A blank line only continues the block if an indented line follows.
            if lines[j].strip() == "" and not (
                j + 1 < len(lines) and lines[j + 1].startswith((" ", "\t"))
            ):
                break
            j += 1
        return j

    preview_idx = find_key(f"{key}:")
    if preview_idx != -1:
        line_eol = "\r\n" if lines[preview_idx].endswith("\r\n") else (
            "\n" if lines[preview_idx].endswith("\n") else ""
        )
        lines[preview_idx] = f"{key}: {preview_path}{line_eol}"
    else:
        anchor = find_key("description:")
        if anchor == -1:
            anchor = find_key("title:")
        if anchor == -1:
            warn(f"No {key}:/description:/title: anchor in {path} front matter")
            return False
        insert_at = end_of_block(anchor)
        if not lines[anchor].endswith("\n") and insert_at == anchor + 1:
            lines[anchor] += eol  # anchor was the final unterminated line
        lines.insert(insert_at, f"{key}: {preview_path}{eol}")

    new_text = text[:fm_start] + "".join(lines) + text[fm_end:]

    backup = path.with_name(path.name + ".bak")
    tmp = path.with_name(path.name + ".tmp~")
    try:
        shutil.copy2(path, backup)
        tmp.write_bytes(new_text.encode("utf-8"))
        os.replace(tmp, path)
        backup.unlink(missing_ok=True)
    except OSError as exc:
        warn(f"Failed to update front matter in {path}: {exc}")
        tmp.unlink(missing_ok=True)
        return False

    success(f"Updated front matter with {key}: {preview_path}")
    return True


def generate_filename(title: str) -> str:
    """Slug identical to the historical Bash chain (trim before the 50-cut)."""
    slug = re.sub(r"[^a-z0-9]", "-", title.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50]


def normalize_preview_path(preview: Optional[str], settings: Settings) -> Optional[str]:
    """Front-matter path → site-absolute path (/assets/... form) for existence
    checks. External URLs pass through unchanged."""
    if not preview:
        return preview
    if preview.startswith(("http://", "https://")):
        return preview
    # Substring (not prefix) check is deliberate: it mirrors the Liquid
    # `contains` logic in components/preview-image.html and content/seo.html —
    # the engine's idea of "already prefixed" must match what the site renders.
    if settings.auto_prefix and settings.assets_prefix not in preview:
        return f"{settings.assets_prefix}{preview}"
    return preview


def check_preview_exists(preview: Optional[str], settings: Settings, root: Path) -> bool:
    if not preview:
        return False
    # External URLs count as present (matches the Liquid component + SEO tags;
    # the old Bash engine would silently regenerate over them).
    if preview.startswith(("http://", "https://")):
        return True
    normalized = normalize_preview_path(preview, settings) or ""
    clean = normalized.lstrip("/")
    candidates = [root / clean, root / "assets" / clean]
    return any(p.is_file() for p in candidates)


def preview_front_matter_path(settings: Settings, filename: str) -> str:
    """The value written to front matter — WITHOUT the assets prefix (Liquid
    adds it): assets/images/previews → /images/previews/<filename>."""
    out = settings.output_dir.strip("/")
    prefix = settings.assets_prefix.strip("/")
    if prefix and (out == prefix or out.startswith(prefix + "/")):
        out = out[len(prefix):].strip("/")
    return f"/{out}/{filename}" if out else f"/{filename}"


def find_preview_image(preview: Optional[str], settings: Settings, root: Path) -> Optional[Path]:
    """Locate an existing preview image on disk (for --enhance)."""
    if not preview or preview.startswith(("http://", "https://")):
        return None
    clean = preview.lstrip("/")
    candidates = [
        root / clean,
        root / "assets" / clean,
        root / settings.output_dir / Path(clean).name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# =============================================================================
# Prompt layer
# =============================================================================

def build_prompt(cf: ContentFile, settings: Settings) -> str:
    """Template prompt — wording carried over from the original engine."""
    parts = [f"Create a blog preview banner image for an article titled '{cf.title}'."]
    if cf.description:
        parts.append(f"The article is about: {cf.description}.")
    if cf.categories:
        parts.append(f"Categories: {cf.categories}.")
    excerpt = re.sub(r"\s+", " ", cf.content[:500]).strip()
    if excerpt:
        parts.append(f"Key themes from content: {excerpt}")
    parts.append(f"Art style: {settings.style}.")
    if settings.style_modifiers:
        parts.append(f"Additional style: {settings.style_modifiers}.")
    parts.append(
        "The image should be suitable as a wide blog header/banner image with "
        "clean composition. No text or words in the image."
    )
    return " ".join(parts)


def build_enhance_prompt(cf: ContentFile, settings: Settings) -> str:
    prompt = settings.enhance_prompt or DEFAULT_ENHANCE_PROMPT
    if cf.title:
        prompt += f" Context: This is a preview banner for an article titled '{cf.title}'."
    if cf.description:
        prompt += f" Article topic: {cf.description}."
    prompt += f" Maintain the {settings.style} artistic style."
    return prompt


def claude_model_for(settings: Settings) -> str:
    return settings.claude_model or DEFAULT_CLAUDE_MODEL


def claude_article_brief(client: "AnthropicClient", cf: ContentFile,
                         settings: Settings, base_prompt: str) -> str:
    """Analyze stage (prompt_engine: claude): Claude reads the article and
    writes the art-direction brief the renderer will receive. Falls back to
    the template prompt on any failure — analysis is an enhancement layer,
    never a hard dependency."""
    excerpt = re.sub(r"\s+", " ", cf.content[:1500]).strip()
    article = (
        f"ARTICLE\nTitle: {cf.title}\n"
        f"Description: {cf.description or '(none)'}\n"
        f"Categories/tags: {cf.categories or '(none)'}\n"
        f"Excerpt: {excerpt or '(none)'}\n\n"
        f"MANDATORY STYLE DIRECTIONS\nArt style: {settings.style}\n"
        f"Style modifiers: {settings.style_modifiers or '(none)'}\n\n"
        "Write the image-generation prompt now."
    )
    try:
        text = client.complete(
            ART_DIRECTOR_SYSTEM, article,
            model=claude_model_for(settings), max_tokens=2048,
            effort=settings.claude_effort,
        ).strip()
        if text:
            debug(f"Claude art-direction brief: {text[:300]}...")
            return text
        warn("Claude analysis returned empty text; using template prompt")
    except Exception as exc:
        warn(f"Claude analysis failed ({exc}); using template prompt")
    return base_prompt


def _extract_json_object(text: str) -> Optional[dict]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def claude_review_image(client: "AnthropicClient", image_path: Path,
                        cf: ContentFile, prompt: str,
                        settings: Settings) -> Tuple[bool, str, str]:
    """Review stage (review_engine: claude): Claude inspects the rendered
    banner. Returns (approved, critique, revised_prompt). Any failure counts
    as approval — review must never block generation."""
    context = (
        f"ARTICLE\nTitle: {cf.title}\nDescription: {cf.description or '(none)'}\n"
        f"Categories/tags: {cf.categories or '(none)'}\n\n"
        f"REQUIRED STYLE\n{settings.style}"
        + (f"; {settings.style_modifiers}" if settings.style_modifiers else "")
        + f"\n\nPROMPT THE IMAGE WAS GENERATED FROM\n{prompt}\n\n"
        "Review the image above against the article and style. JSON only."
    )
    try:
        text = client.complete_vision(
            REVIEWER_SYSTEM, context, image_path,
            model=claude_model_for(settings),
            effort=settings.claude_effort,
        )
        data = _extract_json_object(text)
        if not data:
            warn("Claude review returned no parseable verdict; keeping image")
            return True, "", ""
        verdict = str(data.get("verdict", "approve")).lower()
        critique = str(data.get("critique", "")).strip()
        revised = str(data.get("revised_prompt", "")).strip()
        if verdict == "revise" and revised:
            return False, critique, revised
        return True, critique, ""
    except Exception as exc:
        warn(f"Claude review failed ({exc}); keeping image")
        return True, "", ""


# =============================================================================
# SVG toolkit
# =============================================================================

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

_BANNED_SVG_ELEMENTS = {"script", "foreignObject", "iframe", "audio", "video", "image"}


class SvgError(Exception):
    pass


def seed_for(slug: str) -> int:
    return zlib.crc32(slug.encode("utf-8"))


def palette_for(seed: int) -> List[str]:
    return RETRO_PALETTES[seed % len(RETRO_PALETTES)]


def composition_for(seed: int) -> str:
    return COMPOSITION_VARIANTS[(seed >> 8) % len(COMPOSITION_VARIANTS)]


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


_URL_REF = re.compile(r"url\(\s*(?!#|'#|\"#)[^)]*\)", re.I)


def _scrub_style_text(value: str) -> str:
    value = re.sub(r"@import[^;]*;?", "", value, flags=re.I)
    return _URL_REF.sub("none", value)


def sanitize_svg(svg_text: str) -> Tuple[str, List[str]]:
    """Parse + sanitize model-produced SVG. Raises SvgError when unusable.

    Strips scripts/foreignObject/external references/event handlers; forces the
    banner viewBox/width/height. Returns (clean_svg, warnings).
    """
    warnings: List[str] = []
    # Reject DTDs outright: entity declarations enable expansion attacks
    # (billion-laughs) and external references; legit banner SVG needs neither.
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", svg_text, re.I):
        raise SvgError("SVG contains a DOCTYPE/ENTITY declaration (rejected)")
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise SvgError(f"SVG does not parse: {exc}") from None
    if _localname(root.tag) != "svg":
        raise SvgError(f"Root element is <{_localname(root.tag)}>, not <svg>")

    def scrub(element: ET.Element) -> None:
        for child in list(element):
            name = _localname(child.tag)
            if name in _BANNED_SVG_ELEMENTS:
                element.remove(child)
                warnings.append(f"removed <{name}>")
                continue
            scrub(child)

        for attr in list(element.attrib):
            local = _localname(attr)
            value = element.attrib[attr]
            if local.lower().startswith("on"):
                del element.attrib[attr]
                warnings.append(f"removed {local} handler")
            elif local == "href" and not value.startswith("#"):
                del element.attrib[attr]
                warnings.append("removed external href")
            elif "url(" in value.lower() or "@import" in value.lower():
                # Covers style= AND presentation attributes (fill, stroke,
                # filter, mask, clip-path, …) — url() must stay #-local.
                cleaned = _scrub_style_text(value)
                if cleaned != value:
                    element.attrib[attr] = cleaned
                    warnings.append(f"scrubbed url() in {local}")

        if _localname(element.tag) == "style" and element.text:
            cleaned = _scrub_style_text(element.text)
            if cleaned != element.text:
                element.text = cleaned
                warnings.append("scrubbed <style> url()/@import")

    scrub(root)

    root.set("viewBox", f"0 0 {SVG_WIDTH} {SVG_HEIGHT}")
    root.set("width", str(SVG_WIDTH))
    root.set("height", str(SVG_HEIGHT))

    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    return ET.tostring(root, encoding="unicode"), warnings


# --- Content-aware banner art -----------------------------------------------
# The `local` renderer used to draw ONE composition — a retro skyline under a
# sun — re-coloured per slug. Every banner on a site therefore looked like
# every other banner, and none of them had anything to do with what the article
# said. These compositions replace it: the article's own context (its section,
# tags, title and body) picks the composition AND the palette, so a shell hack
# renders as a circuit schematic and a narrative essay as a flow field.
#
# Everything here is authored at the banner frame (SVG_WIDTH x SVG_HEIGHT) so
# sanitize_svg's forced viewBox is a no-op rather than a squash, and every draw
# goes through the seeded LCG — no clock, no `random`, no environment. Same
# article in, same bytes out.

BANNER_PALETTES: Dict[str, List[str]] = {
    # [bg, far, mid, near, accent, glow]
    "neon": ["#0b0f17", "#171b2e", "#2b2a5e", "#d946ef", "#22d3ee", "#f5f3ff"],
    "ember": ["#120b16", "#2d1b2e", "#5c2a4a", "#b3324b", "#f2542d", "#ffd166"],
    "cyanic": ["#0b132b", "#1c2541", "#1c7293", "#5bc0be", "#9fd8d6", "#e8f1f2"],
    "moss": ["#101a14", "#1b2f22", "#2f5d3f", "#6f9e6f", "#a3c9a8", "#e9edc9"],
    "dusk": ["#1a1423", "#2c1f3d", "#5c3a72", "#a05fa8", "#f5a623", "#f7e8d3"],
    "slate": ["#0d1117", "#161b22", "#26303d", "#4b6178", "#7ea6c9", "#dbe7f0"],
}
BANNER_PALETTE_ORDER: List[str] = ["neon", "ember", "cyanic", "moss", "dusk", "slate"]

# Keyword -> composition. Scored against the article's section, tags, title and
# body; the highest score wins, ties break on the content seed. Kept small and
# legible on purpose — this is art direction, not a classifier.
# Matched as WHOLE WORDS, so section names must appear in the form a section
# directory actually uses ('hacks', not 'hack') alongside the topical terms.
BANNER_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("circuit", ("hack", "hacks", "shell", "bash", "zsh", "cli", "terminal",
                 "command", "script", "docker", "container", "pipeline",
                 "deploy", "git", "kernel", "server", "network", "port",
                 "cache", "sed", "awk", "grep", "ssh", "make", "compile")),
    ("pixelscene", ("tool", "tools", "review", "reviews", "app", "editor",
                    "game", "retro", "install", "cheatsheet", "productivity",
                    "keyboard", "plugin", "extension", "terminal")),
    ("starfield", ("security", "threat", "secret", "secrets", "token", "auth",
                   "permission", "permissions", "audit", "risk", "attack",
                   "privacy", "explore", "journey", "discover", "vulnerability",
                   "credential", "sandbox")),
    ("lowpoly", ("doc", "docs", "guide", "reference", "architecture", "design",
                 "system", "structure", "schema", "diagram", "overview", "spec",
                 "concept", "concepts", "glossary", "handbook")),
    ("flowfield", ("note", "notes", "essay", "story", "ai", "agent", "agents",
                   "robot", "automation", "loop", "flow", "process", "thought",
                   "retrospective", "lesson", "lessons", "journal", "reflection")),
]
BANNER_COMPOSITION_ORDER: List[str] = [
    "circuit", "flowfield", "lowpoly", "pixelscene", "starfield",
]


def _banner_lcg(seed: int):
    """glibc LCG masked to 31 bits — the engine's long-standing determinism
    seam, reused so banner art draws from the same stream shape as the rest."""
    state = seed or 1

    def nxt(bound: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state % max(bound, 1)
    return nxt


def _num(value: float, places: int = 1) -> str:
    """Round for markup. Sub-pixel precision is invisible and triples size."""
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def _mix(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb strings. Integer output, so the bytes are identical
    on every runtime regardless of float formatting."""
    t = min(max(t, 0.0), 1.0)
    out = "#"
    for i in (1, 3, 5):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out += f"{int(ca + (cb - ca) * t + 0.5):02x}"
    return out


# Trig by lookup table, built from a Taylor series rather than imported from
# math: libm rounds the last bit differently across platforms and runtimes, and
# the Ruby port is pinned byte-for-byte against this file. A 256-entry table is
# 1.4 degrees of resolution — finer than a 1px step can express at this size.
_BANNER_SIN: List[float] = []
_BANNER_COS: List[float] = []


def _build_banner_trig() -> None:
    tau = 6.283185307179586
    for i in range(256):
        a = (i / 256.0) * tau
        t = a - tau if a > 3.141592653589793 else a
        _BANNER_SIN.append(
            t - t ** 3 / 6 + t ** 5 / 120 - t ** 7 / 5040 + t ** 9 / 362880)
        _BANNER_COS.append(
            1 - t ** 2 / 2 + t ** 4 / 24 - t ** 6 / 720 + t ** 8 / 40320
            - t ** 10 / 3628800)


_build_banner_trig()


def _bsin(angle: float) -> float:
    return _BANNER_SIN[int(angle / 6.283185307179586 * 256) & 255]


def _bcos(angle: float) -> float:
    return _BANNER_COS[int(angle / 6.283185307179586 * 256) & 255]


def _banner_noise(seed: int):
    """Smoothed value noise on a 17x17 lattice, sampled in unit coordinates."""
    nxt = _banner_lcg(seed ^ 0x9E3779B9)
    grid = [[nxt(1000) / 1000.0 for _ in range(17)] for _ in range(17)]

    def at(x: float, y: float) -> float:
        gx, gy = x * 16.0, y * 16.0
        x0, y0 = int(gx), int(gy)
        fx, fy = gx - x0, gy - y0
        x1, y1 = min(x0 + 1, 16), min(y0 + 1, 16)
        # smoothstep, so the field has no directional creases
        sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a = grid[y0][x0] * (1 - sx) + grid[y0][x1] * sx
        b = grid[y1][x0] * (1 - sx) + grid[y1][x1] * sx
        return a * (1 - sy) + b * sy
    return at


def _banner_frame(body: str, pal: List[str], title: str = "") -> str:
    """Wrap a composition in the banner root. `role="img"` plus a `<title>` as
    the FIRST child is the house rule (.claude/rules/svg.md) — without it a
    screen reader announces an unlabeled graphic."""
    label = (str(title) or "banner").replace("&", "&amp;") \
        .replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" '
        f'width="{SVG_WIDTH}" height="{SVG_HEIGHT}" role="img">'
        f'<title>Preview banner: {label}</title>'
        f'<rect width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="{pal[0]}" />'
        f'{body}</svg>'
    )


def banner_flowfield(seed: int, pal: List[str], title: str = "") -> str:
    """Streamlines advected through a noise field — organic and dense, with no
    dead space anywhere in the frame."""
    nxt = _banner_lcg(seed)
    noise = _banner_noise(seed)
    w, h = SVG_WIDTH, SVG_HEIGHT
    inks = [pal[3], pal[4], pal[5], pal[2]]
    out: List[str] = []
    for _ in range(400):
        x, y = nxt(w + 240) - 120, nxt(h + 240) - 120
        pts = [(x, y)]
        # Advance in SMALL steps so the curve stays faithful to the field, but
        # record only every third one. Mapping the 0..1 noise onto a full turn
        # (not two) keeps adjacent steps from flipping ~180 degrees, which is
        # what would otherwise stutter the line into a zigzag.
        for i in range(96):
            angle = noise(min(max(x / w, 0.0), 1.0),
                          min(max(y / h, 0.0), 1.0)) * 6.283185307179586
            x += _bcos(angle) * 9
            y += _bsin(angle) * 9
            if not (-140 < x < w + 140 and -140 < y < h + 140):
                break
            if i % 3 == 2:
                pts.append((x, y))
        if len(pts) < 5:
            continue
        ink = inks[nxt(len(inks))]
        width = 0.5 + nxt(18) / 10.0
        opacity = 0.16 + nxt(50) / 100.0
        # Whole pixels: at these stroke widths a decimal is invisible and costs
        # two bytes on each of ~12k coordinate pairs.
        d = "M" + " L".join(f"{int(px)} {int(py)}" for px, py in pts)
        out.append(f'<path d="{d}" fill="none" stroke="{ink}" '
                   f'stroke-width="{_num(width)}" '
                   f'stroke-opacity="{_num(opacity, 2)}" '
                   f'stroke-linecap="round" />')
    return _banner_frame("".join(out), pal, title)


def banner_lowpoly(seed: int, pal: List[str], title: str = "") -> str:
    """Faceted gradient field — calm and technical, fills the frame edge to
    edge."""
    nxt = _banner_lcg(seed)
    noise = _banner_noise(seed)
    w, h = SVG_WIDTH, SVG_HEIGHT
    cols, rows = 22, 15
    cw, ch = w / cols, h / rows
    lattice = []
    for r in range(rows + 1):
        row = []
        for c in range(cols + 1):
            # Edge vertices stay pinned, or the border shows through.
            jx = 0.0 if c in (0, cols) else (nxt(60) - 30) / 100.0 * cw
            jy = 0.0 if r in (0, rows) else (nxt(60) - 30) / 100.0 * ch
            row.append((c * cw + jx, r * ch + jy))
        lattice.append(row)

    # Ramp CONTINUOUSLY down the frame and let the noise only shade each facet
    # slightly lighter or darker. Discrete colour stops band the field into
    # hard stripes and an accent threshold scatters floating shards.
    ramp = [pal[1], pal[2], pal[3], pal[4]]

    def facet_color(t: float, n: float) -> str:
        pos = min(max(t, 0.0), 0.999) * (len(ramp) - 1)
        i = int(pos)
        base = _mix(ramp[i], ramp[i + 1], pos - i)
        if n > 0.5:
            return _mix(base, pal[5], (n - 0.5) * 0.22)
        return _mix(base, pal[0], (0.5 - n) * 0.30)

    out: List[str] = []
    for r in range(rows):
        for c in range(cols):
            a, b = lattice[r][c], lattice[r][c + 1]
            d, e = lattice[r + 1][c], lattice[r + 1][c + 1]
            for tri in ((a, b, d), (b, e, d)):
                cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3
                cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3
                color = facet_color(cy / h, noise(cx / w, cy / h))
                points = " ".join(f"{_num(px)},{_num(py)}" for px, py in tri)
                # Stroke each facet in its own fill: float rounding otherwise
                # leaves hairline seams that render as stray light lines.
                out.append(f'<polygon points="{points}" fill="{color}" '
                           f'stroke="{color}" stroke-width="1" />')
    return _banner_frame("".join(out), pal, title)


def banner_circuit(seed: int, pal: List[str], title: str = "") -> str:
    """Orthogonal traces, pads, vias and chips — a schematic read for the
    shell/infrastructure end of a site."""
    nxt = _banner_lcg(seed)
    w, h = SVG_WIDTH, SVG_HEIGHT
    step = 32
    out: List[str] = []

    substrate = []
    for x in range(0, w + 1, step * 2):
        substrate.append(f"M{x} 0 L{x} {h}")
    for y in range(0, h + 1, step * 2):
        substrate.append(f"M0 {y} L{w} {y}")
    out.append(f'<path d="{" ".join(substrate)}" stroke="{pal[1]}" '
               f'stroke-width="1" fill="none" stroke-opacity="0.9" />')

    junctions: List[Tuple[int, int]] = []
    for _ in range(64):
        # Snap to the grid so every trace is orthogonal by construction.
        x = nxt(w // step) * step
        y = nxt(h // step) * step
        segments = [f"M{x} {y}"]
        junctions.append((x, y))
        for _ in range(3 + nxt(5)):
            if nxt(2):
                x = max(0, min(w, x + (nxt(11) - 5) * step))
                segments.append(f"L{x} {y}")
            else:
                y = max(0, min(h, y + (nxt(9) - 4) * step))
                segments.append(f"L{x} {y}")
        junctions.append((x, y))
        ink = pal[4] if nxt(3) else pal[3]
        out.append(f'<path d="{" ".join(segments)}" fill="none" stroke="{ink}" '
                   f'stroke-width="{2 + nxt(3)}" stroke-opacity="0.85" '
                   f'stroke-linecap="square" stroke-linejoin="miter" />')

    for (px, py) in junctions:
        out.append(f'<circle cx="{px}" cy="{py}" r="7" fill="{pal[0]}" '
                   f'stroke="{pal[4]}" stroke-width="3" />')

    for _ in range(6):
        x = nxt(w // step - 6) * step
        y = nxt(h // step - 4) * step
        cw, chh = (3 + nxt(3)) * step, (2 + nxt(2)) * step
        out.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{chh}" rx="6" '
                   f'fill="{pal[2]}" stroke="{pal[5]}" stroke-width="2" />')
        for leg in range(cw // step * 2):
            out.append(f'<rect x="{x + 8 + leg * (step // 2)}" y="{y + chh}" '
                       f'width="6" height="10" fill="{pal[5]}" />')
    return _banner_frame("".join(out), pal, title)


def banner_starfield(seed: int, pal: List[str], title: str = "") -> str:
    """Constellations over layered ridges — the night-sky read."""
    nxt = _banner_lcg(seed)
    w, h = SVG_WIDTH, SVG_HEIGHT
    horizon = int(h * 0.72)
    out: List[str] = []

    for _ in range(230):
        x, y = nxt(w), nxt(horizon)
        # Thin the field toward the horizon so the sky reads as deep.
        if nxt(horizon) < y * 0.75:
            continue
        out.append(f'<circle cx="{x}" cy="{y}" r="{1 + nxt(3)}" fill="{pal[5]}" '
                   f'fill-opacity="{_num(0.3 + nxt(70) / 100.0, 2)}" />')

    for _ in range(4):
        cx, cy = 120 + nxt(w - 240), 90 + nxt(horizon - 220)
        nodes = [(cx, cy)]
        for _ in range(3 + nxt(3)):
            cx += nxt(220) - 90
            cy += nxt(180) - 80
            nodes.append((cx, cy))
        d = "M" + " L".join(f"{nx} {ny}" for nx, ny in nodes)
        out.append(f'<path d="{d}" fill="none" stroke="{pal[4]}" '
                   f'stroke-width="2" stroke-opacity="0.55" />')
        for (nx, ny) in nodes:
            out.append(f'<circle cx="{nx}" cy="{ny}" r="5" fill="{pal[4]}" />')

    mx, my = w - 260 - nxt(200), 150 + nxt(120)
    out.append(f'<circle cx="{mx}" cy="{my}" r="86" fill="{pal[3]}" '
               f'fill-opacity="0.18" />')
    out.append(f'<circle cx="{mx}" cy="{my}" r="62" fill="{pal[5]}" />')
    out.append(f'<circle cx="{mx + 26}" cy="{my - 16}" r="56" fill="{pal[0]}" />')

    # Aerial perspective: the FARTHEST ridge is hazy and light, each nearer one
    # steps darker. Every layer closes to the bottom of the frame, so the
    # foreground is ridge mass rather than a flat band of background.
    for layer in range(4):
        top = horizon - 40 + layer * 58
        points = [f"0,{h}"]
        x, y = 0, float(top)
        while x <= w:
            points.append(f"{x},{_num(y)}")
            x += 40 + nxt(80)
            y = top + nxt(56) - 24
        points.append(f"{w},{_num(float(top))}")
        points.append(f"{w},{h}")
        out.append(f'<polygon points="{" ".join(points)}" '
                   f'fill="{_mix(pal[3], pal[0], layer / 3.0)}" />')
    return _banner_frame("".join(out), pal, title)


def banner_pixelscene(seed: int, pal: List[str], title: str = "") -> str:
    """Pixel-art side-scroller on a strict integer grid, run-length merged."""
    nxt = _banner_lcg(seed)
    px = 16
    cols, rows = SVG_WIDTH // px, SVG_HEIGHT // px
    cells: List[List[Optional[str]]] = [[None] * cols for _ in range(rows)]

    def put(cx: int, cy: int, color: str) -> None:
        if 0 <= cx < cols and 0 <= cy < rows:
            cells[cy][cx] = color

    def block(cx: int, cy: int, bw: int, bh: int, color: str) -> None:
        for yy in range(cy, cy + bh):
            for xx in range(cx, cx + bw):
                put(xx, yy, color)

    ground = rows - 12
    for _ in range(150):
        sx, sy = nxt(cols), nxt(ground - 4)
        if nxt(ground) > sy:
            put(sx, sy, pal[5] if nxt(4) else pal[3])

    sun_x, sun_y = cols - 20 + nxt(8), 6 + nxt(5)
    for yy in range(-4, 5):
        for xx in range(-4, 5):
            d2 = xx * xx + yy * yy
            if d2 <= 16:
                put(sun_x + xx, sun_y + yy, pal[4])
            elif d2 <= 25:
                put(sun_x + xx, sun_y + yy, pal[3])

    # `surface` is the row the ground starts at; fill from there to the bottom
    # so the land is solid mass rather than a one-cell scribble.
    surface = ground
    for cx in range(cols):
        if nxt(4) == 0:
            surface = max(ground - 5, min(rows - 4, surface + nxt(3) - 1))
        block(cx, surface, 1, rows - surface, pal[2])
        put(cx, surface, pal[3])
        if nxt(7) == 0:
            put(cx, surface + 2 + nxt(4), pal[1])

    for _ in range(5):
        span = 5 + nxt(8)
        bx, by = nxt(max(cols - span, 1)), ground - 9 - nxt(16)
        for i in range(span):
            put(bx + i, by, pal[3])
            put(bx + i, by + 1, pal[1])

    # The hero: 6x9 cells with a dark keyline, so it reads off any ground
    # colour and stays the only glow-coloured figure in frame.
    hx, hy = 10 + nxt(14), ground - 10
    block(hx - 1, hy - 1, 8, 11, pal[0])
    block(hx + 1, hy, 4, 2, pal[4])
    block(hx + 1, hy + 2, 4, 1, pal[1])
    block(hx, hy + 3, 6, 4, pal[5])
    block(hx + 2, hy + 4, 2, 2, pal[3])
    block(hx, hy + 7, 2, 3, pal[5])
    block(hx + 4, hy + 7, 2, 3, pal[5])
    block(hx + 6, hy + 1, 1, 6, pal[4])

    # Merge horizontal runs of one colour into single rects: a 96x64 scene
    # stays a few KB instead of six thousand one-cell rects.
    out: List[str] = []
    for y in range(rows):
        x = 0
        while x < cols:
            color = cells[y][x]
            if color is None:
                x += 1
                continue
            run = 1
            while x + run < cols and cells[y][x + run] == color:
                run += 1
            out.append(f'<rect x="{x * px}" y="{y * px}" width="{run * px}" '
                       f'height="{px}" fill="{color}" />')
            x += run
    body = f'<g shape-rendering="crispEdges">{"".join(out)}</g>'
    veil = "".join(f'<rect y="{y}" width="{SVG_WIDTH}" height="2" />'
                   for y in range(0, SVG_HEIGHT, 6))
    body += f'<g fill="{pal[0]}" fill-opacity="0.22">{veil}</g>'
    return _banner_frame(body, pal, title)


BANNER_COMPOSITIONS = {
    "circuit": banner_circuit,
    "flowfield": banner_flowfield,
    "lowpoly": banner_lowpoly,
    "pixelscene": banner_pixelscene,
    "starfield": banner_starfield,
}


_BANNER_WORD = re.compile(r"[a-z0-9]+")


def _banner_words(text: str) -> List[str]:
    """Whole words, lowercased. Substring matching is not good enough here:
    a bare `"ci" in text` fires on 'decision', 'specific' and 'efficiency',
    which is enough to drag every article on a dev blog toward one look."""
    return _BANNER_WORD.findall(str(text or "").lower())


def banner_signature(article: Dict[str, str]) -> str:
    """The text the art is derived from. Title and tags carry the topic; the
    section carries the editorial intent; a slice of the body keeps two posts
    with near-identical titles from colliding."""
    return " ".join([
        article.get("section", ""),
        article.get("categories", ""),
        article.get("title", ""),
        article.get("description", ""),
        article.get("body", "")[:600],
    ]).lower()


def banner_seed_for(article: Dict[str, str]) -> int:
    """Seed from the article's CONTENT, not just its filename — so retitling or
    re-tagging a piece re-rolls its art, and two posts that merely sort next to
    each other don't come out kin."""
    key = banner_signature(article) + "|" + article.get("slug", "")
    return zlib.crc32(key.encode("utf-8"))


def banner_theme_for(article: Dict[str, str]) -> Tuple[str, str]:
    """(composition, palette) for an article. Keyword hits decide; the seed only
    breaks ties and picks the palette, so the mapping is legible to a human
    reading the config rather than an opaque hash.

    The fields are weighted, not pooled. A section name is a deliberate
    editorial choice and the tags and title are hand-written, so they carry
    most of the signal; the body is long, incidental, and full of words the
    author never chose, so each of its hits counts once and the whole field is
    capped. Pooling them all equally lets a 3,000-word article's stray
    vocabulary outvote its own title."""
    fields = (
        (article.get("section", ""), 6),
        (article.get("categories", ""), 3),
        (article.get("title", ""), 3),
        (article.get("description", ""), 2),
        (article.get("body", "")[:4000], 1),
    )
    scored = [(set(_banner_words(text)), weight) for text, weight in fields]
    seed = banner_seed_for(article)

    best_name, best_score = "", 0
    for name, keywords in BANNER_KEYWORDS:
        wanted = set(keywords)
        score = 0
        for words, weight in scored:
            hits = len(wanted & words)
            # Cap the body's contribution: presence, not word count, is what
            # the low-weight field is evidence of.
            score += min(hits, 4) * weight if weight == 1 else hits * weight
        # Strictly greater, so ties fall to the earlier (more specific) entry.
        if score > best_score:
            best_name, best_score = name, score
    if not best_name:
        best_name = BANNER_COMPOSITION_ORDER[seed % len(BANNER_COMPOSITION_ORDER)]

    palette = BANNER_PALETTE_ORDER[(seed >> 8) % len(BANNER_PALETTE_ORDER)]
    return best_name, palette


def render_local_svg(title: str, seed: int,
                     article: Optional[Dict[str, str]] = None) -> str:
    """Deterministic banner for the `local` provider (no network).

    `article` carries the page's context (slug, section, title, tags, body); it
    selects the composition and palette. Without it — a caller that only has a
    slug — the art still renders, just chosen from the seed alone."""
    if article:
        composition, palette = banner_theme_for(article)
        art_seed = banner_seed_for(article)
    else:
        composition = BANNER_COMPOSITION_ORDER[seed % len(BANNER_COMPOSITION_ORDER)]
        palette = BANNER_PALETTE_ORDER[(seed >> 8) % len(BANNER_PALETTE_ORDER)]
        art_seed = seed
    return BANNER_COMPOSITIONS[composition](
        art_seed, BANNER_PALETTES[palette], title)


# =============================================================================
# Rasterizer chain
# =============================================================================

# Tool discovery is per-run stable; memoize the PATH walks so a batch of N
# files doesn't pay N x 4 which() scans.
@functools.lru_cache(maxsize=None)
def _which(tool: str) -> Optional[str]:
    return shutil.which(tool)


def _run_quiet(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> bool:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        debug(f"rasterizer {cmd[0]} failed: {exc}")
        return False
    if proc.returncode != 0:
        debug(f"rasterizer {cmd[0]} exit {proc.returncode}: "
              f"{proc.stderr.decode('utf-8', 'replace')[:200]}")
        return False
    return True


def _playwright_helper(project_root: Path) -> Optional[Path]:
    candidates = [
        # Gem layout: helper vendored beside this file.
        Path(__file__).resolve().parent / "rasterize-svg.js",
        # Theme/curl layout: <site>/scripts/lib/<engine> + <site>/scripts/dev/.
        Path(__file__).resolve().parent.parent / "dev" / "rasterize-svg.js",
        project_root / "scripts" / "dev" / "rasterize-svg.js",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


RASTERIZER_CHOICES: List[str] = [
    "auto", "rsvg", "resvg", "inkscape", "magick", "playwright", "none",
]


def _resvg_attempt(svg_path: Path, png_path: Path, w: int, explicit: bool) -> bool:
    """resvg — the closest headless match to browser rendering (cairo-based
    tools mis-render feTurbulence, for one). Native `resvg` first, then the
    `resvg-js` CLI (`npm i -g @resvg/resvg-js-cli`). Only an EXPLICIT
    `resvg` preference may fall through to `npx -y`, because that downloads a
    package — `auto` must never reach for the network on its own."""
    if _which("resvg"):
        return _run_quiet(["resvg", "-w", str(w), str(svg_path), str(png_path)])
    if _which("resvg-js"):
        return _run_quiet(["resvg-js", "--fit-width", str(w), str(svg_path), str(png_path)])
    if explicit and _which("npx"):
        return _run_quiet(["npx", "-y", "@resvg/resvg-js-cli", "--fit-width", str(w),
                           str(svg_path), str(png_path)], timeout=300)
    return False


def rasterize_svg(
    svg_path: Path, png_path: Path, project_root: Path, preference: str = "auto",
    width: int = SVG_WIDTH,
) -> Optional[str]:
    """SVG → PNG through the first available tool. Returns the tool name used,
    or None when nothing worked (caller keeps the .svg).

    `width` sets the output pixel width (height follows the banner's aspect),
    so the illustration loop can render the same file at full size and at
    card-thumbnail size."""
    w = max(1, int(width))
    h = max(1, int(round(w * SVG_HEIGHT / SVG_WIDTH)))
    helper = _playwright_helper(project_root)
    chain: List[Tuple[str, Any]] = [
        ("rsvg", lambda: _which("rsvg-convert") and _run_quiet(
            ["rsvg-convert", "-w", str(w), "-h", str(h), "-o", str(png_path), str(svg_path)])),
        ("resvg", lambda: _resvg_attempt(svg_path, png_path, w, preference == "resvg")),
        ("inkscape", lambda: _which("inkscape") and _run_quiet(
            ["inkscape", str(svg_path), "--export-type=png",
             f"--export-filename={png_path}", "-w", str(w), "-h", str(h)])),
        ("magick", lambda: (
            (_which("magick") and _run_quiet(
                ["magick", str(svg_path), "-resize", f"{w}x{h}", str(png_path)]))
            or (_which("convert") and _run_quiet(
                ["convert", str(svg_path), "-resize", f"{w}x{h}", str(png_path)]))
        )),
        ("playwright", lambda: helper is not None and _which("node") and _run_quiet(
            ["node", str(helper), str(svg_path), str(png_path), str(w), str(h)],
            cwd=project_root, timeout=180)),
    ]
    if preference == "none":
        return None
    if preference != "auto":
        chain = [entry for entry in chain if entry[0] == preference]
        if not chain:
            warn(f"Unknown rasterizer '{preference}'")
            return None
    for name, attempt in chain:
        if attempt():
            try:
                if png_path.is_file() and png_path.read_bytes()[:8] == PNG_SIGNATURE:
                    debug(f"Rasterized with {name}: {png_path.name}")
                    return name
            except OSError:
                pass
            png_path.unlink(missing_ok=True)
    return None


# =============================================================================
# SVG lint (deterministic) — the checks not worth a model token
# =============================================================================
# This is the ONE Python implementation: tools/svg/svg-check.py is a thin CLI
# over lint_svg(), and lib/zer0_image_generator/svg/lint.rb is pinned to that
# CLI's output by test/ruby/test_svg_lint.rb. Message wording and finding
# order are contract — the authoring loop feeds them back to the model as the
# reason to fix, so rewording one changes what Claude is told.

LINT_NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
LINT_DEFAULT_MAX_KB = 250.0
LINT_TEXT_WARNING = ("<text> present — fonts are not guaranteed at render "
                     "time. Convert to paths for distribution.")


@dataclass
class SvgLintReport:
    label: str
    kilobytes: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    fatal: Optional[str] = None
    strict: bool = False

    @property
    def clean(self) -> bool:
        if self.fatal:
            return False
        return not self.errors and not (self.strict and self.warnings)

    def stderr_lines(self) -> List[str]:
        if self.fatal:
            return [f"ERROR {self.fatal}"]
        return ([f"WARN  {w}" for w in self.warnings]
                + [f"ERROR {e}" for e in self.errors])

    def stdout_lines(self) -> List[str]:
        if not self.clean:
            return []
        return [f"svg-check: {self.label} clean ({self.kilobytes:.1f}KB)"]

    def findings(self) -> List[str]:
        """Every problem as one list — what a fix round is told."""
        if self.fatal:
            return [self.fatal]
        return list(self.errors) + (list(self.warnings) if self.strict else [])


def _lint_tag(el: ET.Element) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _lint_href(el: ET.Element) -> Optional[str]:
    return el.get("href") or el.get(f"{{{XLINK_NS}}}href")


def _lint_viewbox(root: ET.Element) -> Optional[Tuple[float, ...]]:
    vb = root.get("viewBox")
    if not vb:
        return None
    parts = [float(n) for n in LINT_NUM.findall(vb)]
    return tuple(parts[:4]) if len(parts) == 4 else None


def _lint_path_coords(d: str) -> List[Tuple[float, float]]:
    """Rough absolute-coordinate sample. Ignores relative commands on purpose —
    we only want a cheap 'is this wildly outside the canvas' signal."""
    out: List[Tuple[float, float]] = []
    for seg in re.findall(r"[MLHVCSQTA][^A-Za-z]*", d):
        nums = [float(n) for n in LINT_NUM.findall(seg[1:])]
        cmd = seg[0]
        if cmd in "ML" and len(nums) >= 2:
            out += list(zip(nums[0::2], nums[1::2]))
        elif cmd == "C":
            out += list(zip(nums[4::6], nums[5::6]))
    return out


def lint_svg(raw: bytes, label: str = "svg", max_kb: float = LINT_DEFAULT_MAX_KB,
             strict: bool = False) -> SvgLintReport:
    """Lint SVG bytes. `strict` treats warnings as failures (and is the only
    mode that flags <text>). Never raises — an unparseable file is a `fatal`
    finding, which (like svg-check.py's early return) discards the rest."""
    report = SvgLintReport(label=label, strict=strict)
    errors, warnings = report.errors, report.warnings
    kb = len(raw) / 1024
    report.kilobytes = kb
    if kb > max_kb:
        errors.append(f"file is {kb:.0f}KB, budget is {max_kb:.0f}KB "
                      f"(run svgo, or reduce path precision)")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return SvgLintReport(label=label, kilobytes=kb, strict=strict,
                             fatal=f"not well-formed XML: {e}")

    if _lint_tag(root) != "svg":
        errors.append(f"root element is <{_lint_tag(root)}>, expected <svg>")

    vb = _lint_viewbox(root)
    if vb is None:
        errors.append("no viewBox on root — the art will not scale. "
                      'Add viewBox="0 0 W H".')

    kids = [_lint_tag(c) for c in root]
    if "title" not in kids:
        warnings.append("no <title> as first child (screen readers, and it "
                        "shows as a tooltip)")
    if root.get("role") != "img":
        warnings.append('missing role="img" on root')

    ids, dupes = set(), set()
    used_refs = set()
    ext_refs: List[str] = []

    for el in root.iter():
        t = _lint_tag(el)
        _id = el.get("id")
        if _id:
            (dupes.add(_id) if _id in ids else ids.add(_id))

        h = _lint_href(el)
        if h:
            if h.startswith("#"):
                used_refs.add(h[1:])
            elif h.startswith(("http://", "https://", "//")):
                ext_refs.append(h)
            elif h.startswith("data:image") and t == "image":
                errors.append("embedded raster <image> — that is a PNG in a "
                              "trenchcoat, not vector art")
            elif t == "image":
                errors.append(f"external <image> reference: {h}")

        for _attr, val in el.attrib.items():
            m = re.match(r"url\(#([^)]+)\)", (val or "").strip())
            if m:
                used_refs.add(m.group(1))

        if vb and t == "path" and el.get("d"):
            minx, miny, w, h_ = vb
            pad = max(w, h_) * 2
            for x, y in _lint_path_coords(el.get("d")):
                if not (minx - pad <= x <= minx + w + pad and
                        miny - pad <= y <= miny + h_ + pad):
                    warnings.append(
                        f"path coordinate ({x:g},{y:g}) is far outside the "
                        f"viewBox — likely a stray control point")
                    break

        if t == "path" and el.get("d"):
            long_decimals = re.findall(r"\d+\.\d{5,}", el.get("d"))
            if len(long_decimals) > 20:
                warnings.append("path data carries 5+ decimal places; round "
                                "to 2-3 to cut file size ~40%")

        if t == "text" and strict:
            warnings.append(LINT_TEXT_WARNING)

    if ext_refs:
        errors.append(f"external network references: {', '.join(ext_refs[:3])}")
    if dupes:
        errors.append(f"duplicate id(s): {', '.join(sorted(dupes))}")
    dangling = used_refs - ids
    if dangling:
        errors.append(f"reference(s) to missing id(s): "
                      f"{', '.join(sorted(dangling))} — gradient or clipPath "
                      f"will silently render as black/none")
    return report


# =============================================================================
# SVG text → paths (bundled fonts, stdlib TrueType reader)
# =============================================================================
# Claude lays out a headline far better with <text> than by hand-authoring
# glyph outlines, and the title is the most useful thing on a banner — but a
# committed <text> renders in whatever font the viewer happens to have. So the
# loop AUTHORS with <text> and SHIPS paths: every <text> is converted here
# using a font bundled with the engine (fonts/, all OFL), and strict lint then
# holds its no-<text> rule.
#
# The reader handles exactly what the bundled fonts use — TrueType outlines
# (glyf/loca, simple + composite glyphs), cmap format 4, hmtx — and nothing
# else (no kerning, no shaping, no hinting). It is stdlib-only by policy and
# pinned byte-for-byte by the Ruby twin (svg/text_to_paths.rb): every number
# that reaches a path goes through _fmt2, which rounds with floor(x*100+0.5)
# on IEEE doubles so both languages print the same digits.

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# Family key → (file, CSS family names that select it). The first family in a
# font-family list that names a bundled font wins; anything else (serif,
# monospace, a font Claude imagined) resolves to the style card's default.
BUNDLED_FONTS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "press-start-2p": ("PressStart2P-Regular.ttf", ("press start 2p", "press start", "pressstart2p")),
    "inter": ("Inter-Regular.ttf", ("inter",)),
    "inter-bold": ("Inter-Bold.ttf", ()),
}
DEFAULT_FONT_FAMILY = "inter"
# Style card → the family its headline is set in.
CARD_FONTS: Dict[str, str] = {"retro-pixel": "press-start-2p"}

_FONT_CACHE: Dict[str, "TrueTypeFont"] = {}
_FONT_LOCK = threading.Lock()


def _fmt2(value: float) -> str:
    """Two-decimal fixed format with trailing zeros dropped ("12.5", "-3",
    "0.07"). Deterministic across Python and Ruby — see the section note."""
    n = int(math.floor(value * 100 + 0.5))
    sign = "-" if n < 0 else ""
    n = abs(n)
    whole, frac = divmod(n, 100)
    if frac == 0:
        return f"{sign}{whole}" if whole else "0"
    digits = f"{frac:02d}".rstrip("0")
    return f"{sign}{whole}.{digits}"


class TrueTypeFont:
    """Just enough of a TrueType font to draw Latin headlines."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.tables: Dict[str, Tuple[int, int]] = {}
        num_tables = self._u16(4)
        for i in range(num_tables):
            rec = 12 + 16 * i
            tag = self.data[rec:rec + 4].decode("latin-1")
            self.tables[tag] = (self._u32(rec + 8), self._u32(rec + 12))
        for required in ("head", "hhea", "hmtx", "maxp", "cmap", "loca", "glyf"):
            if required not in self.tables:
                raise ValueError(f"{self.path.name}: missing {required} table")
        head = self.tables["head"][0]
        self.units_per_em = self._u16(head + 18)
        self.long_loca = self._s16(head + 50) == 1
        hhea = self.tables["hhea"][0]
        self.ascender = self._s16(hhea + 4)
        self.descender = self._s16(hhea + 6)
        self.num_hmetrics = self._u16(hhea + 34)
        self.num_glyphs = self._u16(self.tables["maxp"][0] + 4)
        self.x_height = self.units_per_em // 2
        if "OS/2" in self.tables:
            os2, os2_len = self.tables["OS/2"]
            if self._u16(os2) >= 2 and os2_len >= 88:
                self.x_height = self._s16(os2 + 86) or self.x_height
        self.cmap = self._read_cmap()
        self._glyph_cache: Dict[int, List[List[Tuple[float, float, bool]]]] = {}

    # -- binary helpers -------------------------------------------------------
    def _u16(self, off: int) -> int:
        return (self.data[off] << 8) | self.data[off + 1]

    def _s16(self, off: int) -> int:
        v = self._u16(off)
        return v - 0x10000 if v >= 0x8000 else v

    def _u32(self, off: int) -> int:
        return (self._u16(off) << 16) | self._u16(off + 2)

    # -- tables ---------------------------------------------------------------
    def _read_cmap(self) -> Dict[int, int]:
        base = self.tables["cmap"][0]
        chosen = None
        for i in range(self._u16(base + 2)):
            rec = base + 4 + 8 * i
            platform, encoding = self._u16(rec), self._u16(rec + 2)
            sub = base + self._u32(rec + 4)
            if self._u16(sub) != 4:
                continue
            if (platform, encoding) == (3, 1) or (platform == 0 and chosen is None):
                chosen = sub
        if chosen is None:
            raise ValueError(f"{self.path.name}: no cmap format 4 subtable")
        seg_x2 = self._u16(chosen + 6)
        ends = chosen + 14
        starts = ends + seg_x2 + 2
        deltas = starts + seg_x2
        ranges = deltas + seg_x2
        mapping: Dict[int, int] = {}
        for seg in range(seg_x2 // 2):
            end = self._u16(ends + 2 * seg)
            start = self._u16(starts + 2 * seg)
            delta = self._u16(deltas + 2 * seg)
            range_off = self._u16(ranges + 2 * seg)
            if start == 0xFFFF:
                continue
            for cp in range(start, end + 1):
                if range_off == 0:
                    gid = (cp + delta) & 0xFFFF
                else:
                    addr = ranges + 2 * seg + range_off + 2 * (cp - start)
                    gid = self._u16(addr)
                    if gid:
                        gid = (gid + delta) & 0xFFFF
                if gid:
                    mapping[cp] = gid
        return mapping

    def glyph_id(self, char: str) -> int:
        return self.cmap.get(ord(char), 0)

    def advance(self, gid: int) -> int:
        hmtx = self.tables["hmtx"][0]
        index = gid if gid < self.num_hmetrics else self.num_hmetrics - 1
        return self._u16(hmtx + 4 * index)

    def _glyph_range(self, gid: int) -> Tuple[int, int]:
        loca = self.tables["loca"][0]
        if self.long_loca:
            start, end = self._u32(loca + 4 * gid), self._u32(loca + 4 * gid + 4)
        else:
            start, end = 2 * self._u16(loca + 2 * gid), 2 * self._u16(loca + 2 * gid + 2)
        glyf = self.tables["glyf"][0]
        return glyf + start, end - start

    def contours(self, gid: int, depth: int = 0) -> List[List[Tuple[float, float, bool]]]:
        """Contours as lists of (x, y, on_curve) in font units (y up)."""
        if gid in self._glyph_cache:
            return self._glyph_cache[gid]
        if gid >= self.num_glyphs or depth > 8:
            return []
        off, length = self._glyph_range(gid)
        if length == 0:
            result: List[List[Tuple[float, float, bool]]] = []
        elif self._s16(off) >= 0:
            result = self._simple_glyph(off)
        else:
            result = self._composite_glyph(off, depth)
        self._glyph_cache[gid] = result
        return result

    def _simple_glyph(self, off: int) -> List[List[Tuple[float, float, bool]]]:
        n_contours = self._s16(off)
        p = off + 10
        end_pts = [self._u16(p + 2 * i) for i in range(n_contours)]
        p += 2 * n_contours
        n_points = (end_pts[-1] + 1) if end_pts else 0
        p += 2 + self._u16(p)  # skip instructions
        flags: List[int] = []
        while len(flags) < n_points:
            flag = self.data[p]
            p += 1
            flags.append(flag)
            if flag & 0x08:
                repeat = self.data[p]
                p += 1
                flags.extend([flag] * repeat)
        flags = flags[:n_points]

        def coords(short_bit: int, same_bit: int) -> List[int]:
            nonlocal p
            values: List[int] = []
            value = 0
            for flag in flags:
                if flag & short_bit:
                    delta = self.data[p]
                    p += 1
                    value += delta if flag & same_bit else -delta
                elif not flag & same_bit:
                    value += self._s16(p)
                    p += 2
                values.append(value)
            return values

        xs = coords(0x02, 0x10)
        ys = coords(0x04, 0x20)
        contours: List[List[Tuple[float, float, bool]]] = []
        start = 0
        for end in end_pts:
            contours.append([(float(xs[i]), float(ys[i]), bool(flags[i] & 0x01))
                             for i in range(start, end + 1)])
            start = end + 1
        return contours

    def _composite_glyph(self, off: int, depth: int) -> List[List[Tuple[float, float, bool]]]:
        p = off + 10
        result: List[List[Tuple[float, float, bool]]] = []
        while True:
            flags = self._u16(p)
            gid = self._u16(p + 2)
            p += 4
            if flags & 0x0001:  # ARG_1_AND_2_ARE_WORDS
                a1, a2 = self._s16(p), self._s16(p + 2)
                p += 4
            else:
                a1, a2 = self.data[p], self.data[p + 1]
                a1 = a1 - 256 if a1 >= 128 else a1
                a2 = a2 - 256 if a2 >= 128 else a2
                p += 2
            dx, dy = (float(a1), float(a2)) if flags & 0x0002 else (0.0, 0.0)
            xx, xy, yx, yy = 1.0, 0.0, 0.0, 1.0
            if flags & 0x0008:  # WE_HAVE_A_SCALE
                xx = yy = self._s16(p) / 16384.0
                p += 2
            elif flags & 0x0040:  # WE_HAVE_AN_X_AND_Y_SCALE
                xx, yy = self._s16(p) / 16384.0, self._s16(p + 2) / 16384.0
                p += 4
            elif flags & 0x0080:  # WE_HAVE_A_TWO_BY_TWO
                xx, yx = self._s16(p) / 16384.0, self._s16(p + 2) / 16384.0
                xy, yy = self._s16(p + 4) / 16384.0, self._s16(p + 6) / 16384.0
                p += 8
            for contour in self.contours(gid, depth + 1):
                result.append([(xx * x + xy * y + dx, yx * x + yy * y + dy, on)
                               for (x, y, on) in contour])
            if not flags & 0x0020:  # MORE_COMPONENTS
                break
        return result


def load_bundled_font(family: str) -> Optional[TrueTypeFont]:
    """The bundled font for a family key, or None when fonts/ is absent (the
    standalone single-file install)."""
    entry = BUNDLED_FONTS.get(family)
    if entry is None:
        return None
    path = FONTS_DIR / entry[0]
    with _FONT_LOCK:
        if family not in _FONT_CACHE:
            if not path.is_file():
                return None
            _FONT_CACHE[family] = TrueTypeFont(path)
        return _FONT_CACHE[family]


def fonts_available() -> bool:
    return all((FONTS_DIR / entry[0]).is_file() for entry in BUNDLED_FONTS.values())


def resolve_font_family(css_family: str, weight: str, default_family: str) -> str:
    """Map a CSS font-family list + weight onto a bundled family key."""
    chosen = default_family if default_family in BUNDLED_FONTS else DEFAULT_FONT_FAMILY
    for name in str(css_family or "").split(","):
        wanted = name.strip().strip("'\"").lower()
        hit = next((key for key, (_f, names) in BUNDLED_FONTS.items() if wanted in names), None)
        if hit:
            chosen = hit
            break
    if chosen == "inter" and _is_bold(weight):
        chosen = "inter-bold"
    return chosen


def _is_bold(weight: str) -> bool:
    w = str(weight or "").strip().lower()
    if w in ("bold", "bolder"):
        return True
    return w.isdigit() and int(w) >= 600


def _contour_path(contour: List[Tuple[float, float, bool]], ox: float, oy: float,
                  scale: float) -> str:
    """One closed TrueType contour → absolute SVG path commands."""
    if not contour:
        return ""

    def pt(x: float, y: float) -> str:
        return f"{_fmt2(ox + x * scale)} {_fmt2(oy - y * scale)}"

    if contour[0][2]:
        start = contour[0]
        seq = contour[1:] + [contour[0]]
    elif contour[-1][2]:
        start = contour[-1]
        seq = list(contour)
    else:
        first, last = contour[0], contour[-1]
        start = ((first[0] + last[0]) / 2.0, (first[1] + last[1]) / 2.0, True)
        seq = list(contour) + [start]
    out = [f"M{pt(start[0], start[1])}"]
    ctrl: Optional[Tuple[float, float, bool]] = None
    for point in seq:
        if point[2]:
            if ctrl is not None:
                out.append(f"Q{pt(ctrl[0], ctrl[1])} {pt(point[0], point[1])}")
                ctrl = None
            else:
                out.append(f"L{pt(point[0], point[1])}")
        else:
            if ctrl is not None:
                mid = ((ctrl[0] + point[0]) / 2.0, (ctrl[1] + point[1]) / 2.0)
                out.append(f"Q{pt(ctrl[0], ctrl[1])} {pt(mid[0], mid[1])}")
            ctrl = point
    # A closing straight segment back to the start is implied by Z.
    if len(out) > 1 and out[-1] == f"L{pt(start[0], start[1])}":
        out.pop()
    out.append("Z")
    return "".join(out)


def text_advance(font: TrueTypeFont, text: str, size: float,
                 letter_spacing: float = 0.0) -> float:
    """Rendered width of `text` at `size` (letter-spacing between glyphs)."""
    if not text:
        return 0.0
    scale = size / font.units_per_em
    width = sum(font.advance(font.glyph_id(ch)) * scale for ch in text)
    return width + letter_spacing * (len(text) - 1)


def glyph_run_path(font: TrueTypeFont, text: str, x: float, y: float, size: float,
                   letter_spacing: float = 0.0) -> Tuple[str, float, int]:
    """Path data for `text` with its baseline-left at (x, y).

    Returns (d, advance, missing) — `missing` counts characters the font has
    no glyph for (drawn as empty space of the .notdef advance)."""
    scale = size / font.units_per_em
    pen = x
    parts: List[str] = []
    missing = 0
    for i, ch in enumerate(text):
        gid = font.glyph_id(ch)
        if gid == 0 and not ch.isspace():
            missing += 1
        else:
            for contour in font.contours(gid):
                parts.append(_contour_path(contour, pen, y, scale))
        pen += font.advance(gid) * scale
        if i < len(text) - 1:
            pen += letter_spacing
    return "".join(parts), pen - x, missing


def baseline_shift(font: TrueTypeFont, baseline: str, size: float) -> float:
    """Offset (user units, +down) that moves a dominant-baseline onto the
    alphabetic baseline the outlines are drawn from."""
    scale = size / font.units_per_em
    mode = str(baseline or "").strip().lower()
    if mode == "middle":
        return font.x_height * scale / 2.0
    if mode == "central":
        return (font.ascender + font.descender) * scale / 2.0
    if mode in ("hanging", "text-before-edge", "text-top"):
        return font.ascender * scale
    if mode in ("text-after-edge", "text-bottom", "ideographic"):
        return font.descender * scale
    return 0.0


def fit_headline(font: TrueTypeFont, text: str, max_width: float, max_lines: int,
                 max_size: float, min_size: float, max_height: float = 0.0,
                 leading: float = 1.25, step: float = 2.0) -> Tuple[List[str], float]:
    """Break `text` into at most `max_lines` lines at WORD boundaries, at the
    largest size in [min_size, max_size] (stepping down by `step`) where every
    line fits `max_width` and (when `max_height` > 0) the block of lines at
    `leading` × size stays within `max_height` — a headline is a caption, not
    the picture.

    Never hyphenates or splits a word — "CHAN-/DRAYA/AN-1" is exactly the
    defect this exists to prevent. When nothing fits even at min_size, the
    words are packed into max_lines at min_size and text_to_paths' overflow
    guard scales the long line down at conversion time."""
    words = [w for w in re.split(r"\s+", str(text or "").strip()) if w]
    if not words:
        return [], float(max_size)
    size = float(max_size)
    while size >= min_size - 1e-9:
        lines = _greedy_lines(font, words, size, max_width)
        fits_height = max_height <= 0 or len(lines) * size * leading <= max_height
        if fits_height and len(lines) <= max_lines and all(
                text_advance(font, line, size) <= max_width for line in lines):
            return lines, size
        size -= step
    lines = _greedy_lines(font, words, float(min_size), max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return lines, float(min_size)


def _greedy_lines(font: TrueTypeFont, words: List[str], size: float,
                  max_width: float) -> List[str]:
    """Fill each line with as many words as fit (a lone overlong word still
    takes its own line)."""
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}" if current else word
        if not current or text_advance(font, trial, size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# --- the document walk -------------------------------------------------------

# Properties that only mean something to text layout — consumed here, never
# carried onto the replacement <g>/<path>.
_TEXT_LAYOUT_PROPS = frozenset((
    "font", "font-family", "font-size", "font-weight", "font-style", "font-variant",
    "font-stretch", "text-anchor", "letter-spacing", "word-spacing",
    "dominant-baseline", "alignment-baseline", "baseline-shift", "writing-mode",
    "text-rendering", "white-space", "text-decoration",
    "x", "y", "dx", "dy", "rotate", "textLength", "lengthAdjust",
    "{http://www.w3.org/XML/1998/namespace}space",
))
_INHERITED_TEXT_PROPS = ("font-family", "font-size", "font-weight", "text-anchor",
                         "letter-spacing", "dominant-baseline")
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_SELECTOR = re.compile(r"\A(text|tspan)?(?:\.([A-Za-z_][\w-]*))?\Z")
DEFAULT_TEXT_SIZE = 16.0
TEXT_FIT_FRACTION = 0.94   # a line may span at most this share of the frame


@dataclass
class TextToPathsResult:
    svg: str
    converted: int = 0
    stripped: int = 0
    fitted: int = 0
    missing_glyphs: int = 0
    notes: List[str] = field(default_factory=list)


def _style_decls(style: str) -> Dict[str, str]:
    decls: Dict[str, str] = {}
    for part in str(style or "").split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            if key.strip():
                decls[key.strip().lower()] = value.strip()
    return decls


def _css_rules(root: ET.Element) -> List[Tuple[Optional[str], Optional[str], Dict[str, str]]]:
    """(tag, class, declarations) for the simple selectors a model writes for
    text — `text`, `tspan`, `.cls`, `text.cls`. Anything fancier is ignored."""
    rules: List[Tuple[Optional[str], Optional[str], Dict[str, str]]] = []
    for el in root.iter():
        if _localname(el.tag) != "style" or not el.text:
            continue
        css = re.sub(r"/\*.*?\*/", "", el.text, flags=re.S)
        for selectors, body in _CSS_RULE.findall(css):
            decls = _style_decls(body)
            for selector in selectors.split(","):
                match = _CSS_SELECTOR.match(selector.strip())
                if match and (match.group(1) or match.group(2)):
                    rules.append((match.group(1), match.group(2), decls))
    return rules


def _css_matches(el: ET.Element, tag: Optional[str], cls: Optional[str]) -> bool:
    if tag and _localname(el.tag) != tag:
        return False
    return not cls or cls in str(el.get("class") or "").split()


def _length(value: str, reference: float) -> Optional[float]:
    raw = str(value or "").strip().lower()
    match = re.match(r"\A(-?\d*\.?\d+(?:e[-+]?\d+)?)\s*(px|pt|em|rem|%)?\Z", raw)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    if unit == "pt":
        return number * 4.0 / 3.0
    if unit == "em":
        return number * reference
    if unit == "rem":
        return number * DEFAULT_TEXT_SIZE
    if unit == "%":
        return number * reference / 100.0
    return number


def _first_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    match = LINT_NUM.search(str(value))
    return float(match.group(0)) if match else None


class _TextStyler:
    """Computed text properties: inline style > CSS rule > attribute > parent."""

    def __init__(self, root: ET.Element):
        self.rules = _css_rules(root)
        self.parents = {child: parent for parent in root.iter() for child in parent}

    def own(self, el: ET.Element, prop: str) -> Optional[str]:
        inline = _style_decls(el.get("style") or "")
        if prop in inline:
            return inline[prop]
        value = None
        for tag, cls, decls in self.rules:
            if prop in decls and _css_matches(el, tag, cls):
                value = decls[prop]
        if value is not None:
            return value
        return el.get(prop)

    def computed(self, el: Optional[ET.Element], prop: str) -> Optional[str]:
        while el is not None:
            value = self.own(el, prop)
            if value is not None and value != "inherit":
                return value
            el = self.parents.get(el)
        return None

    def font_size(self, el: Optional[ET.Element]) -> float:
        chain: List[ET.Element] = []
        while el is not None:
            chain.append(el)
            el = self.parents.get(el)
        size = DEFAULT_TEXT_SIZE
        for node in reversed(chain):
            value = self.own(node, "font-size")
            if value is not None:
                parsed = _length(value, size)
                if parsed is not None and parsed > 0:
                    size = parsed
        return size

    def transformed(self, el: ET.Element) -> bool:
        node: Optional[ET.Element] = el
        while node is not None and node in self.parents:
            if node.get("transform"):
                return True
            node = self.parents.get(node)
        return False

    def tag_rule_decls(self, el: ET.Element) -> Dict[str, str]:
        """Declarations from rules that select by ELEMENT name — those stop
        matching once <text> becomes <g>, so they are copied across."""
        decls: Dict[str, str] = {}
        for tag, cls, rule in self.rules:
            if tag and _css_matches(el, tag, cls):
                decls.update(rule)
        return decls


def _carry_attributes(el: ET.Element, styler: _TextStyler) -> Dict[str, str]:
    """Attributes the replacement element keeps: everything that is not text
    layout, plus the paint an element-name CSS rule used to supply."""
    carried: Dict[str, str] = {}
    for key, value in el.attrib.items():
        if key in _TEXT_LAYOUT_PROPS:
            continue
        if key == "style":
            kept = {k: v for k, v in _style_decls(value).items()
                    if k not in _TEXT_LAYOUT_PROPS}
            if kept:
                carried["style"] = ";".join(f"{k}:{v}" for k, v in kept.items())
            continue
        carried[key] = value
    for key, value in styler.tag_rule_decls(el).items():
        if key not in _TEXT_LAYOUT_PROPS and key not in carried:
            carried[key] = value
    return carried


def _collapse_ws(text: Optional[str]) -> str:
    return re.sub(r" {2,}", " ", re.sub(r"[\t\r\n]", " ", text or ""))


def svg_text_to_paths(svg_text: str, mode: str = "paths",
                      default_family: str = DEFAULT_FONT_FAMILY,
                      frame_width: float = SVG_WIDTH) -> TextToPathsResult:
    """Convert (mode `paths`), strip (`forbid`), or leave (`keep`) every
    <text> in a SANITIZED banner. Returns the re-serialized SVG plus counts.

    paths without bundled fonts degrades to forbid, with a note: a banner
    without its headline is still a banner, a banner in a fallback font is a
    coin flip — which is the defect this step exists to remove."""
    result = TextToPathsResult(svg=svg_text)
    if mode == "keep":
        return result
    if mode == "paths" and not fonts_available():
        result.notes.append("bundled fonts not found — <text> stripped instead of converted")
        mode = "forbid"
    root = ET.fromstring(svg_text)
    styler = _TextStyler(root)
    texts = [el for el in root.iter() if _localname(el.tag) == "text"]
    if not texts:
        return result
    for text_el in texts:
        parent = styler.parents.get(text_el)
        if parent is None:
            continue
        index = list(parent).index(text_el)
        replacement = None
        if mode == "paths":
            replacement = _convert_text(text_el, styler, default_family, frame_width, result)
        if replacement is None:
            result.stripped += 1
        else:
            result.converted += 1
            replacement.tail = text_el.tail
            parent.insert(index, replacement)
        if replacement is None and text_el.tail:
            # Keep surrounding whitespace in the right place.
            if index > 0:
                prev = parent[index - 1]
                prev.tail = (prev.tail or "") + text_el.tail
            else:
                parent.text = (parent.text or "") + text_el.tail
        parent.remove(text_el)
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    result.svg = ET.tostring(root, encoding="unicode")
    if result.converted:
        result.notes.append(f"converted {result.converted} <text> to paths")
    if result.stripped:
        result.notes.append(f"stripped {result.stripped} <text>")
    if result.fitted:
        result.notes.append(f"scaled {result.fitted} overlong line(s) to fit the frame")
    if result.missing_glyphs:
        result.notes.append(f"{result.missing_glyphs} character(s) had no glyph in the bundled font")
    return result


def _convert_text(text_el: ET.Element, styler: _TextStyler, default_family: str,
                  frame_width: float, result: TextToPathsResult) -> Optional[ET.Element]:
    def font_for(el: ET.Element) -> Tuple[str, TrueTypeFont]:
        family = resolve_font_family(styler.computed(el, "font-family") or "",
                                     styler.computed(el, "font-weight") or "",
                                     default_family)
        font = load_bundled_font(family)
        if font is None:
            raise ValueError(f"bundled font {family} unavailable")
        return family, font

    size0 = styler.font_size(text_el)
    x0 = (_first_number(text_el.get("x")) or 0.0) + (_first_number(text_el.get("dx")) or 0.0)
    y0 = (_first_number(text_el.get("y")) or 0.0) + (_length(text_el.get("dy") or "", size0) or 0.0)
    chunks: List[Dict[str, Any]] = []

    def anchor_of(el: ET.Element) -> str:
        value = (styler.computed(el, "text-anchor") or "start").strip().lower()
        return value if value in ("start", "middle", "end") else "start"

    def start_chunk(x: float, y: float, el: ET.Element) -> None:
        chunks.append({"x": x, "y": y, "anchor": anchor_of(el), "runs": []})

    def chunk_end(chunk: Dict[str, Any]) -> float:
        width = 0.0
        for run in chunk["runs"]:
            _fam, font = font_for(run["el"])
            width += text_advance(font, run["text"], styler.font_size(run["el"]))
        return chunk["x"] + width

    def add_run(owner: ET.Element, raw: Optional[str]) -> None:
        text = _collapse_ws(raw)
        if text:
            chunks[-1]["runs"].append({"el": owner, "text": text})

    def walk(el: ET.Element) -> None:
        add_run(el, el.text)
        for child in list(el):
            tag = _localname(child.tag)
            if tag == "tspan":
                size = styler.font_size(child)
                cx, cy = child.get("x"), child.get("y")
                dx = _first_number(child.get("dx")) or 0.0
                dy = _length(child.get("dy") or "", size) or 0.0
                current = chunks[-1]
                if cx is not None or cy is not None or dx or dy:
                    nx = _first_number(cx) if cx is not None else chunk_end(current)
                    ny = _first_number(cy) if cy is not None else current["y"]
                    start_chunk((nx or 0.0) + dx, (ny or 0.0) + dy, child)
                walk(child)
            elif tag == "textPath":
                result.notes.append("<textPath> is not supported — its text was dropped")
            add_run(el, child.tail)

    start_chunk(x0, y0, text_el)
    walk(text_el)

    group = ET.Element(f"{{{SVG_NS}}}g", _carry_attributes(text_el, styler))
    label_parts: List[str] = []
    fittable = not styler.transformed(text_el)
    for chunk in chunks:
        runs = chunk["runs"]
        if not runs:
            continue
        runs[0]["text"] = runs[0]["text"].lstrip(" ")
        runs[-1]["text"] = runs[-1]["text"].rstrip(" ")
        measured = []
        total = 0.0
        for run in runs:
            _fam, font = font_for(run["el"])
            size = styler.font_size(run["el"])
            spacing = _length(styler.computed(run["el"], "letter-spacing") or "", size) or 0.0
            width = text_advance(font, run["text"], size, spacing)
            measured.append((run, font, size, spacing))
            total += width
        if total <= 0:
            continue
        factor = 1.0
        limit = frame_width * TEXT_FIT_FRACTION
        if fittable and total > limit:
            factor = limit / total
            result.fitted += 1
        span = total * factor
        start = chunk["x"] - span * {"start": 0.0, "middle": 0.5, "end": 1.0}[chunk["anchor"]]
        if fittable and (start < 0 or start + span > frame_width):
            # Only text that actually leaves the frame is moved — and then
            # inside the same margin the fit uses.
            margin = (frame_width - limit) / 2.0
            start = min(max(start, margin), frame_width - margin - span)
        pen = start
        for run, font, size, spacing in measured:
            if not run["text"]:
                continue
            scaled = size * factor
            shift = baseline_shift(font, styler.computed(run["el"], "dominant-baseline") or "", scaled)
            d, advance, missing = glyph_run_path(font, run["text"], pen, chunk["y"] + shift,
                                                 scaled, spacing * factor)
            pen += advance
            result.missing_glyphs += missing
            label_parts.append(run["text"])
            if not d:
                continue
            attrs = {} if run["el"] is text_el else _carry_attributes(run["el"], styler)
            path = ET.SubElement(group, f"{{{SVG_NS}}}path", attrs)
            path.set("d", d)
    if not len(group):
        return None
    group.set("aria-label", " ".join(part.strip() for part in label_parts if part.strip()))
    return group


_PRECISION_ATTR = re.compile(r'(\s(?:d|points)=")([^"]*)(")')
_LONG_DECIMAL = re.compile(r"-?\d+\.\d{3,}")


def round_svg_precision(svg_text: str) -> str:
    """Round path/points numbers carrying 3+ decimals to 2. Sub-pixel precision
    is invisible at banner scale and is the cheapest size win there is — a
    mechanical fix that should never cost a model round."""
    def fix_number(match: "re.Match[str]") -> str:
        return _fmt2(float(match.group(0)))

    def fix_attr(match: "re.Match[str]") -> str:
        return match.group(1) + _LONG_DECIMAL.sub(fix_number, match.group(2)) + match.group(3)

    return _PRECISION_ATTR.sub(fix_attr, svg_text)


# =============================================================================
# Anthropic client (Claude Code OAuth → API key → claude CLI)
# =============================================================================

# List prices, USD per million tokens (input, output), by model-id prefix.
# Used only to SHADOW-price the illustration loop for its budget cap and its
# telemetry: under a Claude Code OAuth token nothing is invoiced per token, but
# the cap still bounds how much work one run may do. Unknown models are priced
# at the Sonnet rate rather than as free, so a cap never silently stops binding.
CLAUDE_PRICES_PER_MTOK: List[Tuple[str, float, float]] = [
    ("claude-opus-5-5", 4.00, 20.00),
    ("claude-sonnet-5-5", 2.00, 10.00),
    ("claude-haiku-5-5", 0.10, 0.50),
    ("claude-opus", 5.00, 25.00),
    ("claude-sonnet", 2.00, 10.00),
    ("claude-haiku", 1.00, 5.00),
]
CACHE_READ_PRICE_FACTOR = 0.1


def usage_cost_usd(record: Dict[str, Any]) -> float:
    model = str(record.get("model") or "")
    rate_in, rate_out = 2.00, 10.00
    for prefix, price_in, price_out in CLAUDE_PRICES_PER_MTOK:
        if model.startswith(prefix):
            rate_in, rate_out = price_in, price_out
            break
    billed_in = (int(record.get("input_tokens") or 0)
                 + int(record.get("cache_creation_input_tokens") or 0)
                 + CACHE_READ_PRICE_FACTOR * int(record.get("cache_read_input_tokens") or 0))
    out = int(record.get("output_tokens") or 0)
    return round((billed_in * rate_in + out * rate_out) / 1_000_000, 6)


def _output_config(effort: str, json_schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    if effort:
        config["effort"] = effort
    if json_schema:
        config["format"] = {"type": "json_schema", "schema": json_schema}
    return config


class ClaudeRefusal(Exception):
    def __init__(self, category: Optional[str]):
        self.category = category
        super().__init__(f"request declined (category: {category or 'unspecified'})")


class ClaudeTruncated(Exception):
    pass


class AnthropicClient:
    """Minimal Messages-API client honoring the repo's credential conventions.

    Modes (first match wins — mirrors templates/deploy/chat-proxy/worker.js):
      oauth    CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_AUTH_TOKEN → Bearer +
               `anthropic-beta: oauth-2025-04-20` + Claude Code first system block
      api_key  ANTHROPIC_API_KEY → x-api-key header
      cli      `claude -p` headless (rides the local Claude Code login)
    """

    def __init__(self, env: Optional[Dict[str, str]] = None):
        self.env = dict(env if env is not None else os.environ)
        self.mode: Optional[str] = None
        self.token: Optional[str] = None
        if self.env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            self.mode, self.token = "oauth", self.env["CLAUDE_CODE_OAUTH_TOKEN"]
        elif self.env.get("ANTHROPIC_AUTH_TOKEN"):
            self.mode, self.token = "oauth", self.env["ANTHROPIC_AUTH_TOKEN"]
        elif self.env.get("ANTHROPIC_API_KEY"):
            self.mode, self.token = "api_key", self.env["ANTHROPIC_API_KEY"]
        elif shutil.which("claude"):
            self.mode = "cli"

    def available(self) -> bool:
        return self.mode is not None

    def describe(self) -> str:
        return {
            "oauth": "Claude Code OAuth token (Bearer)",
            "api_key": "Anthropic API key",
            "cli": "claude CLI (local Claude Code login)",
            None: "none",
        }[self.mode]

    def headers(self) -> Dict[str, str]:
        if self.mode == "oauth":
            return {
                "Authorization": f"Bearer {self.token}",
                "anthropic-version": ANTHROPIC_VERSION,
                "anthropic-beta": OAUTH_BETA,
            }
        if self.mode == "api_key":
            return {
                "x-api-key": self.token or "",
                "anthropic-version": ANTHROPIC_VERSION,
            }
        raise RuntimeError(f"no API headers for mode {self.mode}")

    def complete(
        self,
        system_text: str,
        user_text: str,
        model: str = DEFAULT_CLAUDE_MODEL,
        max_tokens: int = CLAUDE_MAX_TOKENS,
        effort: str = "",
        json_schema: Optional[Dict[str, Any]] = None,
        usage: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """One Messages-API turn (or CLI run); returns concatenated text blocks.

        `json_schema` asks for structured output (`output_config.format`) —
        callers still parse defensively, because the CLI mode and the
        unsupported-parameter retry both drop it. `usage`, when given, gets
        one record appended per billed call (see _record_usage).

        Raises ClaudeRefusal / ClaudeTruncated / HttpStatusError / RuntimeError.
        """
        if self.mode == "cli":
            return self._complete_cli(system_text, user_text, model)
        if self.mode is None:
            raise RuntimeError("no Anthropic credential configured")

        # The Claude Code identity block is REQUIRED as the first system block
        # for OAuth tokens (worker.js recipe) and intentionally omitted for
        # plain API keys, matching the chat proxy's per-mode behavior.
        system_blocks = [{"type": "text", "text": system_text}]
        if self.mode == "oauth":
            system_blocks.insert(0, {"type": "text", "text": CLAUDE_CODE_SYSTEM_PROMPT})

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "thinking": {"type": "adaptive"},
            "system": system_blocks,
            "messages": [{"role": "user", "content": user_text}],
        }
        output_config = _output_config(effort, json_schema)
        if output_config:
            payload["output_config"] = output_config

        def call(body: Dict[str, Any]) -> dict:
            return with_retries(
                lambda: http_json(ANTHROPIC_API_URL, body, self.headers(), timeout=900),
                "Anthropic API",
            )

        try:
            data = call(payload)
        except HttpStatusError as exc:
            message = exc.message().lower() if exc.status == 400 else ""
            if exc.status == 400 and ("output_config" in message or "effort" in message):
                debug("Retrying without output_config parameter")
                payload.pop("output_config", None)
                data = call(payload)
            elif exc.status == 400 and "thinking" in message:
                debug("Retrying without thinking parameter")
                payload.pop("thinking", None)
                data = call(payload)
            elif exc.status == 401 and self.mode == "oauth":
                raise RuntimeError(
                    "Anthropic rejected the OAuth token (401). It may be expired "
                    "— mint a fresh one with `claude setup-token`, or use "
                    "ANTHROPIC_API_KEY instead."
                ) from None
            else:
                raise

        self._record_usage(data, model, usage)
        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            details = data.get("stop_details") or {}
            raise ClaudeRefusal(details.get("category") if isinstance(details, dict) else None)

        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if stop_reason == "max_tokens":
            raise ClaudeTruncated(text)
        return text

    def complete_vision(
        self,
        system_text: str,
        user_text: str,
        image_path: Any,
        model: str = DEFAULT_CLAUDE_MODEL,
        max_tokens: int = 2048,
        effort: str = "",
        json_schema: Optional[Dict[str, Any]] = None,
        usage: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """One vision turn over local PNG(s) (review/critique stages).

        `image_path` is one Path or a list of Paths, sent in order ahead of the
        text. CLI mode passes the file paths and lets `claude -p` read them;
        API modes embed base64."""
        paths = list(image_path) if isinstance(image_path, (list, tuple)) else [image_path]
        if self.mode == "cli":
            listing = ", then ".join(str(Path(p).resolve()) for p in paths)
            noun = "image file" if len(paths) == 1 else "image files, in order"
            prompt = (
                f"{system_text}\n\n---\n\nFirst use the Read tool to view the "
                f"{noun} at {listing} — then respond.\n\n{user_text}"
            )
            return self._run_cli(prompt, model, allowed_tools="Read")
        if self.mode is None:
            raise RuntimeError("no Anthropic credential configured")

        system_blocks = [{"type": "text", "text": system_text}]
        if self.mode == "oauth":
            system_blocks.insert(0, {"type": "text", "text": CLAUDE_CODE_SYSTEM_PROMPT})
        content: List[Dict[str, Any]] = []
        for path in paths:
            image_bytes = Path(path).read_bytes()
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": image_media_type(image_bytes),
                "data": base64.b64encode(image_bytes).decode("ascii"),
            }})
        content.append({"type": "text", "text": user_text})
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "thinking": {"type": "adaptive"},
            "system": system_blocks,
            "messages": [{"role": "user", "content": content}],
        }
        output_config = _output_config(effort, json_schema)
        if output_config:
            payload["output_config"] = output_config

        def call(body: Dict[str, Any]) -> dict:
            return with_retries(
                lambda: http_json(ANTHROPIC_API_URL, body, self.headers(), timeout=900),
                "Anthropic API (review)",
            )

        try:
            data = call(payload)
        except HttpStatusError as exc:
            message = exc.message().lower() if exc.status == 400 else ""
            if exc.status == 400 and ("output_config" in message or "effort" in message):
                debug("Retrying review without output_config parameter")
                payload.pop("output_config", None)
                data = call(payload)
            else:
                raise
        self._record_usage(data, model, usage)
        if data.get("stop_reason") == "refusal":
            details = data.get("stop_details") or {}
            raise ClaudeRefusal(details.get("category") if isinstance(details, dict) else None)
        return "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )

    @staticmethod
    def _record_usage(data: Dict[str, Any], model: str,
                      sink: Optional[List[Dict[str, Any]]]) -> None:
        """Append this call's token usage (and its list-price cost) to `sink`.

        The CLI mode reports no usage, so a CLI run's records simply never
        appear — telemetry shows tokens as unknown rather than as zero."""
        if sink is None:
            return
        raw = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return
        record = {
            "model": model,
            "input_tokens": int(raw.get("input_tokens") or 0),
            "output_tokens": int(raw.get("output_tokens") or 0),
            "cache_read_input_tokens": int(raw.get("cache_read_input_tokens") or 0),
            "cache_creation_input_tokens": int(raw.get("cache_creation_input_tokens") or 0),
        }
        record["cost_usd"] = usage_cost_usd(record)
        sink.append(record)

    def _complete_cli(self, system_text: str, user_text: str, model: str) -> str:
        return self._run_cli(f"{system_text}\n\n---\n\n{user_text}", model)

    def _run_cli(self, prompt: str, model: str,
                 allowed_tools: Optional[str] = None) -> str:
        cmd = ["claude", "-p", "--model", model, "--output-format", "text"]
        if allowed_tools:
            cmd += ["--allowedTools", allowed_tools]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"claude CLI failed: {exc}") from None
        if proc.returncode != 0 or not proc.stdout.strip():
            tail = (proc.stderr or "").strip()[-300:]
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: {tail or 'no output'}"
            )
        return proc.stdout


CLAUDE_CREDENTIAL_HINT = (
    "Claude orchestration (article analysis + image review) needs any ONE of:\n"
    "  1. CLAUDE_CODE_OAUTH_TOKEN   — run `claude setup-token` (Claude Pro/Max)\n"
    "  2. ANTHROPIC_AUTH_TOKEN      — short-lived Bearer (e.g. `ant auth print-credentials`)\n"
    "  3. ANTHROPIC_API_KEY         — key from console.anthropic.com\n"
    "  4. the `claude` CLI installed and logged in (used automatically)\n"
    "Falling back to the template prompt and skipping review (or pass "
    "--prompt-engine template --review none to silence this)."
)


# =============================================================================
# Illustration loop (provider: claude)
# =============================================================================
#   [1] PLAN      Claude → JSON scene graph (palette tokens, focal point, layers)
#   [2] AUTHOR    Claude → SVG from the plan + style card (headline as <text>)
#   [3] SHAPE     text→paths · sanitize · round · strict lint   (no model)
#                 └ lint fails → one targeted fix round, then the `local` art
#   [4] LOOK      rasterize at 1536px and 120px                 (no model)
#   [5] CRITIQUE  Claude vision → {works, fails, next_change, overall,
#                 thumbnail_holds}
#                 └ below claude_min_score (or thumbnail fails) → [2'] a
#                   targeted EDIT of the current SVG, up to claude_rounds
#   [6] COMMIT    best-of by score · front matter · one telemetry record
#
# Steps 3, 4 and 6 are deterministic. `claude_rounds: 0` is the rollback: one
# authored draft, shaped and linted, never rendered or reviewed.

STYLE_CARDS_DIR = Path(__file__).resolve().parents[2] / "tools" / "svg" / "library" / "styles"
# Card sections the AUTHOR follows / the CRITIC grades against. The rest
# (seed recipes, library references) describe the dev toolkit, not the look.
STYLE_CARD_AUTHOR_SECTIONS = ("Signature", "Geometry & grid", "Palette", "Do / Don't")
STYLE_CARD_CRITIC_SECTIONS = ("Signature", "Critique add-ons")
PALETTE_ROLES: List[str] = ["bg", "shadow", "low_mid", "mid", "accent", "highlight"]
PLAN_LAYER_ROLES: List[str] = ["background", "midground", "subject", "accent", "text", "veil"]
HEADLINE_PLACEMENTS: List[str] = ["top", "bottom", "left", "right", "none"]
MAX_SVG_CHARS = 400_000          # refuse pathological replies before parsing
SVG_AUTHOR_MAX_TOKENS = 32000    # an authored banner + adaptive thinking
THUMBNAIL_WIDTH = 120            # card size — what the thumbnail test looks at
TEXT_TO_PATHS_HEADROOM_KB = 80   # converted glyphs grow a titled banner

# JSON Schemas (structured outputs: every object closed, no numeric bounds —
# the validators below clamp). svg/plan.schema.json and
# svg/critique.schema.json are generated from these; a test pins them equal,
# and .claude/workflows/svg-forge.js carries the same CRITIQUE shape.
PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "focal_point", "palette", "layers", "symmetry_break",
                 "headline_placement", "avoid"],
    "properties": {
        "subject": {"type": "string",
                    "description": "one sentence: the concrete scene the banner shows"},
        "focal_point": {
            "type": "object", "additionalProperties": False,
            "required": ["x", "y", "element"],
            "properties": {
                "x": {"type": "number", "description": "0-1 share of the width"},
                "y": {"type": "number", "description": "0-1 share of the height"},
                "element": {"type": "string", "description": "what sits there"},
            },
        },
        "palette": {
            "type": "object", "additionalProperties": False,
            "required": list(PALETTE_ROLES),
            "properties": {role: {"type": "string", "description": "#rrggbb"}
                           for role in PALETTE_ROLES},
        },
        "layers": {
            "type": "array",
            "description": "3-4 layers, back to front",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["role", "description", "tokens"],
                "properties": {
                    "role": {"type": "string", "enum": list(PLAN_LAYER_ROLES)},
                    "description": {"type": "string"},
                    "tokens": {"type": "array",
                               "items": {"type": "string", "enum": list(PALETTE_ROLES)}},
                },
            },
        },
        "symmetry_break": {"type": "string",
                           "description": "the one deliberate asymmetry, which is the subject"},
        "headline_placement": {"type": "string", "enum": list(HEADLINE_PLACEMENTS)},
        "avoid": {"type": "array", "items": {"type": "string"}},
    },
}

CRITIQUE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["works", "fails", "next_change", "overall", "thumbnail_holds"],
    "properties": {
        "works": {"type": "string"},
        "fails": {"type": "array", "items": {"type": "string"}},
        "next_change": {"type": "string", "description": "exactly one actionable edit"},
        "overall": {"type": "number",
                    "description": "0-10, be stingy: 8+ means shippable as-is"},
        "thumbnail_holds": {"type": "boolean",
                            "description": "silhouette still reads at 120px"},
    },
}

PLANNER_SYSTEM = """You are the art director planning ONE preview banner (1536x1024) for an
article. You do not draw; you decide. Return a scene graph as JSON:
- subject: the article's actual subject as one concrete scene — specific
  objects and actions, never a generic technology collage.
- focal_point: where the eye lands (x, y as 0-1 shares) and what is there.
- palette: six hex tokens by role. When fixed tokens are given, return
  exactly those.
- layers: 3-4 layers back to front, each naming the palette roles it uses.
  One layer's role is "text" unless headline_placement is "none".
- symmetry_break: the single deliberate asymmetry — it should BE the subject.
- headline_placement: where the title block goes, keeping the focal point
  clear of it.
- avoid: specific failure modes for this subject (clutter, tiny detail that
  dies at thumbnail size, lettering besides the headline...).
The banner must read as a 120px-wide card thumbnail as well as full size:
plan big silhouettes, strong value contrast and few elements."""

AUTHOR_SYSTEM = ("You are an SVG illustrator. You reply with ONE complete, standalone SVG "
                 "document and nothing else — no prose, no code fence.")

CRITIC_SYSTEM = """You are a stingy art director critiquing a preview banner for an article.
You are shown the banner twice: IMAGE 1 at full size (1536px wide) and
IMAGE 2 at card-thumbnail size (120px wide), exactly as a reader meets it in
a list of posts. Judge:
1. Subject — does it depict THIS article's subject, specifically?
2. Style — does it obey the style card's signature rules?
3. Craft — composition, value structure, focal point; any overlap, clipping,
   broken or off-grid shapes, garbled or mis-wrapped lettering.
4. Thumbnail — at IMAGE 2, do the main silhouette and the headline (if any)
   still read? Fine detail that turns to mush there is a failure.
Score `overall` from 0 to 10; 8+ means shippable as-is, 7 is acceptable,
below that something specific is wrong. `next_change` is exactly ONE
concrete edit to the SVG that would raise the score most. Reply with JSON
only."""

# Literal reply shapes, quoted in the prompts. Structured outputs enforce the
# schemas on the API path; the `claude -p` CLI path has no such parameter, and
# without the shape spelled out a CLI planner answers in its own keys (seen in
# the first live run: "no usable scene graph").
PLAN_SKELETON = json.dumps({
    "subject": "...", "focal_point": {"x": 0.6, "y": 0.4, "element": "..."},
    "palette": {role: "#rrggbb" for role in PALETTE_ROLES},
    "layers": [{"role": "background", "description": "...", "tokens": ["bg", "shadow"]}],
    "symmetry_break": "...", "headline_placement": "bottom", "avoid": ["..."],
})
CRITIQUE_SKELETON = json.dumps({
    "works": "...", "fails": ["..."], "next_change": "...", "overall": 6.5,
    "thumbnail_holds": False,
})

EDITOR_SYSTEM = ("You are an SVG illustrator revising your own banner after an art "
                 "director's critique. You reply with the COMPLETE revised SVG document "
                 "and nothing else — no prose, no code fence.")


@dataclass
class StyleCard:
    name: str
    title: str
    sections: Dict[str, str]

    def text_for(self, wanted: Tuple[str, ...]) -> str:
        blocks = [f"## {name}\n{self.sections[name].strip()}"
                  for name in wanted if self.sections.get(name, "").strip()]
        return "\n\n".join(blocks)

    @property
    def font_family(self) -> str:
        return CARD_FONTS.get(self.name, DEFAULT_FONT_FAMILY)


def load_style_card(name: str, project_root: Optional[Path] = None) -> Optional[StyleCard]:
    """Resolve a style card by name (bundled cards) or by path (site-local)."""
    name = str(name or "").strip()
    if not name:
        return None
    candidates: List[Path] = []
    if name.endswith(".md") or "/" in name:
        candidates.append(Path(name) if Path(name).is_absolute()
                          else (project_root or Path.cwd()) / name)
    candidates.append(STYLE_CARDS_DIR / f"{name}.md")
    for path in candidates:
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            return parse_style_card(path.stem, text)
    warn(f"style card '{name}' not found — using the prose style only")
    return None


def parse_style_card(name: str, text: str) -> StyleCard:
    title_match = re.search(r"^#\s+(.+)$", text, re.M)
    sections: Dict[str, str] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return StyleCard(name=name, title=title_match.group(1).strip() if title_match else name,
                     sections=sections)


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(high, max(low, number))


def validate_plan(data: Any, palette: List[str]) -> Optional[Dict[str, Any]]:
    """Normalize a planner reply, or None when it is not a usable plan.
    Fixed palette tokens (policy) always override whatever the model chose."""
    if not isinstance(data, dict) or not str(data.get("subject") or "").strip():
        return None
    focal = data.get("focal_point") if isinstance(data.get("focal_point"), dict) else {}
    plan_palette: Dict[str, str] = {}
    raw_palette = data.get("palette") if isinstance(data.get("palette"), dict) else {}
    for i, role in enumerate(PALETTE_ROLES):
        if len(palette) == len(PALETTE_ROLES):
            plan_palette[role] = palette[i]
        else:
            value = str(raw_palette.get(role) or "").strip().lower()
            plan_palette[role] = value if _HEX_TOKEN.match(value) else ""
    layers = []
    for layer in data.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        role = str(layer.get("role") or "").strip().lower()
        if role not in PLAN_LAYER_ROLES:
            continue
        tokens = [t for t in (layer.get("tokens") or []) if t in PALETTE_ROLES]
        layers.append({"role": role, "description": str(layer.get("description") or "").strip(),
                       "tokens": tokens})
    if not layers:
        return None
    placement = str(data.get("headline_placement") or "bottom").strip().lower()
    return {
        "subject": str(data["subject"]).strip(),
        "focal_point": {"x": _clamp(focal.get("x"), 0.0, 1.0, 0.5),
                        "y": _clamp(focal.get("y"), 0.0, 1.0, 0.5),
                        "element": str(focal.get("element") or "").strip()},
        "palette": plan_palette,
        "layers": layers[:6],
        "symmetry_break": str(data.get("symmetry_break") or "").strip(),
        "headline_placement": placement if placement in HEADLINE_PLACEMENTS else "bottom",
        "avoid": [str(a).strip() for a in (data.get("avoid") or []) if str(a).strip()][:8],
    }


def validate_critique(data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict) or "overall" not in data:
        return None
    fails = data.get("fails")
    holds = data.get("thumbnail_holds")
    return {
        "works": str(data.get("works") or "").strip(),
        "fails": [str(f).strip() for f in fails if str(f).strip()] if isinstance(fails, list) else [],
        "next_change": str(data.get("next_change") or "").strip(),
        "overall": round(_clamp(data.get("overall"), 0.0, 10.0, 0.0), 2),
        "thumbnail_holds": holds if isinstance(holds, bool) else _setting_bool(holds),
    }


def critique_passes(critique: Optional[Dict[str, Any]], settings: Settings) -> bool:
    if not critique:
        return False
    if critique["overall"] < settings.claude_min_score:
        return False
    return critique["thumbnail_holds"] or not settings.claude_require_thumbnail


def critique_rank(critique: Optional[Dict[str, Any]]) -> float:
    """Best-of ordering: the score, with a half-point for a thumbnail that
    reads (an unreviewed draft ranks below any reviewed one)."""
    if not critique:
        return -1.0
    return critique["overall"] + (0.5 if critique["thumbnail_holds"] else 0.0)


@dataclass
class Headline:
    lines: List[str]
    size: float
    family: str
    css_family: str
    anchor: str
    x: float
    baselines: List[float]

    def brief(self) -> str:
        rows = "\n".join(f'  {i + 1}. "{line}" — baseline y={_fmt2(y)}'
                         for i, (line, y) in enumerate(zip(self.lines, self.baselines)))
        return (f"HEADLINE (the article title, pre-broken at word boundaries — use these "
                f"lines verbatim, one <text> per line or one <text> with <tspan>s):\n"
                f"  font-family=\"{self.css_family}\" font-size=\"{_fmt2(self.size)}\" "
                f"text-anchor=\"{self.anchor}\" x=\"{_fmt2(self.x)}\"\n{rows}\n"
                "Give it a backing plate or clear field so it reads at thumbnail size. "
                "No other lettering anywhere in the banner.")


HEADLINE_SIZES: Dict[str, Tuple[float, float]] = {
    "press-start-2p": (64.0, 24.0),
    "inter": (96.0, 40.0),
}
HEADLINE_LEADING = 1.25
HEADLINE_MAX_HEIGHT = 0.30   # share of the banner height the title block may take
HEADLINE_CSS_FAMILY: Dict[str, str] = {"press-start-2p": "Press Start 2P", "inter": "Inter"}


def plan_headline(title: str, placement: str, family: str) -> Optional[Headline]:
    """Deterministic headline layout for the author: lines, size, baselines.
    None when the placement is `none` or the bundled fonts are absent."""
    if placement == "none" or not str(title or "").strip():
        return None
    base = "press-start-2p" if family == "press-start-2p" else "inter"
    font = load_bundled_font(base if base == "press-start-2p" else "inter-bold")
    if font is None:
        return None
    max_size, min_size = HEADLINE_SIZES[base]
    side = placement in ("left", "right")
    width = SVG_WIDTH * (0.42 if side else 0.86)
    lines, size = fit_headline(font, title, width, 3, max_size, min_size,
                               max_height=SVG_HEIGHT * (0.5 if side else HEADLINE_MAX_HEIGHT),
                               leading=HEADLINE_LEADING)
    leading = size * HEADLINE_LEADING
    block = leading * (len(lines) - 1)
    if placement == "top":
        first = SVG_HEIGHT * 0.08 + size
    elif placement == "bottom":
        first = SVG_HEIGHT * 0.92 - block
    else:
        first = SVG_HEIGHT / 2.0 - block / 2.0 + size * 0.35
    if placement == "left":
        anchor, x = "start", SVG_WIDTH * 0.06
    elif placement == "right":
        anchor, x = "end", SVG_WIDTH * 0.94
    else:
        anchor, x = "middle", SVG_WIDTH / 2.0
    return Headline(lines=lines, size=size, family=base, css_family=HEADLINE_CSS_FAMILY[base],
                    anchor=anchor, x=x, baselines=[first + leading * i for i in range(len(lines))])


def _body_excerpt(text: str, limit: int = 1500) -> str:
    body = re.sub(r"```.*?```", "", text or "", flags=re.S)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:limit]


def extract_svg_document(text: str) -> str:
    """The <svg>…</svg> in a model reply, fenced or bare; '' when absent."""
    fenced = re.search(r"```(?:svg|xml)?\s*\n(.*?)```", str(text or ""), re.S)
    if fenced and "<svg" in fenced.group(1):
        text = fenced.group(1)
    match = re.search(r"<svg\b.*</svg\s*>", str(text or ""), re.S | re.I)
    return match.group(0) if match else ""


def ensure_accessible(svg: str, title: str) -> str:
    """Guarantee role="img" + a first-child <title>. Attribute-aware: a naive
    substring test would inject a duplicate role and break the parse."""
    root_tag = svg.split(">", 1)[0]
    if not re.search(r"""\brole\s*=\s*["']img["']""", root_tag):
        svg = svg.replace("<svg", '<svg role="img"', 1)
    if not re.search(r"<title[\s>]", svg):
        safe = (title or "banner").replace("&", "&amp;").replace("<", "&lt;")
        head, sep, tail = svg.partition(">")
        svg = f"{head}{sep}<title>{safe}</title>{tail}"
    return svg


@dataclass
class ShapedSvg:
    svg: str
    lint: SvgLintReport
    text: TextToPathsResult
    sanitizer_notes: List[str]


def shape_svg(raw: str, title: str, settings: Settings, default_family: str) -> ShapedSvg:
    """[3] SHAPE — deterministic: accessibility → sanitize → text→paths →
    precision → strict lint. Raises SvgError when the markup is unusable."""
    if not raw:
        raise SvgError("reply contained no SVG markup")
    if len(raw) > MAX_SVG_CHARS:
        raise SvgError(f"SVG reply is {len(raw)} characters (limit {MAX_SVG_CHARS})")
    clean, notes = sanitize_svg(ensure_accessible(raw, title))
    text = svg_text_to_paths(clean, settings.svg_text, default_family)
    svg = round_svg_precision(text.svg)
    report = lint_svg(svg.encode("utf-8"), "banner", max_kb=settings.svg_max_kb, strict=True)
    if settings.svg_text == "keep":
        report.warnings = [w for w in report.warnings if w != LINT_TEXT_WARNING]
    return ShapedSvg(svg=svg, lint=report, text=text, sanitizer_notes=notes)


def look_svg(svg: str, workdir: Path, stem: str, settings: Settings,
             project_root: Path) -> Optional[Tuple[Path, Path, str]]:
    """[4] LOOK — render one draft at full and thumbnail size. None when no
    rasterizer is reachable (the loop then commits unreviewed)."""
    if settings.look_rasterizer == "none":
        return None
    svg_path = workdir / f"{stem}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    full, thumb = workdir / f"{stem}.png", workdir / f"{stem}-thumb.png"
    tool = rasterize_svg(svg_path, full, project_root, settings.look_rasterizer, SVG_WIDTH)
    if not tool:
        return None
    if not rasterize_svg(svg_path, thumb, project_root, tool, THUMBNAIL_WIDTH):
        return None
    return full, thumb, tool


@dataclass
class BudgetMeter:
    """Run-wide list-price spend of the loop, shared by every worker."""
    cap_usd: float = 0.0
    spent_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, records: List[Dict[str, Any]]) -> None:
        with self._lock:
            self.spent_usd += sum(float(r.get("cost_usd") or 0.0) for r in records)

    def exhausted(self) -> bool:
        with self._lock:
            return self.cap_usd > 0 and self.spent_usd >= self.cap_usd


class IllustrationLoop:
    """One banner's trip through the loop. Holds the per-banner usage so the
    telemetry record and the run budget see the same numbers."""

    def __init__(self, provider: "ClaudeSvgProvider", settings: Settings, ctx: "RunContext"):
        self.provider = provider
        self.settings = settings
        self.ctx = ctx
        self.article = ctx.article or {}
        self.client = ctx.claude()
        self.model = provider.authoring_model(settings)
        self.card = load_style_card(settings.style_card, ctx.project_root)
        self.family = self.card.font_family if self.card else DEFAULT_FONT_FAMILY
        self.usage: List[Dict[str, Any]] = []
        self.calls = 0
        self.meta: Dict[str, Any] = {
            "provider": "claude", "model": self.model,
            "style_card": self.card.name if self.card else None,
            "plan": False, "rounds_used": 0, "fix_round": False,
            "fallback": None, "critic": None, "rasterizer": None,
        }

    # -- model calls ----------------------------------------------------------
    def _call(self, fn, *args, **kwargs) -> str:
        before = len(self.usage)
        self.calls += 1
        try:
            return fn(*args, usage=self.usage, **kwargs)
        finally:
            self.ctx.budget.add(self.usage[before:])

    def _over_budget(self, stage: str) -> bool:
        if self.ctx.budget.exhausted():
            info(f"  ↳ loop budget (${self.settings.claude_budget_usd:g}) spent — skipping {stage}")
            self.meta.setdefault("budget_skipped", []).append(stage)
            return True
        return False

    def article_block(self) -> str:
        a = self.article
        return (f"ARTICLE\nTitle: {a.get('title', '')}\nSection: {a.get('section', '')}\n"
                f"Tags: {a.get('categories', '')}\nDescription: {a.get('description', '')}\n"
                f"Body excerpt:\n---\n{_body_excerpt(a.get('body', ''))}\n---")

    def style_block(self, prompt: str) -> str:
        s = self.settings
        parts = [f"ART DIRECTION\nStyle: {s.style}\nModifiers: {s.style_modifiers or '(none)'}"]
        if prompt and prompt.strip() and prompt.strip() != s.style:
            parts.append(f"Brief: {prompt.strip()}")
        if len(s.palette) == len(PALETTE_ROLES):
            pairs = ", ".join(f"{role}={tok}" for role, tok in zip(PALETTE_ROLES, s.palette))
            parts.append(f"FIXED PALETTE (use these tokens, no others besides #000 for a "
                         f"scanline veil): {pairs}")
        if self.card:
            parts.append(
                f"STYLE CARD — {self.card.title}. Its rules are constraints, not suggestions. "
                "It was written for the engine's generator toolkit: where it mentions scripts, "
                "pixelkit or seeds, reproduce the LOOK those produce by hand.\n"
                + self.card.text_for(STYLE_CARD_AUTHOR_SECTIONS))
        return "\n\n".join(parts)

    # -- stages ---------------------------------------------------------------
    def plan(self, prompt: str) -> Optional[Dict[str, Any]]:
        if not self.settings.claude_plan or self._over_budget("plan"):
            return None
        fixed = (", ".join(self.settings.palette)
                 if len(self.settings.palette) == len(PALETTE_ROLES) else "none — choose")
        request = (f"{self.article_block()}\n\n{self.style_block(prompt)}\n\n"
                   f"Fixed palette tokens: {fixed}\n\nReply with ONLY a JSON object of "
                   f"exactly this shape (layer roles: {', '.join(PLAN_LAYER_ROLES)}; "
                   f"headline_placement: {', '.join(HEADLINE_PLACEMENTS)}):\n{PLAN_SKELETON}")
        try:
            reply = self._call(self.client.complete, PLANNER_SYSTEM, request, model=self.model,
                               max_tokens=4096, effort=self.settings.claude_effort,
                               json_schema=PLAN_SCHEMA)
        except Exception as exc:  # noqa: BLE001 - planning is an enhancement
            warn(f"  ↳ plan stage failed ({exc}); authoring without a plan")
            return None
        plan = validate_plan(_extract_json_object(reply or ""), self.settings.palette)
        if plan is None:
            warn("  ↳ plan stage returned no usable scene graph; authoring without a plan")
        self.meta["plan"] = plan is not None
        return plan

    def author(self, plan: Optional[Dict[str, Any]], prompt: str) -> str:
        s = self.settings
        placement = plan["headline_placement"] if plan else "bottom"
        headline = (plan_headline(self.article.get("title", ""), placement, self.family)
                    if s.svg_text != "forbid" else None)
        budget_kb = max(60, int(s.svg_max_kb - (TEXT_TO_PATHS_HEADROOM_KB if headline else 0)))
        lettering = (headline.brief() if headline else
                     "No lettering of any kind — no <text>, no glyph paths.")
        request = (
            "Author the preview banner as a single SVG document.\n\n"
            "HARD REQUIREMENTS\n"
            f'- Root: <svg xmlns="{SVG_NS}" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" '
            f'width="{SVG_WIDTH}" height="{SVG_HEIGHT}" role="img">\n'
            "- A <title> as the FIRST child describing the image.\n"
            "- Vector shapes only: no <script>, <foreignObject>, <image>, external href, or "
            "data: payloads. Every url(#id) must point at an id defined in the file.\n"
            "- Fill the whole frame; no large empty regions.\n"
            f"- Coordinates rounded to at most 2 decimals; under {budget_kb} KB.\n"
            "- Readable as a 120px-wide card thumbnail: big silhouettes, strong value "
            "contrast, no detail that only works large.\n\n"
            f"{lettering}\n\n"
            + (f"PLAN (follow it)\n{json.dumps(plan, indent=1)}\n\n" if plan else "")
            + f"{self.style_block(prompt)}\n\n{self.article_block()}\n"
        )
        return self._call(self.client.complete, AUTHOR_SYSTEM, request, model=self.model,
                          max_tokens=SVG_AUTHOR_MAX_TOKENS, effort=s.claude_effort)

    def fix(self, shaped_svg: str, findings: List[str]) -> str:
        request = (
            "This SVG banner failed a deterministic lint. Fix ONLY these problems with "
            "minimal edits — do not re-art-direct — and reply with the complete SVG:\n"
            + "\n".join(f"- {f}" for f in findings) + f"\n\nSVG:\n{shaped_svg}\n")
        return self._call(self.client.complete, EDITOR_SYSTEM, request, model=self.model,
                          max_tokens=SVG_AUTHOR_MAX_TOKENS, effort=self.settings.claude_effort)

    def critique(self, images: Tuple[Path, Path]) -> Optional[Dict[str, Any]]:
        if self._over_budget("critique"):
            return None
        card = (self.card.text_for(STYLE_CARD_CRITIC_SECTIONS) if self.card else
                f"Style: {self.settings.style}")
        request = (f"{self.article_block()}\n\nSTYLE TO GRADE AGAINST\n{card}\n\n"
                   "IMAGE 1 is the banner at full size; IMAGE 2 is the same banner at "
                   "120px. Reply with ONLY a JSON object of exactly this shape:\n"
                   f"{CRITIQUE_SKELETON}")
        try:
            reply = self._call(self.client.complete_vision, CRITIC_SYSTEM, request,
                               list(images), model=self.model, max_tokens=4096,
                               effort=self.settings.claude_effort, json_schema=CRITIQUE_SCHEMA)
        except Exception as exc:  # noqa: BLE001 - review never blocks a banner
            warn(f"  ↳ critique failed ({exc}); keeping the best draft so far")
            return None
        critique = validate_critique(_extract_json_object(reply or ""))
        if critique is None:
            warn("  ↳ critique returned no parseable verdict")
        return critique

    def edit(self, svg: str, critique: Dict[str, Any]) -> str:
        fails = "\n".join(f"- {f}" for f in critique["fails"]) or "- (none listed)"
        request = (
            "Revise this banner. Keep everything the critique says works; apply the "
            "required change and fix what fails, changing as little else as possible. Keep "
            "any headline <text>/paths exactly as they are unless the critique names them.\n\n"
            f"WORKS: {critique['works']}\nFAILS:\n{fails}\n"
            f"REQUIRED NEXT CHANGE: {critique['next_change']}\n"
            f"SCORE: {critique['overall']}/10 — thumbnail "
            f"{'holds' if critique['thumbnail_holds'] else 'does NOT hold'} at 120px.\n\n"
            f"{self.article_block()}\n\nCURRENT SVG:\n{svg}\n")
        return self._call(self.client.complete, EDITOR_SYSTEM, request, model=self.model,
                          max_tokens=SVG_AUTHOR_MAX_TOKENS, effort=self.settings.claude_effort)

    # -- driver ---------------------------------------------------------------
    def run(self, prompt: str) -> Optional[ShapedSvg]:
        """Returns the shaped SVG to commit, or None (caller falls back)."""
        title = self.article.get("title", "") or self.ctx.slug
        if self._over_budget("authoring"):
            self.meta["fallback"] = "budget"
            return None
        plan = self.plan(prompt)
        try:
            shaped = shape_svg(extract_svg_document(self.author(plan, prompt)), title,
                               self.settings, self.family)
        except Exception as exc:  # noqa: BLE001 - every failure degrades
            warn(f"  ↳ authoring failed: {exc}")
            self.meta["fallback"] = "author_failed"
            return None
        if not shaped.lint.clean:
            info(f"  ↳ strict lint: {len(shaped.lint.findings())} finding(s) — one fix round")
            self.meta["fix_round"] = True
            try:
                shaped = shape_svg(extract_svg_document(
                    self.fix(shaped.svg, shaped.lint.findings())), title, self.settings,
                    self.family)
            except Exception as exc:  # noqa: BLE001
                warn(f"  ↳ fix round failed: {exc}")
                self.meta["fallback"] = "lint"
                return None
            if not shaped.lint.clean:
                warn("  ↳ still not strict-clean after the fix round: "
                     + "; ".join(shaped.lint.findings()[:3]))
                self.meta["fallback"] = "lint"
                return None
        if self.settings.claude_rounds <= 0:
            return shaped

        best: Tuple[ShapedSvg, Optional[Dict[str, Any]]] = (shaped, None)
        current = shaped
        with tempfile.TemporaryDirectory(prefix="zer0-look-") as tmp:
            for round_no in range(self.settings.claude_rounds + 1):
                look = look_svg(current.svg, Path(tmp), f"r{round_no}", self.settings,
                                self.ctx.project_root)
                if look is None:
                    info("  ↳ no rasterizer to look through — committing unreviewed")
                    break
                self.meta["rasterizer"] = look[2]
                critique = self.critique((look[0], look[1]))
                if critique is None:
                    break
                info(f"  ↳ critic: {critique['overall']:g}/10, thumbnail "
                     f"{'holds' if critique['thumbnail_holds'] else 'fails'}"
                     + (f" (round {round_no})" if round_no else ""))
                if critique_rank(critique) >= critique_rank(best[1]):
                    best = (current, critique)
                if critique_passes(critique, self.settings):
                    break
                if round_no >= self.settings.claude_rounds or self._over_budget("edit"):
                    break
                try:
                    edited = shape_svg(extract_svg_document(self.edit(current.svg, critique)),
                                       title, self.settings, self.family)
                except Exception as exc:  # noqa: BLE001
                    warn(f"  ↳ edit round failed: {exc}")
                    break
                self.meta["rounds_used"] = round_no + 1
                if not edited.lint.clean:
                    warn("  ↳ edit broke strict lint — keeping the previous draft")
                    break
                current = edited
        self.meta["critic"] = best[1]
        return best[0]


# =============================================================================
# Providers
# =============================================================================

@dataclass
class ImageResult:
    ok: bool
    kind: str = "png"                 # png | svg
    path: Optional[Path] = None
    error: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None   # loop facts for the telemetry record


class EditUnsupported(Exception):
    def __init__(self, provider: str):
        super().__init__(f"provider '{provider}' has no image-edit capability")
        self.provider = provider


class Provider:
    name = "base"

    def is_configured(self, env: Dict[str, str]) -> bool:
        raise NotImplementedError

    def missing_hint(self, env: Dict[str, str]) -> str:
        raise NotImplementedError

    def default_model(self) -> str:
        raise NotImplementedError

    def auth_description(self, env: Dict[str, str]) -> Optional[str]:
        """One line naming the credential this run will authenticate with, for
        the config banner. None (the default) means "there is nothing
        interesting to say" — a provider with exactly one possible credential."""
        return None

    def output_stem(self, slug: str, ctx: "RunContext") -> str:
        """Filename stem this provider writes to, minus the extension.

        Per-article by default. A provider that deliberately SHARES one image
        across many pages (the collection default) overrides this so the runner
        writes one file and stamps every page at it, instead of emitting N
        near-identical copies under N names."""
        return slug

    def generate(self, prompt: str, settings: Settings, out_base: Path,
                 ctx: "RunContext") -> ImageResult:
        raise NotImplementedError

    def edit(self, image_path: Path, prompt: str, settings: Settings,
             ctx: "RunContext", out_path: Optional[Path] = None) -> ImageResult:
        """Enhance an existing image. Providers without an edit capability
        raise EditUnsupported; the runner then falls back to OpenAI (the
        historical behavior of --enhance)."""
        raise EditUnsupported(self.name)


@dataclass
class RunContext:
    """Run-scoped services handed to providers."""
    project_root: Path
    env: Dict[str, str]
    anthropic: Optional[AnthropicClient] = None
    grok: Optional["GrokClient"] = None
    slug: str = ""
    # The page's own context (slug/section/title/categories/description/body),
    # set per file by the runner. The local renderer derives BOTH composition
    # and palette from it, which is what makes a banner about its article
    # instead of about its filename.
    article: Optional[Dict[str, str]] = None
    # Shared by every per-file copy (dataclasses.replace is shallow), so the
    # illustration loop's spend cap is enforced across workers. Typed Any, not
    # "BudgetMeter": a string annotation on a dataclass field makes dataclasses
    # look the module up in sys.modules, which breaks every loader that execs
    # this file via spec_from_file_location (svg-check.py, the Ruby oracles,
    # site companions).
    budget: Any = field(default_factory=lambda: BudgetMeter())

    def claude(self) -> AnthropicClient:
        if self.anthropic is None:
            self.anthropic = AnthropicClient(self.env)
        return self.anthropic

    def grok_client(self) -> "GrokClient":
        if self.grok is None:
            self.grok = GrokClient(self.env)
        return self.grok

    def orchestrator(self, engine: str):
        return self.grok_client() if engine == "xai" else self.claude()


def adapt_openai_size_quality(model: str, size: str, quality: str) -> Tuple[str, str]:
    """Historical engine behavior: adapt shared settings per model family."""
    if model.startswith("gpt-image-") and size == "1792x1024":
        size = "1536x1024"
    elif model.startswith("dall-e-") and quality == "auto":
        quality = "standard"
    return size, quality


def _write_image_payload(entry: Dict[str, Any], out_path: Path) -> bool:
    """Persist one OpenAI-style data[0] entry (b64_json preferred, else url)."""
    b64 = entry.get("b64_json")
    if b64:
        out_path.write_bytes(base64.b64decode(b64))
        return True
    url = entry.get("url")
    if url:
        download_to(url, out_path)
        return True
    return False


class OpenAIProvider(Provider):
    name = "openai"

    def is_configured(self, env: Dict[str, str]) -> bool:
        return bool(env.get("OPENAI_API_KEY"))

    def missing_hint(self, env: Dict[str, str]) -> str:
        return "OPENAI_API_KEY environment variable is required for the OpenAI provider"

    def default_model(self) -> str:
        return "gpt-image-2"

    def _headers(self, env: Dict[str, str]) -> Dict[str, str]:
        return {"Authorization": f"Bearer {env['OPENAI_API_KEY']}"}

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        model = effective_model(settings, self)
        size, quality = adapt_openai_size_quality(model, settings.size, settings.quality)
        out_path = out_base.with_suffix(".png")
        payload = {"model": model, "prompt": prompt, "n": 1, "size": size, "quality": quality}
        debug(f"OpenAI generate: model={model} size={size} quality={quality}")
        try:
            data = with_retries(
                lambda: http_json(
                    "https://api.openai.com/v1/images/generations",
                    payload, self._headers(ctx.env), timeout=900,
                ),
                "OpenAI API",
            )
            entries = data.get("data") or []
            if not entries or not _write_image_payload(entries[0], out_path):
                return ImageResult(False, error="No image data in OpenAI response")
            return ImageResult(True, "png", out_path)
        except HttpStatusError as exc:
            return ImageResult(False, error=f"OpenAI API error: {exc.message()}")
        except Exception as exc:
            return ImageResult(False, error=str(exc))

    def edit(self, image_path, prompt, settings, ctx, out_path=None) -> ImageResult:
        model = settings.enhance_model
        fields = {
            "prompt": prompt,
            "model": model,
            "n": "1",
            "size": "auto",
            "quality": settings.enhance_quality,
            "output_format": settings.enhance_format,
        }
        # gpt-image-2 does not accept input_fidelity (historical behavior).
        if model != "gpt-image-2":
            fields["input_fidelity"] = settings.enhance_fidelity
        image_bytes = image_path.read_bytes()
        files = [("image[]", image_path.name, image_bytes, image_media_type(image_bytes))]
        out_path = out_path or image_path
        debug(f"OpenAI edit: model={model} fidelity="
              f"{fields.get('input_fidelity', '(omitted)')} format={settings.enhance_format}")
        try:
            data = with_retries(
                lambda: http_multipart(
                    "https://api.openai.com/v1/images/edits",
                    fields, files, self._headers(ctx.env), timeout=900,
                ),
                "OpenAI edits API",
            )
            usage = data.get("usage") or {}
            if usage.get("total_tokens"):
                debug(f"Token usage: {usage.get('total_tokens')} total")
            entries = data.get("data") or []
            if not entries or not _write_image_payload(entries[0], out_path):
                return ImageResult(False, error="No image data in enhance response")
            revised = entries[0].get("revised_prompt")
            if revised:
                debug(f"Revised prompt: {revised[:200]}...")
            return ImageResult(True, "png", out_path)
        except HttpStatusError as exc:
            return ImageResult(False, error=f"OpenAI enhance API error: {exc.message()}")
        except Exception as exc:
            return ImageResult(False, error=str(exc))


# --- xAI (Grok) credentials --------------------------------------------------
#
# api.x.ai takes a plain `Authorization: Bearer <value>` for BOTH kinds of
# credential, so the only thing that varies between a Grok OAuth access token
# and a console API key is where the value comes from and what we tell the human
# when it is rejected.
#
# Refresh, not login. The engine never MINTS a token — that takes an interactive
# login — but an expired token whose store also holds a refresh
# token and a client id (Kilo Code's login does) is refreshed at auth.x.ai once,
# right before a request needs it, and written back to that store so the login
# tool and the next run both see the rotated pair (lifehacker.dev's cover-art
# script already refreshes and saves the same way). Expired with nothing to
# refresh with, a token is treated as absent and the chain falls back to the
# API key.
XAI_API_BASE = "https://api.x.ai/v1"

# OAuth access token straight from the environment. XAI_ first (it matches the
# vendor's own XAI_* naming), GROK_ accepted because that is what the
# consumer-facing login is called.
XAI_OAUTH_TOKEN_ENV: Tuple[str, ...] = ("XAI_OAUTH_TOKEN", "GROK_OAUTH_TOKEN")

# Explicit path to a credentials file written by a Grok OAuth login.
XAI_CREDENTIALS_FILE_ENV: Tuple[str, ...] = (
    "XAI_OAUTH_CREDENTIALS", "GROK_OAUTH_CREDENTIALS",
)

XAI_API_KEY_ENV = "XAI_API_KEY"

# Where a Grok login drops its token when no path is configured. Relative to the
# home directory so a test (and a container) can point HOME elsewhere.
XAI_DEFAULT_CREDENTIALS_FILES: Tuple[str, ...] = (
    ".grok/auth.json", ".config/grok/auth.json", ".xai/auth.json",
    ".local/share/kilo/auth.json",
)

# Credential files nest the token differently per tool; look at the top level
# first, then inside the usual containers.
XAI_NESTED_KEYS: Tuple[str, ...] = ("xai", "grok", "oauth", "tokens", "credentials")

# Treat a token that expires within the minute as already gone — a run can
# easily outlive that, and the API key fallback is cheaper than a mid-run 401 on
# every remaining page.
XAI_EXPIRY_LEEWAY = 60.0

# Which rung(s) to try, as an env knob. `auto` (the default) is OAuth first with
# the API key as the fallback; the other two pin one rung.
XAI_AUTH_MODE_ENV = "XAI_AUTH"
XAI_AUTH_MODES: Tuple[str, ...] = ("auto", "oauth", "api_key")

# The refresh grant's endpoint, as auth.x.ai's OIDC discovery document
# (/.well-known/openid-configuration) publishes it.
XAI_TOKEN_ENDPOINT = "https://auth.x.ai/oauth2/token"
XAI_REFRESH_TOKEN_KEYS: Tuple[str, ...] = ("refresh_token", "refresh")
XAI_EXPIRY_KEYS: Tuple[str, ...] = ("expires_at", "expiry", "expiration", "expires")
XAI_ISSUED_KEYS: Tuple[str, ...] = ("created_at", "obtained_at", "issued_at", "issued")
# Workers share one store: the first to find the token expired refreshes it,
# the rest wait and read the result. A refresh token may rotate on use, so two
# concurrent refreshes would leave one worker holding a dead token.
_XAI_REFRESH_LOCK = threading.Lock()

XAI_MISSING_HINT = (
    "The xAI provider needs a Grok OAuth token or an xAI API key — any ONE of:\n"
    "  1. XAI_OAUTH_TOKEN (or GROK_OAUTH_TOKEN) — an OAuth access token from a\n"
    "     Grok login (SuperGrok / X Premium+)\n"
    "  2. a Grok OAuth credentials file — ~/.grok/auth.json by default, or the\n"
    "     path in XAI_OAUTH_CREDENTIALS / GROK_OAUTH_CREDENTIALS\n"
    "  3. XAI_API_KEY — a key from console.x.ai (also the automatic fallback\n"
    "     when an OAuth token is expired or rejected)\n"
    "Pin one rung with XAI_AUTH=oauth|api_key; the default tries OAuth first."
)


@dataclass
class XAICredential:
    """One resolved way to authenticate against api.x.ai."""
    mode: str    # "oauth" | "api_key" — which rung of the chain this is
    token: str
    source: str  # human label for logs and fallback warnings
    # Set when the token has expired but its store can refresh it: the token is
    # empty until xai_ready_credential() refreshes it, right before use.
    refresh_path: Optional[str] = None

    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def xai_auth_mode(env: Dict[str, str]) -> str:
    raw = (env.get(XAI_AUTH_MODE_ENV) or "").strip().lower()
    if not raw:
        return "auto"
    if raw in XAI_AUTH_MODES:
        return raw
    debug(f"{XAI_AUTH_MODE_ENV}={raw} is not one of "
          f"{'|'.join(XAI_AUTH_MODES)}; using auto")
    return "auto"


def xai_credential_chain(env: Dict[str, str]) -> List[XAICredential]:
    """The credentials to try, best rung first. Empty = provider unconfigured."""
    mode = xai_auth_mode(env)
    chain: List[XAICredential] = []
    if mode != "api_key":
        chain.extend(_xai_oauth_credentials(env))
    if mode != "oauth":
        api_key = _xai_api_key_credential(env)
        if api_key is not None:
            chain.append(api_key)
    return chain


def xai_auth_describe(env: Dict[str, str]) -> Optional[str]:
    """One-line summary of how this run will authenticate (None when it cannot)."""
    chain = xai_credential_chain(env)
    if not chain:
        return None
    if len(chain) > 1:
        return f"{chain[0].source}, falling back to {chain[1].source}"
    return chain[0].source


def xai_base_url(env: Dict[str, str]) -> str:
    """Base for the images endpoint. XAI_BASE_URL is xAI's own override and is
    honored here so an OAuth surface on a different host stays reachable."""
    configured = env.get("XAI_BASE_URL") or ""
    return configured.rstrip("/") if configured else XAI_API_BASE


def _xai_oauth_credentials(env: Dict[str, str]) -> List[XAICredential]:
    for name in XAI_OAUTH_TOKEN_ENV:
        value = env.get(name)
        if value:
            return [XAICredential("oauth", value, f"{name} (Grok OAuth token)")]
    for path in _xai_credential_files(env):
        credential = _xai_file_credential(path)
        if credential is not None:
            return [credential]
    return []


def _xai_api_key_credential(env: Dict[str, str]) -> Optional[XAICredential]:
    value = env.get(XAI_API_KEY_ENV)
    if not value:
        return None
    return XAICredential("api_key", value, f"{XAI_API_KEY_ENV} (xAI API key)")


def _xai_credential_files(env: Dict[str, str]) -> List[str]:
    """Candidate credential-file paths: an explicit override wins outright, so a
    configured-but-missing path never silently reads someone else's token."""
    for name in XAI_CREDENTIALS_FILE_ENV:
        value = env.get(name)
        if value:
            return [value]
    home = _xai_home_dir(env)
    if not home:
        return []
    paths = [os.path.join(home, rel) for rel in XAI_DEFAULT_CREDENTIALS_FILES]
    kilo = env.get("KILO_AUTH_PATH") or ""
    if kilo:
        paths.insert(0, kilo)
    return paths


def _xai_home_dir(env: Dict[str, str]) -> Optional[str]:
    """The env snapshot is the source of truth (tests and containers set HOME);
    the process's own home is only the last resort."""
    for name in ("HOME", "USERPROFILE"):
        value = env.get(name)
        if value:
            return value
    home = os.path.expanduser("~")
    # expanduser returns "~" unchanged when it cannot resolve a home directory.
    return home if home and home != "~" else None


def _xai_file_credential(path: str) -> Optional[XAICredential]:
    """Read one credentials file. Anything unreadable, unparseable, tokenless or
    expired is "no credential here" — the chain moves on to the next rung."""
    if not os.path.isfile(path):
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        debug(f"xAI OAuth: {path} is not valid JSON ({exc}); ignoring")
        return None
    except OSError as exc:
        debug(f"xAI OAuth: cannot read {path} ({exc}); ignoring")
        return None
    if not isinstance(data, dict):
        debug(f"xAI OAuth: {path} is not a JSON object; ignoring")
        return None
    node = _xai_token_node(data)
    if node is None:
        debug(f"xAI OAuth: no access_token in {path}; ignoring")
        return None
    if _xai_expired(node):
        if _xai_refresh_token(node) and _xai_client_id(node):
            return XAICredential("oauth", "",
                                 f"Grok OAuth token ({path}; expired, refreshed on use)",
                                 refresh_path=path)
        debug(f"xAI OAuth: the token in {path} has expired and holds nothing to "
              f"refresh it with; re-run your Grok login")
        return None
    return XAICredential("oauth", str(node["access_token"]),
                         f"Grok OAuth token ({path})")


def xai_ready_credential(credential: XAICredential) -> XAICredential:
    """The credential ready to send: itself, or for an expired OAuth token its
    store can refresh, the refreshed one. Raises RuntimeError on a failed refresh."""
    if not credential.refresh_path:
        return credential
    return _xai_refresh_file_credential(credential.refresh_path)


def _xai_refresh_file_credential(path: str) -> XAICredential:
    with _XAI_REFRESH_LOCK:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"xAI OAuth: cannot re-read {path} ({exc})") from None
        node = _xai_find_token_node(data) if isinstance(data, dict) else None
        if node is None:
            raise RuntimeError(f"xAI OAuth: no access token left in {path}")
        # Another worker may have refreshed the store while this one waited.
        current = _xai_token_node(data)
        if current is not None and not _xai_expired(current):
            return XAICredential("oauth", str(current["access_token"]),
                                 f"Grok OAuth token ({path})")
        refresh, client_id = _xai_refresh_token(node), _xai_client_id(node)
        if not refresh or not client_id:
            raise RuntimeError(f"xAI OAuth: the token in {path} cannot be refreshed")
        fresh = _xai_request_refresh(refresh, client_id)
        _xai_store_refreshed(node, fresh, time.time())
        try:
            _xai_write_store(path, data)
        except OSError as exc:
            # The refresh token may already have rotated, so say so loudly — but
            # this run still holds a working access token.
            warn(f"xAI OAuth: refreshed, but could not save the new token to {path} "
                 f"({exc}); the login tool may need a fresh sign-in")
        debug(f"xAI OAuth: refreshed the token in {path}")
        return XAICredential("oauth", str(fresh["access_token"]),
                             f"Grok OAuth token ({path}; refreshed)")


def _xai_request_refresh(refresh_token: str, client_id: str) -> Dict[str, Any]:
    """POST the refresh grant. Never retried: a refresh token that rotated on a
    request whose response was lost is already spent."""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}
    try:
        _, _, raw = http_request(XAI_TOKEN_ENDPOINT, "POST", headers, body, 60)
    except HttpStatusError as exc:
        # The OAuth error code (invalid_grant, invalid_client) is safe to show
        # and says whether a re-login is due; the description may echo input.
        details = exc.json()
        code = details.get("error") if isinstance(details, dict) else None
        reason = f"HTTP {exc.status}: {code}" if _xai_token_string(code) else f"HTTP {exc.status}"
        raise RuntimeError(f"xAI OAuth refresh failed ({reason})") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise RuntimeError("xAI OAuth refresh returned non-JSON") from None
    if not isinstance(data, dict) or not _xai_token_string(data.get("access_token")):
        raise RuntimeError("xAI OAuth refresh returned no access_token")
    return data


def _xai_store_refreshed(node: Dict[str, Any], fresh: Dict[str, Any], now: float) -> None:
    """Write the refreshed pair into the store's own node, in its own key names
    and time units, so the tool that owns the file still reads it."""
    token_key = "access_token" if _xai_token_string(node.get("access_token")) else "access"
    node[token_key] = fresh["access_token"]
    if _xai_token_string(fresh.get("refresh_token")):
        refresh_key = next((k for k in XAI_REFRESH_TOKEN_KEYS
                            if _xai_token_string(node.get(k))), "refresh_token")
        node[refresh_key] = fresh["refresh_token"]
    lifetime = _xai_number(fresh.get("expires_in")) or 3600.0
    for key in XAI_EXPIRY_KEYS:
        if _xai_epoch_seconds(node.get(key)) is not None:
            node[key] = _xai_timestamp_like(node[key], now + lifetime)
            return
    if _xai_number(node.get("expires_in")) is not None:
        node["expires_in"] = int(lifetime)
        for key in XAI_ISSUED_KEYS:
            if _xai_epoch_seconds(node.get(key)) is not None:
                node[key] = _xai_timestamp_like(node[key], now)
                return


def _xai_timestamp_like(previous: Any, seconds: float) -> Any:
    """`seconds` in the shape `previous` used: epoch ms, epoch s, or ISO-8601."""
    value = _xai_number(previous)
    if value is not None:
        stamp = int(seconds * 1000) if value > 1e11 else int(seconds)
        return str(stamp) if isinstance(previous, str) else stamp
    return datetime.fromtimestamp(int(seconds), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _xai_write_store(path: str, data: Dict[str, Any]) -> None:
    """Replace the store atomically, keeping its permissions (it holds secrets)."""
    target = Path(os.path.realpath(path))
    mode = target.stat().st_mode & 0o777
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        # Created owner-only: the token must never sit world-readable, even briefly.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _xai_refresh_token(node: Dict[str, Any]) -> Optional[str]:
    for key in XAI_REFRESH_TOKEN_KEYS:
        if _xai_token_string(node.get(key)):
            return node[key]
    return None


def _xai_client_id(node: Dict[str, Any]) -> Optional[str]:
    """The OAuth client the token was issued to: the store's own record, else
    the access token's JWT claims (client_id, then a string or first aud)."""
    if _xai_token_string(node.get("client_id")):
        return node["client_id"]
    access = node.get("access_token") if _xai_token_string(node.get("access_token")) \
        else node.get("access")
    claims = _xai_jwt_claims(access)
    if _xai_token_string(claims.get("client_id")):
        return claims["client_id"]
    aud = claims.get("aud")
    if isinstance(aud, list):
        aud = next((a for a in aud if _xai_token_string(a)), None)
    return aud if _xai_token_string(aud) else None


def _xai_jwt_claims(token: Any) -> Dict[str, Any]:
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) < 2:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _xai_token_node(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The dict actually holding `access_token`: the document itself, or one of
    the containers a login tool nests it under. Kilo's store uses `access`."""
    node = _xai_find_token_node(data)
    if node is None:
        return None
    if _xai_token_string(node.get("access_token")):
        return node
    out = dict(node)
    out["access_token"] = node["access"]
    return out


def _xai_find_token_node(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _xai_token_string(data.get("access_token")) or _xai_token_string(data.get("access")):
        return data
    for key in XAI_NESTED_KEYS:
        nested = data.get(key)
        if isinstance(nested, dict) and (
            _xai_token_string(nested.get("access_token"))
            or _xai_token_string(nested.get("access"))
        ):
            return nested
    return None


def _xai_token_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _xai_expired(node: Dict[str, Any], now: Optional[float] = None) -> bool:
    expires_at = _xai_absolute_expiry(node)
    if expires_at is None:
        return False
    return expires_at <= (time.time() if now is None else now) + XAI_EXPIRY_LEEWAY


def _xai_absolute_expiry(node: Dict[str, Any]) -> Optional[float]:
    """Absolute expiry in epoch seconds, or None when the file records none."""
    for key in ("expires_at", "expiry", "expiration", "expires"):
        value = _xai_epoch_seconds(node.get(key))
        if value is not None:
            return value
    # `expires_in` is relative and only means something next to an issue time.
    lifetime = _xai_number(node.get("expires_in"))
    if lifetime is None:
        return None
    for key in ("created_at", "obtained_at", "issued_at", "issued"):
        issued = _xai_epoch_seconds(node.get(key))
        if issued is not None:
            return issued + lifetime
    return None


def _xai_epoch_seconds(raw: Any) -> Optional[float]:
    """Accepts epoch seconds, epoch milliseconds, or an ISO-8601 timestamp."""
    value = _xai_number(raw)
    if value is not None:
        # 1e11 seconds is the year 5138; anything past it is milliseconds.
        return value / 1000.0 if value > 1e11 else value
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# Aspect ratios the Imagine models take. grok-imagine renders a square unless
# told otherwise, which a wide banner then crops; grok-2-image predates the
# parameter, so it is sent nothing.
XAI_IMAGINE_PREFIX = "grok-imagine"
XAI_ASPECT_RATIOS: Tuple[Tuple[str, float], ...] = (
    ("1:1", 1.0), ("3:2", 1.5), ("2:3", 2 / 3), ("4:3", 4 / 3),
    ("3:4", 0.75), ("16:9", 16 / 9), ("9:16", 9 / 16),
)


def xai_aspect_ratio(model: str, size: str) -> Optional[str]:
    """The Imagine aspect ratio nearest the configured WIDTHxHEIGHT size, or None
    for a non-Imagine model or a size with no dimensions (e.g. `auto`)."""
    if not (model or "").strip().lower().startswith(XAI_IMAGINE_PREFIX):
        return None
    match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", size or "")
    if not match or not int(match.group(1)) or not int(match.group(2)):
        return None
    wanted = math.log(int(match.group(1)) / int(match.group(2)))
    return min(XAI_ASPECT_RATIOS, key=lambda item: abs(math.log(item[1]) - wanted))[0]


def _xai_number(raw: Any) -> Optional[float]:
    # bool is an int subclass; a JSON true/false is not a timestamp.
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class GrokClient:
    """OpenAI-compatible chat client for api.x.ai.

    Duck-typed against AnthropicClient (complete / complete_vision / available /
    describe) so analyze/review can run on Grok with the same OAuth token the
    image renderer already uses.
    """

    DEFAULT_MODEL = "grok-4"

    def __init__(self, env: Optional[Dict[str, str]] = None) -> None:
        self.env = dict(os.environ if env is None else env)
        chain = xai_credential_chain(self.env)
        self.credential = chain[0] if chain else None

    def available(self) -> bool:
        return self.credential is not None

    def describe(self) -> str:
        return self.credential.source if self.credential else "none"

    def complete(
        self,
        system_text: str,
        user_text: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2048,
        effort: str = "",
    ) -> str:
        if self.credential is None:
            raise RuntimeError("no xAI credential configured")
        payload = {
            "model": self._resolve_model(model),
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": max_tokens,
        }
        return self._message_text(self._api_call(payload, "xAI chat"))

    def complete_vision(
        self,
        system_text: str,
        user_text: str,
        image_path: Path,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 2048,
        effort: str = "",
    ) -> str:
        if self.credential is None:
            raise RuntimeError("no xAI credential configured")
        raw = Path(image_path).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        payload = {
            "model": self._resolve_model(model),
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{image_media_type(raw)};base64,{b64}"}},
                    {"type": "text", "text": user_text},
                ]},
            ],
            "max_tokens": max_tokens,
        }
        return self._message_text(self._api_call(payload, "xAI chat (review)"))

    def _resolve_model(self, model: str) -> str:
        name = (model or "").strip()
        if not name or name.startswith("claude"):
            return self.DEFAULT_MODEL
        return name

    def _api_call(self, payload: Dict[str, Any], what: str) -> dict:
        self.credential = xai_ready_credential(self.credential)
        url = f"{xai_base_url(self.env)}/chat/completions"
        return with_retries(
            lambda: http_json(url, payload, self.credential.headers(), timeout=900),
            what,
        )

    def _message_text(self, data: dict) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")


class XAIProvider(Provider):
    """xAI (Grok) images/generations.

    Two ways in, tried in order: a Grok OAuth access token, then the
    XAI_API_KEY. Both are Bearer credentials on the same endpoint, so the
    fallback is genuinely a retry with a different token — an OAuth token that
    has gone stale between runs costs one rejected request and then rides the
    API key instead of failing the page."""
    name = "xai"

    # Statuses that mean "this credential is no good" rather than "this request
    # is no good" — the only ones worth re-trying on the next rung.
    AUTH_FAILURE_STATUSES = (401, 403)

    # xAI caps the prompt; the original engine slices the first 1000 chars.
    PROMPT_LIMIT = 1000

    def is_configured(self, env: Dict[str, str]) -> bool:
        return bool(xai_credential_chain(env))

    def missing_hint(self, env: Dict[str, str]) -> str:
        return XAI_MISSING_HINT

    def auth_description(self, env: Dict[str, str]) -> Optional[str]:
        return xai_auth_describe(env)

    def default_model(self) -> str:
        return "grok-2-image"

    @staticmethod
    def _named_for_its_bytes(out_path: Path) -> ImageResult:
        """Imagine answers JPEG: keep the bytes (a PNG re-encode is ~4x larger)
        and give the file the extension they are, so it is served as what it is."""
        with out_path.open("rb") as handle:
            head = handle.read(12)
        if image_media_type(head) != "image/jpeg":
            return ImageResult(True, "png", out_path)
        jpg_path = out_path.with_suffix(".jpg")
        out_path.replace(jpg_path)
        return ImageResult(True, "jpg", jpg_path)

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        chain = xai_credential_chain(ctx.env)
        if not chain:
            return ImageResult(False, error=XAI_MISSING_HINT)
        model = effective_model(settings, self)
        out_path = out_base.with_suffix(".png")
        payload = {"model": model, "prompt": prompt[:self.PROMPT_LIMIT], "n": 1}
        aspect = xai_aspect_ratio(model, settings.size)
        if aspect:
            payload["aspect_ratio"] = aspect
        url = f"{xai_base_url(ctx.env)}/images/generations"
        for index, credential in enumerate(chain):
            try:
                credential = xai_ready_credential(credential)
            except Exception as exc:
                fallback = chain[index + 1] if index + 1 < len(chain) else None
                if fallback is not None:
                    warn(f"{exc} — retrying with {fallback.source}")
                    continue
                return ImageResult(False, error=f"{exc}; re-run your Grok login")
            debug(f"xAI generate: model={model} auth={credential.source}")
            try:
                data = with_retries(
                    lambda: http_json(url, payload, credential.headers(), timeout=900),
                    "xAI API",
                )
                entries = data.get("data") or []
                if not entries or not _write_image_payload(entries[0], out_path):
                    return ImageResult(False, error="No image data in xAI response")
                return self._named_for_its_bytes(out_path)
            except HttpStatusError as exc:
                fallback = chain[index + 1] if index + 1 < len(chain) else None
                if exc.status in self.AUTH_FAILURE_STATUSES and fallback is not None:
                    warn(f"xAI rejected the {credential.source} (HTTP {exc.status}) — "
                         f"retrying with {fallback.source}")
                    continue
                return ImageResult(False, error=f"xAI API error: {exc.message()}")
            except Exception as exc:
                return ImageResult(False, error=str(exc))
        # Unreachable: the last rung has no fallback and always returns above.
        return ImageResult(False, error="No usable xAI credential")


class StabilityProvider(Provider):
    name = "stability"

    def is_configured(self, env: Dict[str, str]) -> bool:
        return bool(env.get("STABILITY_API_KEY"))

    def missing_hint(self, env: Dict[str, str]) -> str:
        return "STABILITY_API_KEY environment variable is required for the Stability AI provider"

    def default_model(self) -> str:
        return "stable-diffusion-xl-1024-v1-0"

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        out_path = out_base.with_suffix(".png")
        payload = {
            "text_prompts": [{"text": prompt}],
            "cfg_scale": 7,
            # SDXL v1 endpoint accepts fixed dimension sets; 1024x1024 preserved
            # from the original engine.
            "height": 1024,
            "width": 1024,
            "samples": 1,
            "steps": 30,
        }
        try:
            data = with_retries(
                lambda: http_json(
                    "https://api.stability.ai/v1/generation/"
                    "stable-diffusion-xl-1024-v1-0/text-to-image",
                    payload,
                    {"Authorization": f"Bearer {ctx.env['STABILITY_API_KEY']}"},
                    timeout=900,
                ),
                "Stability API",
            )
            artifacts = data.get("artifacts") or []
            if not artifacts or not artifacts[0].get("base64"):
                return ImageResult(False, error="No image data in Stability response")
            out_path.write_bytes(base64.b64decode(artifacts[0]["base64"]))
            return ImageResult(True, "png", out_path)
        except HttpStatusError as exc:
            return ImageResult(False, error=f"Stability API error: {exc.message()}")
        except Exception as exc:
            return ImageResult(False, error=str(exc))


class GeminiProvider(Provider):
    name = "gemini"

    def is_configured(self, env: Dict[str, str]) -> bool:
        return bool(env.get("GEMINI_API_KEY"))

    def missing_hint(self, env: Dict[str, str]) -> str:
        return "GEMINI_API_KEY environment variable is required for the Gemini provider"

    def default_model(self) -> str:
        return "gemini-2.5-flash-image"

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        model = effective_model(settings, self)
        out_path = out_base.with_suffix(".png")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            data = with_retries(
                lambda: http_json(
                    url, payload,
                    {"x-goog-api-key": ctx.env["GEMINI_API_KEY"]},
                    timeout=900,
                ),
                "Gemini API",
            )
            for candidate in data.get("candidates") or []:
                for part in ((candidate.get("content") or {}).get("parts")) or []:
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        out_path.write_bytes(base64.b64decode(inline["data"]))
                        return ImageResult(True, "png", out_path)
            return ImageResult(False, error="No inline image data in Gemini response")
        except HttpStatusError as exc:
            return ImageResult(False, error=f"Gemini API error: {exc.message()}")
        except Exception as exc:
            return ImageResult(False, error=str(exc))


class SvgProviderMixin:
    """Shared sanitize → write → rasterize tail for SVG-producing providers."""

    def finish_svg(self, svg_text: str, out_base: Path, settings: Settings,
                   ctx: RunContext) -> ImageResult:
        try:
            clean, notes = sanitize_svg(svg_text)
        except SvgError as exc:
            return ImageResult(False, error=str(exc))
        for note in notes:
            warn(f"SVG sanitizer: {note}")
        svg_path = out_base.with_suffix(".svg")
        png_path = out_base.with_suffix(".png")
        svg_path.write_text(clean, encoding="utf-8")
        tool = rasterize_svg(svg_path, png_path, ctx.project_root, settings.rasterizer)
        if tool:
            svg_path.unlink(missing_ok=True)
            return ImageResult(True, "png", png_path)
        # `rasterizer: none` is a deliberate site policy (SVG-only), not a
        # missing dependency — say so instead of nagging about librsvg.
        if settings.rasterizer == "none":
            info(f"SVG-only mode (rasterizer: none) — wrote {svg_path.name}")
        else:
            warn(
                "No SVG rasterizer available — keeping the .svg preview. Social "
                "og:image works best as PNG: install librsvg (`brew install librsvg`) "
                "or Playwright (`npx playwright install chromium`), or set "
                "`preview_images.rasterizer: none` to make SVG-only the intent."
            )
        return ImageResult(True, "svg", svg_path)


class LocalProvider(Provider, SvgProviderMixin):
    name = "local"

    def is_configured(self, env: Dict[str, str]) -> bool:
        return True

    def missing_hint(self, env: Dict[str, str]) -> str:
        return ""

    def default_model(self) -> str:
        return "template-svg"

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        seed = seed_for(ctx.slug or out_base.stem)
        svg_text = render_local_svg(ctx.slug, seed, ctx.article)
        return self.finish_svg(svg_text, out_base, settings, ctx)

    def edit(self, image_path, prompt, settings, ctx, out_path=None) -> ImageResult:
        # Historical behavior: the local provider "enhances" by doing nothing
        # (no API), so dry testing of --enhance needs no credentials.
        warn("Local provider: No actual enhancement. Logging prompt...")
        debug(f"Enhancement prompt: {prompt[:400]}...")
        info(f"Placeholder: would enhance {image_path}")
        return ImageResult(True, "png", image_path)


# Renderers only — Claude is the orchestration layer (claude_article_brief /
# claude_review_image) that sits in front of ANY of these, not a provider.

class DefaultProvider(Provider, SvgProviderMixin):
    """Key-free floor: ONE shared banner per collection/section.

    The `local` provider draws a distinct procedural composition per article.
    That is right when the art is meant to be per-article, but when there is no
    AI credential anywhere it produces N near-identical images under N names —
    91 flow fields that differ only by palette read as one picture repeated, and
    cost 91 files to say so. This provider is honest about that instead: pages
    that were never touched by an image model share a single deliberate banner
    for their section, and the repo carries one file per section rather than one
    per page.

    Upgrade path: wire any renderer credential and `provider: auto` moves off
    this rung automatically.
    """

    name = "default"

    def is_configured(self, env: Dict[str, str]) -> bool:
        return True

    def missing_hint(self, env: Dict[str, str]) -> str:
        return ""

    def default_model(self) -> str:
        return "collection-default-svg"

    def group_of(self, ctx: "RunContext") -> str:
        article = ctx.article or {}
        return str(article.get("section") or "").strip() or "default"

    def output_stem(self, slug: str, ctx: "RunContext") -> str:
        # Every page in a section resolves to the same stem, so the runner
        # writes it once and stamps every page of that section at it.
        return f"section-{generate_filename(self.group_of(ctx)) or 'default'}"

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        group = self.group_of(ctx)
        # Seeded by the SECTION, not the article: the whole point is that the
        # image is shared, so it must not vary with whichever page happened to
        # trigger the write.
        seed = seed_for(group)
        composition, palette = banner_theme_for(
            {"slug": group, "section": group, "categories": group,
             "title": group, "description": "", "body": ""})
        svg_text = BANNER_COMPOSITIONS[composition](
            seed, BANNER_PALETTES[palette], group)
        return self.finish_svg(svg_text, out_base, settings, ctx)


class ClaudeSvgProvider(Provider, SvgProviderMixin):
    """Claude authors the banner as SVG, from the article — and LOOKS at it.

    Claude cannot render pixels — the Anthropic API has no image endpoint — but
    it can WRITE vector markup, which is the one image format a language model
    can emit directly. That makes it the rung between "no credential at all"
    and "a raster image API": genuinely per-article art, no image-model spend.

    Since 0.10 the one-shot call is a loop (IllustrationLoop): plan → author →
    shape → look → critique → edit, so the model sees the banner at full and
    thumbnail size before the run commits it. Every draft goes through the
    same sanitizer as every other SVG and a strict lint gate; a banner that
    cannot be made strict-clean is replaced by the deterministic `local` art
    rather than committed broken (degrade, never block, never ship broken).
    """

    name = "claude"

    def is_configured(self, env: Dict[str, str]) -> bool:
        return AnthropicClient(env).available()

    def missing_hint(self, env: Dict[str, str]) -> str:
        return CLAUDE_CREDENTIAL_HINT

    def default_model(self) -> str:
        return DEFAULT_CLAUDE_MODEL

    def authoring_model(self, settings: Settings) -> str:
        """--model when it is a Claude model, else claude_model, else default."""
        if model_family(settings.model or "") == "claude":
            return settings.model.strip()
        return claude_model_for(settings)

    def generate(self, prompt, settings, out_base, ctx) -> ImageResult:
        loop = IllustrationLoop(self, settings, ctx)
        shaped = loop.run(prompt)
        meta = dict(loop.meta)
        meta["calls"] = loop.calls
        meta["usage"] = loop.usage
        if shaped is None:
            info("  ↳ falling back to the deterministic local banner")
            result = LOCAL_FALLBACK.generate(prompt, settings, out_base, ctx)
            meta["fallback"] = meta.get("fallback") or "failed"
            meta["lint"] = None
            result.meta = meta
            return result
        meta["lint"] = {"clean": shaped.lint.clean, "errors": shaped.lint.errors,
                        "warnings": shaped.lint.warnings}
        meta["text"] = {"mode": settings.svg_text, "converted": shaped.text.converted,
                        "stripped": shaped.text.stripped, "fitted": shaped.text.fitted,
                        "missing_glyphs": shaped.text.missing_glyphs}
        for note in shaped.text.notes:
            debug(f"text→paths: {note}")
        result = self.finish_svg(shaped.svg, out_base, settings, ctx)
        result.meta = meta
        return result


def _extract_svg(text: str) -> str:
    """Pull the <svg>…</svg> out of a model reply, fence or no fence."""
    match = re.search(r"<svg\b.*?</svg>", str(text or ""), re.S | re.I)
    return match.group(0) if match else ""


PROVIDERS: Dict[str, Provider] = {
    provider.name: provider
    for provider in (
        OpenAIProvider(),
        XAIProvider(),
        StabilityProvider(),
        GeminiProvider(),
        LocalProvider(),
        DefaultProvider(),
        ClaudeSvgProvider(),
    )
}
LOCAL_FALLBACK: Provider = PROVIDERS["local"]


# =============================================================================
# Orchestrator
# =============================================================================

@dataclass
class Stats:
    processed: int = 0
    generated: int = 0
    enhanced: int = 0
    skipped: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name) + 1)


def _unquote_git_path(path: str) -> str:
    """Undo git's C-style quoting (`"p\\303\\244ge.md"`) so non-ASCII names
    survive --changed mode instead of being silently dropped."""
    if not (path.startswith('"') and path.endswith('"')):
        return path
    inner = path[1:-1]
    try:
        return (inner.encode("latin-1", "backslashreplace")
                .decode("unicode_escape")
                .encode("latin-1")
                .decode("utf-8"))
    except (UnicodeDecodeError, UnicodeEncodeError):
        return inner


def git_changed_markdown(root: Path, exclude_re: str = "") -> List[Tuple[Path, bool]]:
    """(path, is_new) for every new/modified markdown file under `root`.

    `-uall` matters: plain --porcelain collapses a brand-new directory to one
    `?? dir/` line, hiding every article inside it. `exclude_re` is matched
    against the raw status line (callers use it to skip files they staged
    themselves)."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=str(root),
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn(f"git status failed: {exc}")
        return []
    if out.returncode != 0:
        warn(f"git status failed: {(out.stderr or '').strip()[:200]}")
        return []
    pattern = re.compile(exclude_re) if exclude_re else None
    seen: Dict[Path, bool] = {}
    for line in out.stdout.splitlines():
        if len(line) < 4 or "D" in line[:2]:
            continue
        status, rel = line[:2], line[3:]
        if " -> " in rel:  # rename: take the new side
            rel = rel.split(" -> ", 1)[1]
        rel = _unquote_git_path(rel.strip())
        if not rel.endswith((".md", ".markdown")):
            continue
        if pattern is not None and pattern.search(line):
            continue
        candidate = root / rel
        if candidate.is_file():
            is_new = status == "??" or status.startswith("A")
            seen[candidate] = seen.get(candidate, False) or is_new
    return list(seen.items())


def banner_telemetry_record(root: Path, article: Path, slug: str, result: ImageResult,
                            settings: Settings) -> Dict[str, Any]:
    """One banner's telemetry: the shape `telemetry/banners.jsonl` carries
    (schema `banner/v1`; additive changes only)."""
    meta = dict(result.meta or {})
    usage = meta.pop("usage", None)
    tokens = None
    cost = None
    if usage:
        tokens = {"input": sum(u["input_tokens"] + u["cache_creation_input_tokens"]
                               + u["cache_read_input_tokens"] for u in usage),
                  "output": sum(u["output_tokens"] for u in usage)}
        cost = round(sum(u["cost_usd"] for u in usage), 6)

    def rel(path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(root.resolve()))
        except ValueError:
            return str(path)

    size_kb = None
    try:
        size_kb = round(result.path.stat().st_size / 1024, 1)
    except (OSError, AttributeError):
        pass
    critic = meta.get("critic")
    record = {
        "schema": "banner/v1",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slug": slug,
        "article": rel(article),
        "banner": rel(result.path),
        "kind": result.kind,
        "kb": size_kb,
        "provider": meta.get("provider") or settings.provider,
        "model": meta.get("model"),
        "style_card": meta.get("style_card"),
        "plan": meta.get("plan", False),
        "calls": meta.get("calls", 0),
        "rounds_used": meta.get("rounds_used", 0),
        "fix_round": meta.get("fix_round", False),
        "fallback": meta.get("fallback"),
        "rasterizer": meta.get("rasterizer"),
        "lint": meta.get("lint"),
        "text": meta.get("text"),
        "critic": ({"overall": critic["overall"], "thumbnail_holds": critic["thumbnail_holds"],
                    "fails": critic["fails"], "next_change": critic["next_change"]}
                   if critic else None),
        "tokens": tokens,
        "cost_usd": cost,
    }
    if meta.get("budget_skipped"):
        record["budget_skipped"] = meta["budget_skipped"]
    return record


def shape_file(svg_path: Path, settings: Settings, project_root: Path) -> Dict[str, Any]:
    """--shape: the loop's SHAPE step over a file, written back in place.

    This is how the interactive dev loop (.claude/workflows/svg-forge.js)
    finalizes a piece: through the same code the production loop commits
    with, so the two can never disagree about what "clean" means."""
    raw = svg_path.read_text(encoding="utf-8")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S)
    card = load_style_card(settings.style_card, project_root)
    family = card.font_family if card else DEFAULT_FONT_FAMILY
    out: Dict[str, Any] = {"schema": "banner-shape/v1", "banner": str(svg_path)}
    try:
        shaped = shape_svg(extract_svg_document(raw) or raw,
                           title_match.group(1).strip() if title_match else svg_path.stem,
                           settings, family)
    except SvgError as exc:
        out["lint"] = {"clean": False, "fatal": str(exc), "errors": [], "warnings": []}
        return out
    svg_path.write_text(shaped.svg, encoding="utf-8")
    out.update({
        "kb": round(len(shaped.svg.encode("utf-8")) / 1024, 1),
        "lint": {"clean": shaped.lint.clean, "fatal": shaped.lint.fatal,
                 "errors": shaped.lint.errors, "warnings": shaped.lint.warnings},
        "text": {"mode": settings.svg_text, "converted": shaped.text.converted,
                 "stripped": shaped.text.stripped, "fitted": shaped.text.fitted,
                 "notes": shaped.text.notes},
        "sanitizer": shaped.sanitizer_notes,
    })
    return out


def inspect_banner(svg_path: Path, settings: Settings, ctx: "RunContext",
                   article_path: Optional[Path] = None, critic: bool = False) -> Dict[str, Any]:
    """--inspect: strict-lint an existing banner, optionally render + critique
    it. The audit and backfill tooling read this one JSON object, so it is the
    same lint and the same critic the loop itself uses."""
    raw = svg_path.read_bytes()
    report = lint_svg(raw, svg_path.name, max_kb=settings.svg_max_kb, strict=True)
    text = raw.decode("utf-8", "replace")
    out: Dict[str, Any] = {
        "schema": "banner-inspect/v1",
        "banner": str(svg_path),
        "kb": round(len(raw) / 1024, 1),
        "lint": {"clean": report.clean, "fatal": report.fatal, "errors": report.errors,
                 "warnings": report.warnings},
        "features": {
            "text": len(re.findall(r"<text\b", text)),
            "filter": len(re.findall(r"<filter\b", text)),
            "gradient": len(re.findall(r"<(?:linear|radial)Gradient\b", text)),
        },
        "critic": None,
    }
    if not critic:
        return out
    article: Dict[str, str] = {"title": "", "section": "", "categories": "",
                               "description": "", "body": ""}
    if article_path is not None:
        cf = parse_front_matter(article_path, settings.front_matter_key)
        if cf is not None:
            article = article_art_context(cf, generate_filename(cf.title))
    if not article["title"]:
        match = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
        article["title"] = match.group(1).strip() if match else svg_path.stem
    if not ctx.claude().available():
        out["critic_error"] = "no Claude credential"
        return out
    loop = IllustrationLoop(PROVIDERS["claude"], settings,
                            replace(ctx, slug=svg_path.stem, article=article))
    with tempfile.TemporaryDirectory(prefix="zer0-inspect-") as tmp:
        look = look_svg(text, Path(tmp), "inspect", settings, ctx.project_root)
        if look is None:
            out["critic_error"] = f"no rasterizer ({settings.look_rasterizer})"
            return out
        out["rasterizer"] = look[2]
        out["critic"] = loop.critique((look[0], look[1]))
    if loop.usage:
        out["cost_usd"] = round(sum(u["cost_usd"] for u in loop.usage), 6)
    return out


class Runner:
    def __init__(self, settings: Settings, project_root: Path,
                 ctx: Optional[RunContext] = None):
        self.settings = settings
        self.root = project_root
        self.stats = Stats()
        self.authors = read_authors(project_root, settings.authors_file)
        self.ctx = ctx or RunContext(project_root=project_root, env=dict(os.environ))

    # -- discovery ------------------------------------------------------------

    def collection_path(self, name: str) -> Path:
        """`<root>/<collections_dir>/_<name>` — collections_dir is Jekyll's own
        key (default "" = site root; zer0-mistakes sets `pages`)."""
        base = self.root
        for part in self.settings.collections_dir.split("/"):
            if part:
                base = base / part
        return base / f"_{name}"

    def discover(self, collection_path: Path) -> List[Path]:
        if not collection_path.is_dir():
            warn(f"Collection directory not found: {collection_path}")
            return []
        return sorted(collection_path.rglob("*.md"))

    # -- per-file processing --------------------------------------------------

    def process_file(self, path: Path, is_new: bool = False) -> None:
        if _interrupted:
            return
        settings = self.settings
        self.stats.inc("processed")
        debug(f"Processing file: {path}")

        cf = parse_front_matter(path, settings.front_matter_key)
        if cf is None:
            self.stats.inc("skipped")
            return

        if settings.enhance:
            self._enhance_file(cf)
            return

        # Generate mode -------------------------------------------------------
        # A NEW article (--changed) may arrive stamped with its section's
        # shared placeholder banner, which exists on disk. Treating that as
        # "already illustrated" would skip exactly the articles the grow tick
        # exists to illustrate — so a new file is re-illustrated unless it
        # already points at its OWN slug-named banner or an external URL.
        replace_placeholder = False
        if is_new and cf.preview:
            external = str(cf.preview).startswith(("http://", "https://"))
            own = Path(str(cf.preview)).stem == generate_filename(cf.title or "")
            replace_placeholder = not external and not own
        if (cf.preview and not replace_placeholder
                and check_preview_exists(cf.preview, settings, self.root)):
            if not settings.force:
                debug(f"Preview already exists and is valid: {cf.preview}")
                self.stats.inc("skipped")
                return
            info(f"Force mode: regenerating preview for {cf.title}")

        if settings.list_only:
            print(f"{Colors.YELLOW}Missing preview:{Colors.NC} {path}")
            print(f"  Title: {cf.title}")
            if cf.preview:
                print(f"  Current preview (not found): {cf.preview}")
            print()
            return

        info(f"Generating preview for: {cf.title}")

        slug = generate_filename(cf.title)
        if not slug:
            warn(f"Cannot derive filename from title in {path}")
            self.stats.inc("errors")
            return
        # The provider chooses the filename stem: per-article for the real
        # renderers, one shared file per collection for the key-free default.
        provider_for_paths = PROVIDERS.get(settings.provider)
        stem = slug
        if provider_for_paths is not None:
            stem = provider_for_paths.output_stem(
                slug, replace(self.ctx, slug=slug,
                              article=article_art_context(cf, slug))) or slug
        out_base = self.root / settings.output_dir / stem

        # Style overrides apply only once an image/prompt is actually built.
        file_settings = file_preview_settings(settings, cf, self.authors)

        # ---- Analyze: Claude reads the article and writes the art brief ----
        base_prompt = build_prompt(cf, file_settings)
        prompt = base_prompt
        orchestrated = settings.provider != "local"  # local is deterministic
        # The claude provider's loop PLANS its own scene; a raster-model brief
        # in front of it would be one more call whose output the plan replaces.
        loop_plans = settings.provider == "claude" and file_settings.claude_plan
        if (orchestrated and file_settings.prompt_engine in ("claude", "xai")
                and not settings.dry_run and not loop_plans):
            prompt = claude_article_brief(
                self.ctx.orchestrator(file_settings.prompt_engine),
                cf, file_settings, base_prompt)
        debug(f"Generated prompt: {prompt[:500]}...")

        if settings.dry_run:
            info("[DRY RUN] Would generate image:")
            print(f"  Provider: {settings.provider}")
            if orchestrated and file_settings.prompt_engine in ("claude", "xai"):
                print(f"  Prompt engine: {file_settings.prompt_engine} "
                      "(article analysis runs at generation time)")
            if orchestrated and file_settings.review_engine in ("claude", "xai"):
                print(f"  Review: {file_settings.review_engine} "
                      "(image review runs at generation time)")
            if settings.provider == "claude":
                print(f"  Loop: plan={'on' if file_settings.claude_plan else 'off'} "
                      f"rounds={file_settings.claude_rounds} "
                      f"min_score={file_settings.claude_min_score:g} "
                      f"text={file_settings.svg_text} "
                      f"style_card={file_settings.style_card or '(prose style)'}")
            print(f"  Output: {out_base.with_suffix('.png')}")
            print(f"  Preview path: {preview_front_matter_path(file_settings, slug + '.png')}")
            print(f"  Prompt: {prompt[:400]}...")
            print()
            self.stats.inc("generated")
            return

        provider = PROVIDERS[settings.provider]
        # Per-file context copy: workers must not share a mutable slug (the
        # local provider derives its deterministic seed from it). The copy
        # carries the shared AnthropicClient reference, which is stateless
        # after init and therefore thread-safe.
        file_ctx = replace(self.ctx, slug=slug,
                           article=article_art_context(cf, slug))
        # ---- Produce: the selected raster model renders the brief ----
        result = provider.generate(prompt, file_settings, out_base, file_ctx)

        # ---- Review: Claude inspects the render; at most ONE regeneration ----
        if (orchestrated and file_settings.review_engine in ("claude", "xai")
                and result.ok and result.path and result.kind in ("png", "jpg")):
            approved, critique, revised = claude_review_image(
                self.ctx.orchestrator(file_settings.review_engine),
                result.path, cf, prompt, file_settings)
            if approved:
                if critique:
                    debug(f"Claude review: {critique}")
            else:
                info(f"  ↳ Claude review requested a revision: {critique}")
                debug(f"Revised prompt: {revised[:300]}...")
                retry = provider.generate(revised, file_settings, out_base, file_ctx)
                if retry.ok and retry.path:
                    result = retry
                    success("  ↳ Regenerated with Claude's revised brief")
                else:
                    warn(f"  ↳ Revision render failed "
                         f"({retry.error or 'unknown'}); keeping the first image")

        if result.ok and result.path:
            fm_value = preview_front_matter_path(file_settings, result.path.name)
            if update_front_matter(path, fm_value, dry_run=False,
                                   key=settings.front_matter_key):
                self.stats.inc("generated")
                self.emit_telemetry(path, slug, result, file_settings)
                # Serial-mode pacing between paid API calls (historical
                # behavior). In parallel mode a per-worker sleep throttles
                # nothing — it only burns worker capacity — so skip it.
                if POST_GENERATION_SLEEP and settings.parallel <= 1:
                    time.sleep(POST_GENERATION_SLEEP)
            else:
                self.stats.inc("errors")
        else:
            warn(f"Failed to generate image for: {cf.title}")
            if result.error:
                warn(f"  {result.error}")
            self.stats.inc("errors")

    # -- telemetry ------------------------------------------------------------

    _telemetry_lock = threading.Lock()

    def emit_telemetry(self, path: Path, slug: str, result: ImageResult,
                       settings: Settings) -> None:
        """Append one JSON record per committed banner (settings.telemetry)."""
        if not self.settings.telemetry or not result.path:
            return
        record = banner_telemetry_record(self.root, path, slug, result, settings)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with self._telemetry_lock:
            if self.settings.telemetry == "-":
                print(f"TELEMETRY {line}", flush=True)
                return
            target = Path(self.settings.telemetry)
            if not target.is_absolute():
                target = Path.cwd() / target
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                warn(f"telemetry not written ({exc})")

    def _enhance_file(self, cf: ContentFile) -> None:
        settings = self.settings
        existing = find_preview_image(cf.preview, settings, self.root)
        if existing is None:
            warn(f"No existing preview image found for: {cf.title}")
            warn(f"  Expected at: {cf.preview}")
            warn("  Use without --enhance to generate a new image first.")
            self.stats.inc("skipped")
            return

        info(f"Enhancing preview for: {cf.title}")
        file_settings = file_preview_settings(settings, cf, self.authors)
        prompt = build_enhance_prompt(cf, file_settings)
        debug(f"Enhancement prompt: {prompt[:400]}...")

        if settings.dry_run:
            info("[DRY RUN] Would enhance image:")
            print(f"  Source: {existing}")
            print(f"  Model: {settings.enhance_model}")
            print(f"  Prompt: {prompt[:400]}...")
            print()
            self.stats.inc("enhanced")
            return

        # --enhance-format other than the current extension writes a NEW file
        # (content and extension must agree) and repoints the front matter;
        # the default png-onto-png flow enhances in place with a backup.
        out_path = existing.with_suffix("." + settings.enhance_format)
        in_place = out_path == existing

        if in_place:
            backup = existing.with_name(existing.stem + "_pre-enhance" + existing.suffix)
            if not backup.exists():
                shutil.copy2(existing, backup)
                info(f"Original backed up to: {backup.name}")
            else:
                debug(f"Backup already exists: {backup}")
        else:
            backup = existing  # original file is untouched and acts as the fallback

        # Capability-driven routing: the active provider's edit() runs when it
        # has one; EditUnsupported falls back to OpenAI (historical behavior).
        provider = PROVIDERS[settings.provider]
        try:
            result = provider.edit(existing, prompt, file_settings, self.ctx, out_path)
        except EditUnsupported:
            warn(f"Enhancement not supported for provider: {settings.provider} "
                 "(falling back to OpenAI)")
            openai_provider = PROVIDERS["openai"]
            if not openai_provider.is_configured(self.ctx.env):
                warn("Enhance requires OPENAI_API_KEY (the images/edits API is OpenAI-only).")
                self.stats.inc("errors")
                return
            result = openai_provider.edit(existing, prompt, file_settings, self.ctx, out_path)

        if result.ok:
            if not in_place and result.path and result.path != existing:
                old_value = cf.preview or ""
                new_value = (
                    old_value.rsplit("/", 1)[0] + "/" + result.path.name
                    if "/" in old_value else result.path.name
                )
                update_front_matter(cf.path, new_value, dry_run=False,
                                    key=self.settings.front_matter_key)
                info(f"Preview extension changed: {existing.name} → {result.path.name}")
            success(f"Enhanced image saved to: {result.path or existing}")
            self.stats.inc("enhanced")
        else:
            warn(f"Failed to enhance image for: {cf.title}")
            if result.error:
                warn(f"  {result.error}")
            info(f"Original preserved at: {backup}")
            self.stats.inc("errors")

    # -- collection / run loop ------------------------------------------------

    def process_collection(self, collection_path: Path) -> None:
        files = self.discover(collection_path)
        if self.settings.batch > 0:
            files = files[: self.settings.batch]
        if not files:
            return
        serial = (
            self.settings.list_only
            or self.settings.dry_run
            or self.settings.parallel <= 1
        )
        if serial:
            for file_path in files:
                if _interrupted:
                    warn("Interrupted! Stopping...")
                    break
                self.process_file(file_path)
            return
        with ThreadPoolExecutor(max_workers=self.settings.parallel) as pool:
            futures = {pool.submit(self.process_file, f): f for f in files}
            for future in as_completed(futures):
                if _interrupted:
                    for pending in futures:
                        pending.cancel()
                    warn("Interrupted! Cancelling remaining tasks...")
                    break
                exc = future.exception()
                if exc:
                    warn(f"Worker failed on {futures[future]}: {exc}")
                    self.stats.inc("errors")

    def run(self) -> int:
        settings = self.settings
        if settings.changed:
            targets = git_changed_markdown(self.root, settings.exclude_re)
            step(f"Processing {len(targets)} new/modified markdown file(s)...")
            if settings.batch > 0:
                targets = targets[: settings.batch]
            if settings.parallel <= 1 or settings.dry_run or settings.list_only:
                for target, is_new in targets:
                    if _interrupted:
                        break
                    self.process_file(target, is_new=is_new)
            else:
                with ThreadPoolExecutor(max_workers=settings.parallel) as pool:
                    for future in as_completed(
                            [pool.submit(self.process_file, t, n) for t, n in targets]):
                        exc = future.exception()
                        if exc:
                            warn(f"Worker failed: {exc}")
                            self.stats.inc("errors")
        elif settings.file:
            target = Path(settings.file)
            if not target.is_absolute():
                # Source-relative first; then cwd-relative, so repo-root paths
                # like pages/_notes/x.md still work on `source:` sites.
                target = self.root / settings.file
                if not target.is_file() and (Path.cwd() / settings.file).is_file():
                    target = Path.cwd() / settings.file
            if not target.is_file():
                error_exit(f"File not found: {settings.file}")
            self.process_file(target)
        elif settings.collection and settings.collection != "all":
            path = self.collection_path(settings.collection)
            if not path.is_dir():
                available = ", ".join(settings.collections)
                error_exit(
                    f"Unknown collection: {settings.collection}. "
                    f"Available: {available}, all"
                )
            step(f"Processing {settings.collection} collection...")
            self.process_collection(path)
        else:
            step("Processing all configured collections...")
            for name in settings.collections:
                path = self.collection_path(name)
                if path.is_dir():
                    step(f"Processing {name} collection...")
                    self.process_collection(path)
                else:
                    warn(f"Collection directory not found: {path}")

        print()
        print_header("📊 Summary")
        print(f"  Files processed: {self.stats.processed}")
        print(f"  Images generated: {self.stats.generated}")
        print(f"  Images enhanced: {self.stats.enhanced}")
        print(f"  Files skipped: {self.stats.skipped}")
        print(f"  Errors: {self.stats.errors}")
        print()

        if settings.dry_run:
            info("This was a dry run. No actual changes were made.")
        if self.stats.errors > 0:
            warn("Some files had errors. Check the output above.")
            return 1
        success("Preview image generation complete!")
        return 0


# =============================================================================
# CLI
# =============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zer0-image-generator",
        description="AI preview/social-image generator for Jekyll sites — "
                    "Claude analyzes & reviews, a renderer produces "
                    "(openai [default], xai, stability, gemini, local)",
    )
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Preview what would be generated (no changes)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output")
    parser.add_argument("-f", "--file", help="Process a specific file only")
    parser.add_argument("-c", "--collection",
                        help="Process one collection by name, or 'all' for every "
                             "configured collection")
    parser.add_argument("-p", "--provider",
                        choices=sorted(list(PROVIDERS.keys()) + ["auto"]),
                        help="Renderer, or `auto` to pick the best one the "
                             "environment can reach (raster API > claude SVG > "
                             "shared collection default)")
    parser.add_argument("--model", help="Override the image/SVG model for the provider")
    parser.add_argument("--output-dir",
                        help="Output directory for images (default: assets/images/previews)")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate images even if preview exists")
    parser.add_argument("--list-missing", action="store_true",
                        help="Only list files with missing previews")
    parser.add_argument("-j", "--parallel", "-w", "--workers", type=int, default=None,
                        dest="parallel", metavar="N",
                        help="Concurrent workers (default 4; serial for dry-run/list)")
    parser.add_argument("-e", "--enhance", action="store_true",
                        help="Enhance existing preview images (OpenAI images/edits)")
    parser.add_argument("--enhance-prompt", help="Custom enhancement prompt (implies --enhance)")
    parser.add_argument("--enhance-model", help="Model for enhancement (default: gpt-image-2)")
    parser.add_argument("--enhance-quality", choices=["low", "medium", "high", "auto"],
                        help="Enhancement quality (default: auto)")
    parser.add_argument("--enhance-fidelity", choices=["high", "low"],
                        help="Input fidelity (implies --enhance)")
    parser.add_argument("--enhance-format", choices=["png", "jpeg", "webp"],
                        help="Enhanced output format (implies --enhance)")
    parser.add_argument("--prompt-engine", choices=["template", "claude", "xai"],
                        help="Art-direction brief: claude or xai (Grok OAuth) "
                             "analyzes the article (default: claude); template "
                             "uses the built-in prompt")
    parser.add_argument("--review", choices=["claude", "xai", "none"],
                        help="Post-render review: claude or xai inspects the image "
                             "and may request one refined regeneration (default: claude)")
    parser.add_argument("--rasterizer", choices=RASTERIZER_CHOICES,
                        help="SVG→PNG tool for claude/local providers (default: "
                             "auto; `none` keeps the .svg and writes no PNG)")
    loop = parser.add_argument_group(
        "illustration loop (provider: claude)",
        "plan → author → shape → look → critique → edit; see "
        "docs/ILLUSTRATION-LOOP.md")
    loop.add_argument("--style-card", dest="style_card", metavar="NAME",
                      help="style card name (tools/svg/library/styles/<NAME>.md) "
                           "or a path to one")
    loop.add_argument("--palette", metavar="TOKENS",
                      help="six hex tokens (comma separated) or a palette name")
    loop.add_argument("--claude-plan", dest="claude_plan",
                      action=argparse.BooleanOptionalAction, default=None,
                      help="plan a JSON scene graph before authoring (default: on)")
    loop.add_argument("--rounds", dest="claude_rounds", type=int, metavar="N",
                      help="critique-driven edit rounds (default 1; 0 = one-shot)")
    loop.add_argument("--min-score", dest="claude_min_score", type=float,
                      metavar="SCORE", help="critic score that ends the loop (default 7)")
    loop.add_argument("--require-thumbnail", dest="claude_require_thumbnail",
                      action=argparse.BooleanOptionalAction, default=None,
                      help="the banner must also read at 120px (default: on)")
    loop.add_argument("--svg-text", dest="svg_text", choices=["paths", "keep", "forbid"],
                      help="what happens to <text>: converted to paths with a "
                           "bundled font (default), kept, or stripped")
    loop.add_argument("--svg-max-kb", dest="svg_max_kb", type=float, metavar="KB",
                      help="strict-lint size budget per banner (default 300)")
    loop.add_argument("--look-rasterizer", dest="look_rasterizer",
                      choices=RASTERIZER_CHOICES,
                      help="tool the loop renders through to LOOK at a draft "
                           "(default auto; none disables the critique)")
    loop.add_argument("--budget-usd", dest="claude_budget_usd", type=float,
                      metavar="USD", help="per-run spend cap for the loop (0 = none)")
    loop.add_argument("--telemetry", metavar="PATH",
                      help="append one JSON record per banner to PATH ('-' = stdout)")
    loop.add_argument("--changed", action="store_true",
                      help="illustrate git-new/modified markdown files")
    loop.add_argument("--exclude-re", dest="exclude_re", metavar="REGEX",
                      help="--changed: skip `git status --porcelain` lines "
                           "matching REGEX")
    loop.add_argument("--inspect", metavar="SVG",
                      help="lint (and with --critic, render + critique) an "
                           "existing banner; prints one JSON object and exits")
    loop.add_argument("--critic", action="store_true",
                      help="with --inspect: also run the vision critique "
                           "(needs a Claude credential and a rasterizer)")
    loop.add_argument("--shape", metavar="SVG",
                      help="run the loop's deterministic SHAPE step on an SVG in "
                           "place (sanitize, text→paths, precision, strict lint); "
                           "prints one JSON object, exits 1 unless strict-clean")
    parser.add_argument("--style", help="Override image style prompt")
    parser.add_argument("--assets-prefix", help="Assets prefix for path normalization")
    parser.add_argument("--no-auto-prefix", action="store_true",
                        help="Disable automatic assets prefix prepending")
    parser.add_argument("--collections-dir", dest="collections_dir",
                        help="Directory holding _<collection> dirs (default: Jekyll's "
                             "top-level collections_dir, else the site root)")
    parser.add_argument("--front-matter-key", dest="front_matter_key",
                        help="Front-matter key to read/write (default: preview; "
                             "jekyll-seo-tag sites typically use image)")
    parser.add_argument("--authors-file", dest="authors_file",
                        help="Author-overrides YAML relative to the site root "
                             "(default: _data/authors.yml; pass '' to disable)")
    parser.add_argument("--batch", type=int, default=0,
                        help="Limit number of files processed (0 = no limit)")
    parser.add_argument("--log-file", help="Also write log output to a file")
    # Accepted for backward compatibility with the previous engine's CLI;
    # pacing is now handled by with_retries (Retry-After aware) + -j workers.
    parser.add_argument("--rate-limit", type=int, dest="rate_limit",
                        help=argparse.SUPPRESS)
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    args = build_arg_parser().parse_args(argv)
    # Historical flag semantics: these imply --enhance (--enhance-model does not).
    if args.enhance_prompt or args.enhance_fidelity or args.enhance_format:
        args.enhance = True
    return args


# Renderers that produce raster art, best first. `auto` walks this list before
# falling back to the SVG rungs.
AUTO_RASTER_ORDER: List[str] = ["openai", "xai", "stability", "gemini"]

# Env vars that constitute a real Claude credential. Deliberately NOT the same
# test as AnthropicClient.available(), which also accepts a `claude` binary on
# PATH: an installed CLI is not proof of a working login, and `auto` promoting
# an unauthenticated machine off the default rung would fail every page at
# generation time instead of quietly shipping the shared banner. An explicit
# `--provider claude` still rides the CLI, because that is a human asserting it
# works.
CLAUDE_CREDENTIAL_ENV: Tuple[str, ...] = (
    "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
)


def _claude_credential_wired(env: Dict[str, str]) -> bool:
    return any(env.get(name) for name in CLAUDE_CREDENTIAL_ENV)


def resolve_auto_provider(settings: Settings, env: Dict[str, str]) -> Settings:
    """Pick the best renderer the environment can actually reach.

    The ladder, best rung first:

      1. a raster image API (OPENAI/XAI/STABILITY/GEMINI key) — and if a Claude
         credential is ALSO present, `prompt_engine: claude` already has Claude
         write the art brief that renderer works from, and review the result;
      2. a Claude credential alone — Claude authors the banner as SVG, which is
         the one image format a language model can emit directly;
      3. nothing wired — one shared, deliberate banner per collection.

    Only `provider: auto` goes through this. An explicit provider is honored as
    written, so a site can always pin what it wants.
    """
    if settings.provider != "auto":
        return settings

    for name in AUTO_RASTER_ORDER:
        provider = PROVIDERS.get(name)
        if provider is not None and provider.is_configured(env):
            claude = " (Claude writes the brief)" if _claude_credential_wired(env) else ""
            info(f"provider: auto → {name}{claude}")
            return replace(settings, provider=name)

    if _claude_credential_wired(env):
        info("provider: auto → claude (no raster image key; Claude authors the SVG)")
        return replace(settings, provider="claude")

    info("provider: auto → default (no image credential wired; "
         "one shared banner per collection)")
    return replace(settings, provider="default")


def _degrade_llm(settings: Settings, ctx: RunContext) -> Settings:
    """Turn off Claude/Grok stages that have no credential, independently."""
    if settings.prompt_engine == "claude" or settings.review_engine == "claude":
        if ctx.claude().available():
            info(f"Claude orchestration: {ctx.claude().describe()}")
        else:
            warn(CLAUDE_CREDENTIAL_HINT)
            settings = replace(
                settings,
                prompt_engine=("template" if settings.prompt_engine == "claude"
                               else settings.prompt_engine),
                review_engine=("none" if settings.review_engine == "claude"
                               else settings.review_engine),
            )
    if settings.prompt_engine == "xai" or settings.review_engine == "xai":
        if ctx.grok_client().available():
            info(f"Grok orchestration: {ctx.grok_client().describe()}")
        else:
            warn(XAI_MISSING_HINT)
            settings = replace(
                settings,
                prompt_engine=("template" if settings.prompt_engine == "xai"
                               else settings.prompt_engine),
                review_engine=("none" if settings.review_engine == "xai"
                               else settings.review_engine),
            )
    return settings


def validate_credentials(settings: Settings, ctx: RunContext) -> None:
    """Credential checks are skipped for --list-missing/--dry-run (historical
    behavior), but an unknown provider name (from AI_PROVIDER / _config.yml —
    argparse already constrains -p) errors in every mode."""
    provider = PROVIDERS.get(settings.provider)
    if provider is None:
        error_exit(f"Unknown AI provider: {settings.provider}. "
                   f"Available: {', '.join(sorted(PROVIDERS))}")
    if settings.list_only or settings.dry_run:
        return
    if provider.name == "local":
        info("Using local provider - no API key required")
        return
    if not provider.is_configured(ctx.env):
        error_exit(provider.missing_hint(ctx.env))
    # Providers with more than one way in (xAI: OAuth token, then API key) say
    # which one this run picked, so a silent fallback is never a surprise.
    description = provider.auth_description(ctx.env)
    if description:
        info(f"{provider.name} auth: {description}")


def main(argv: Optional[List[str]] = None) -> int:
    global VERBOSE, _log_file

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    args = parse_args(argv)
    ensure_yaml()
    _load_dotenv()

    project_root = find_project_root()
    site_config = read_config(project_root)
    project_root = apply_source_root(project_root, site_config)
    settings = resolve_settings(args, site_config)
    VERBOSE = settings.verbose

    if args.log_file:
        try:
            _log_file = open(args.log_file, "w", encoding="utf-8")
            info(f"Logging to: {args.log_file}")
        except OSError as exc:
            warn(f"Cannot open log file: {exc}")

    explicitly_targeted = (
        settings.file or settings.collection or settings.enhance
        or settings.provider_explicit or args.inspect or args.shape
    )
    if not settings.enabled and not explicitly_targeted:
        info("preview_images.enabled is false in _config.yml — nothing to do "
             "(pass --provider, --file or --collection to override).")
        return 0

    if args.shape:
        target = Path(args.shape)
        if not target.is_file():
            error_exit(f"File not found: {args.shape}")
        real_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            report = shape_file(target, settings, project_root)
        finally:
            sys.stdout = real_stdout
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        return 0 if report["lint"]["clean"] else 1

    if args.inspect:
        ctx = RunContext(project_root=project_root, env=dict(os.environ))
        target = Path(args.inspect)
        if not target.is_file():
            error_exit(f"File not found: {args.inspect}")
        article = Path(settings.file) if settings.file else None
        # stdout carries exactly one JSON object; progress logging goes to stderr.
        real_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            report = inspect_banner(target, settings, ctx, article, critic=args.critic)
        finally:
            sys.stdout = real_stdout
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        return 0

    print_header("🎨 Preview Image Generator")
    ctx = RunContext(project_root=project_root, env=dict(os.environ))
    ctx.budget.cap_usd = settings.claude_budget_usd
    settings = resolve_auto_provider(settings, ctx.env)
    validate_credentials(settings, ctx)

    # LLM orchestration degrades gracefully: without a credential the run
    # continues on template prompts, unreviewed. Claude and Grok degrade
    # independently so a missing Claude token does not disable a Grok review.
    if (settings.provider not in ("local", "default")
            and not (settings.dry_run or settings.list_only)):
        settings = _degrade_llm(settings, ctx)

    output_dir = project_root / settings.output_dir
    if not settings.dry_run and not settings.list_only:
        output_dir.mkdir(parents=True, exist_ok=True)

    info("Configuration:")
    print(f"  AI Provider: {settings.provider}")
    print(f"  Image Model: {settings.model or PROVIDERS[settings.provider].default_model()}")
    print(f"  Output Dir: {settings.output_dir}")
    print(f"  Image Size: {settings.size}")
    print(f"  Parallel Workers: {settings.parallel}")
    print(f"  Dry Run: {str(settings.dry_run).lower()}")
    print(f"  Force: {str(settings.force).lower()}")
    print(f"  List Only: {str(settings.list_only).lower()}")
    print(f"  Prompt Engine: {settings.prompt_engine}")
    print(f"  Review: {settings.review_engine}")
    if settings.enhance:
        print("  Mode: ENHANCE (improve existing images)")
        print(f"  Enhance Model: {settings.enhance_model}")
        print(f"  Enhance Quality: {settings.enhance_quality}")
        print(f"  Input Fidelity: {settings.enhance_fidelity}")
        print(f"  Output Format: {settings.enhance_format}")
        if settings.enhance_prompt:
            print(f"  Custom Prompt: {settings.enhance_prompt[:80]}...")
        else:
            print("  Prompt: (default improvement prompt)")
    print()

    runner = Runner(settings, project_root, ctx=ctx)
    exit_code = runner.run()

    if _log_file:
        _log_file.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
