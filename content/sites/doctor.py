"""zer0 doctor: is a site's repository consistent with the platform's contract?
(PLAN G4; ADR 0006 decisions 4 and 8.)

The Python port of the Rails catalog's doctor (`rails/bin/zer0-cms doctor`).
Six checks, each a list of findings in lifehacker.dev's `findings.jsonl` shape
(`check_id, severity, file, line, rule, evidence, fingerprint`, the fingerprint
`sha1("check_id|rule|file|evidence")[:12]`), so the same triage tooling reads
them:

| check        | error when                                              | warning when |
|--------------|---------------------------------------------------------|--------------|
| config       | `_config.yml` unreadable, does not parse, not a mapping | — |
| image-engine | a vendored preview-generator fork exists                | no `preview_images:`; a Gemfile without the image generator |
| cms          | `zer0.json` invalid JSON(C), or a content folder missing | no `zer0.json`; no `$schema`; it breaks schemas/zer0.schema.json |
| fleet        | `fleet.manifest.yml` present but not strict YAML        | — |
| distribution | the `distribution.linkedin` block invalid, its ledger unreadable | a setting it does not know, a missing author or URL; a vendored per-site publisher |
| content      | a catalogued file whose front matter does not parse     | a field its content type (zer0.json) requires is empty |

What changed from the Ruby doctor, and why (ADR 0006 decision 4: the theme
leaves this repository and no doctor rule may name it):

* the `theme` check's two theme rules are gone — `theme-not-zer0` (an error
  unless `_config.yml` names the theme) and `no-theme-overrides` (a warning
  without the theme's override file). Its third rule, `config-unreadable`, is
  generic and stays, as the `config` check;
* the content check no longer reads the theme's front-matter schema (the
  vendored copy, a site's own copy, or `--schema`): a required key is one the
  site's own content types declare (`zer0.json` `contentTypes[].fields[]`
  with `required: true`, resolved per file as the extension resolves them),
  and `zer0.json` itself is checked against schemas/zer0.schema.json. A site
  with no `zer0.json` has no required keys — the cms check already says so;
* a YAML or JSON syntax error's evidence is this parser's wording, so its
  text (and fingerprint) differs from libyaml's; its rule, file and line do not.

Every other rule is the Ruby doctor's, rule for rule and word for word, and
tests/sites/test_doctor.py holds it to the Ruby doctor's recorded findings on
every in-repo site. It needs PyYAML and jsonschema and nothing from Django:
`python -m sites.doctor PATH` (run from content/) is what `bin/zer0 doctor` and
the reusable `zer0-doctor.yml` run; `manage.py doctor` is the same inside the
platform, and a site's doctor job records its findings (sites/services.py).
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from . import catalog, frontmatter

CHECKS = ("config", "image-engine", "cms", "fleet", "distribution", "content")
SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "zer0.schema.json"
IMAGE_GEM = "zer0-image-generator"
PREVIEW_FORKS = (
    "_plugins/preview_image_generator.rb",
    "_plugins/preview_generator.rb",
    "scripts/lib/preview_generator.py",
)
# The per-site LinkedIn publisher the distribution lane replaced.
VENDORED_LINKEDIN = ("scripts/features/linkedin/posts.py", "scripts/features/linkedin/mcp_server.py")


@dataclass
class Report:
    root: Path
    findings: list = field(default_factory=list)
    content_types: int = 0

    @property
    def errors(self) -> int:
        return sum(f["severity"] == "error" for f in self.findings)

    @property
    def warnings(self) -> int:
        return sum(f["severity"] == "warning" for f in self.findings)

    @property
    def ok(self) -> bool:
        return self.errors == 0


def finding(check_id, severity, rule, evidence, *, file="", line=None) -> dict:
    stamp = hashlib.sha1(f"{check_id}|{rule}|{file}|{evidence}".encode(), usedforsecurity=False).hexdigest()[:12]
    return {
        "check_id": check_id,
        "severity": severity,
        "file": str(file),
        "line": line,
        "rule": rule,
        "evidence": str(evidence),
        "fingerprint": stamp,
    }


def run(root, *, today: date | None = None) -> Report:
    """Every check over the site at `root`; `today` dates LinkedIn's API-version window."""
    report = Report(root=Path(os.path.abspath(root)))
    config = check_config(report.root, report.findings)
    check_image_engine(report.root, config, report.findings)
    zer0 = check_cms(report.root, report.findings)
    check_fleet(report.root, report.findings)
    check_distribution(report.root, report.findings, today)
    report.content_types = check_content(report.root, zer0, report.findings)
    return report


# ── config ──────────────────────────────────────────────────────────────────


def check_config(root: Path, findings: list) -> dict | None:
    rel = "_config.yml"
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except OSError as e:
        code = errno.errorcode.get(e.errno or 0, type(e).__name__)
        findings.append(finding("config", "error", "config-unreadable", f"cannot read _config.yml: {code}", file=rel))
        return None
    except UnicodeDecodeError:
        findings.append(finding("config", "error", "config-unreadable", "_config.yml is not UTF-8", file=rel))
        return None
    try:
        loaded = yaml.load(text, Loader=frontmatter.Loader)  # noqa: S506 — a SafeLoader
    except yaml.MarkedYAMLError as e:
        evidence = f"_config.yml does not parse: {e.problem}"
        findings.append(
            finding("config", "error", "config-unreadable", evidence, file=rel, line=frontmatter.error_line(e))
        )
        return None
    except yaml.YAMLError as e:
        evidence = f"_config.yml does not load: {frontmatter.first_line(e)}"
        findings.append(finding("config", "error", "config-unreadable", evidence, file=rel))
        return None
    if not isinstance(loaded, dict):
        findings.append(finding("config", "error", "config-unreadable", "_config.yml is not a mapping", file=rel))
        return None
    return loaded


# ── image engine ────────────────────────────────────────────────────────────


def _preview_fork(path: Path) -> bool:
    """A candidate path is a fork only when it reads the image engine's own
    `preview_images` config: it-journey's `_plugins/preview_generator.rb` is a
    Front Matter CMS `/preview/` mirror that shares the filename and nothing else."""
    try:
        return path.is_file() and b"preview_images" in path.read_bytes()
    except OSError:
        return False


def check_image_engine(root: Path, config: dict | None, findings: list) -> None:
    for rel in PREVIEW_FORKS:
        if _preview_fork(root / rel):
            evidence = f"a vendored preview generator; use the {IMAGE_GEM} gem"
            findings.append(finding("image-engine", "error", "vendored-preview-fork", evidence, file=rel))
    if config is not None and not isinstance(config.get("preview_images"), dict):
        evidence = "no preview_images: block"
        findings.append(finding("image-engine", "warning", "no-preview-images-config", evidence, file="_config.yml"))
    gemfile = root / "Gemfile"
    if not gemfile.is_file():
        return
    if re.search(rf"^\s*gem\s+[\"']{re.escape(IMAGE_GEM)}[\"']", gemfile.read_text(errors="replace"), re.M):
        return
    evidence = f"Gemfile does not require {IMAGE_GEM}"
    findings.append(finding("image-engine", "warning", "gemfile-missing-image-generator", evidence, file="Gemfile"))


# ── cms ─────────────────────────────────────────────────────────────────────


def check_cms(root: Path, findings: list) -> dict | None:
    rel = "zer0.json"
    path = root / rel
    if not path.is_file():
        findings.append(finding("cms", "warning", "no-zer0-json", "no zer0.json", file=rel))
        return None
    try:
        data = jsonc_loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        evidence = f"zer0.json is not valid JSON(C): {str(e).splitlines()[0].strip()[:160]}"
        findings.append(finding("cms", "error", "zer0-json-invalid", evidence, file=rel))
        return None
    if not isinstance(data, dict):
        findings.append(finding("cms", "error", "zer0-json-invalid", "zer0.json is not an object", file=rel))
        return None
    schema = data.get("$schema")
    if not (isinstance(schema, str) and schema.strip()):
        findings.append(finding("cms", "warning", "zer0-json-no-schema", "zer0.json has no $schema", file=rel))
    folders = data.get("contentFolders") if isinstance(data.get("contentFolders"), list) else []
    for index, folder in enumerate(folders):
        folder_path = folder.get("path") if isinstance(folder, dict) else None
        if isinstance(folder_path, str) and not content_folder(root, folder_path).is_dir():
            evidence = f"contentFolders[{index}].path {folder_path} does not exist"
            findings.append(finding("cms", "error", "content-folder-missing", evidence, file=rel))
    for message in schema_problems(data):
        findings.append(finding("cms", "warning", "zer0-json-schema", message, file=rel))
    return data


def schema_problems(data: dict) -> list[str]:
    """Where `zer0.json` breaks schemas/zer0.schema.json, one sentence each."""
    import jsonschema

    validator = jsonschema.Draft7Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        problems.append(f"zer0.json {where}: {error.message[:200]}")
    return problems


def content_folder(root: Path, path: str) -> Path:
    """`[[workspace]]` is the site root; a `*` or `{{…}}` placeholder cuts the
    path back to the last directory that is literal."""
    text = path.replace("[[workspace]]", str(root))
    wild = re.search(r"\*|\{\{", text)
    if wild:
        text = re.sub(r"[^/]*\Z", "", text[: wild.start()])
    return Path(os.path.normpath(os.path.join(root, os.path.expanduser(text or "."))))


# JSON with comments and trailing commas (the zer0.json dialect): comments go
# first, kept as blank space so line numbers hold, then a comma before a
# closing bracket; strings are matched whole so neither is touched inside one.
_COMMENTS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[\]}])', re.S)


def jsonc_loads(text: str):
    text = text.removeprefix("\ufeff")
    text = _COMMENTS.sub(lambda m: m.group() if m.group().startswith('"') else re.sub(r"[^\n]", " ", m.group()), text)
    return json.loads(_TRAILING.sub(lambda m: m.group() if m.group().startswith('"') else "", text))


# ── fleet ───────────────────────────────────────────────────────────────────


class _StrictLoader(yaml.SafeLoader):
    """YAML with no aliases and nothing but strings, numbers, booleans, nulls,
    lists and mappings — what a manifest every tool reads the same way may hold."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.composer.ComposerError(None, None, f"alias *{event.anchor} is not allowed", event.start_mark)
        return super().compose_node(parent, index)

    def construct_undefined(self, node):
        raise yaml.constructor.ConstructorError(None, None, f"tag {node.tag} is not allowed", node.start_mark)


_StrictLoader.add_constructor("tag:yaml.org,2002:timestamp", _StrictLoader.construct_undefined)
_StrictLoader.add_constructor(None, _StrictLoader.construct_undefined)


def check_fleet(root: Path, findings: list) -> None:
    rel = "fleet.manifest.yml"
    path = root / rel
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 — a SafeLoader, stricter still
    except (yaml.scanner.ScannerError, yaml.parser.ParserError) as e:
        mark = e.context_mark or e.problem_mark
        evidence = f"not valid YAML: {e.problem} (column {mark.column + 1 if mark else 0})"
        findings.append(
            finding("fleet", "error", "fleet-manifest-invalid", evidence, file=rel, line=frontmatter.error_line(e))
        )
        return
    except yaml.YAMLError as e:
        evidence = f"not strict YAML: {e.problem if getattr(e, 'problem', None) else frontmatter.first_line(e)}"
        findings.append(finding("fleet", "error", "fleet-manifest-invalid", evidence, file=rel))
        return
    if not isinstance(data, dict):
        findings.append(finding("fleet", "error", "fleet-manifest-invalid", "top level is not a mapping", file=rel))
        return
    duplicate = _first_duplicate_key(yaml.compose(text, Loader=_StrictLoader))  # noqa: S506 — composing only
    if duplicate:
        key, line = duplicate
        evidence = f"duplicate key {json.dumps(key)}"
        findings.append(finding("fleet", "error", "fleet-manifest-invalid", evidence, file=rel, line=line))


def _first_duplicate_key(node):
    if node is None:
        return None
    if isinstance(node, yaml.MappingNode):
        seen = set()
        for key, _ in node.value:
            if isinstance(key, yaml.ScalarNode):
                if key.value in seen:
                    return key.value, key.start_mark.line + 1
                seen.add(key.value)
        children = [n for pair in node.value for n in pair]
    elif isinstance(node, yaml.SequenceNode):
        children = node.value
    else:
        return None
    for child in children:
        found = _first_duplicate_key(child)
        if found:
            return found
    return None


# ── distribution ────────────────────────────────────────────────────────────

LINKEDIN_KEYS = (
    "author",
    "siteUrl",
    "apiVersion",
    "queue",
    "ledger",
    "acceptStatuses",
    "sources",
    "fallbackImage",
    "hashtagLimit",
    "bannedPatternsFile",
    "scopes",
)
LINKEDIN_API_VERSION = "202608"
LINKEDIN_AUTHOR = re.compile(r"\Aurn:li:(person|organization|organizationBrand|share|ugcPost|image):([A-Za-z0-9_-]+)\Z")


class _ConfigError(Exception):
    pass


def _inspect(value) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else "nil" if value is None else str(value)


def _first(*values) -> str | None:
    for value in values:
        text = "" if value is None else str(value).strip()
        if text:
            return text
    return None


def _confined(value, key) -> str:
    """A repository-relative path that stays inside the repository."""
    text = str(value).strip().replace("\\", "/")
    if not text or text.startswith("/") or ".." in text.split("/") or re.match(r"[A-Za-z]:", text):
        raise _ConfigError(f"distribution.linkedin.{key} must be a path inside the repository, got {_inspect(value)}")
    return os.path.normpath(text)


def _version_status(version: str, today: date) -> str:
    match = re.fullmatch(r"(\d{4})(\d{2})", version)
    if not match or not 1 <= int(match.group(2)) <= 12:
        return "invalid"
    age = (today.year * 12 + today.month) - (int(match.group(1)) * 12 + int(match.group(2)))
    if age < 0:
        return "future"
    return "sunset" if age >= 12 else "aging" if age >= 10 else "ok"


def _linkedin_problems(root: Path, today: date):
    """(configured, [(severity, message)], ledger path) for `zer0.json`'s
    `distribution.linkedin` block, as the distribution lane reads it with no
    environment: the doctor reports what the repository says."""
    problems = []
    try:
        zer0 = jsonc_loads((root / "zer0.json").read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        problems.append(("error", f"zer0.json does not parse: {str(e).splitlines()[0].strip()}"))
        zer0 = {}
    zer0 = zer0 if isinstance(zer0, dict) else {}
    distribution = zer0.get("distribution")
    block = distribution.get("linkedin") if isinstance(distribution, dict) else None
    block = block if isinstance(block, dict) else {}
    cms = zer0.get("cms")
    site = {}
    if (root / "_config.yml").is_file():
        try:
            loaded = yaml.load((root / "_config.yml").read_text(encoding="utf-8"), Loader=frontmatter.Loader)  # noqa: S506
            site = loaded if isinstance(loaded, dict) else {}
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            problems.append(("error", f"_config.yml does not parse: {frontmatter.first_line(e)}"))
    jekyll_linkedin = site.get("linkedin") if isinstance(site.get("linkedin"), dict) else {}
    url = str(site.get("url") or "").strip()
    jekyll_url = f"{url.rstrip('/')}{str(site.get('baseurl') or '').strip().rstrip('/')}" if url else None
    author = _first(block.get("author"), jekyll_linkedin.get("org_urn"))
    site_url = (_first(block.get("siteUrl"), jekyll_url) or "").rstrip("/")
    api_version = _first(block.get("apiVersion"), LINKEDIN_API_VERSION) or ""
    # In the lane's order, so the first path it would refuse is the one reported.
    _confined(block.get("queue") or ".zer0/drafts/linkedin", "queue")
    ledger = _confined(block.get("ledger") or ".zer0/ledger.json", "ledger")
    for key in ("fallbackImage", "bannedPatternsFile"):
        if block.get(key):
            _confined(block[key], key)
    _confined((cms.get("root") if isinstance(cms, dict) else None) or ".cms", "cms.root")
    accept = block.get("acceptStatuses")
    accept = ["approved"] if accept is None or accept is False else accept if isinstance(accept, list) else [accept]
    accept = [str(s).strip().lower() for s in accept]

    for key in block:
        if key not in LINKEDIN_KEYS:
            problems.append(
                ("warning", f"distribution.linkedin.{key} is not a setting (known: {', '.join(LINKEDIN_KEYS)})")
            )
    match = LINKEDIN_AUTHOR.match(author or "")
    if not author:
        problems.append(("warning", "no LinkedIn author: set distribution.linkedin.author in zer0.json"))
    elif not (match and match.group(1) in ("person", "organization")):
        problems.append(
            ("error", f"author must be urn:li:organization:{{id}} or urn:li:person:{{id}}, got {_inspect(author)}")
        )
    status = _version_status(api_version, today)
    if status == "invalid":
        problems.append(("error", f"apiVersion must be YYYYMM, got {_inspect(api_version)}"))
    elif status == "sunset":
        problems.append(
            (
                "error",
                f"LinkedIn-Version {api_version} is past LinkedIn's twelve-month support window; LinkedIn rejects it",
            )
        )
    elif status == "aging":
        problems.append(
            (
                "warning",
                f"LinkedIn-Version {api_version} leaves LinkedIn's support window within two months; bump apiVersion",
            )
        )
    elif status == "future":
        problems.append(("error", f"LinkedIn-Version {api_version} is in the future"))
    if not site_url:
        problems.append(
            (
                "warning",
                "no site URL: set url in _config.yml or distribution.linkedin.siteUrl — article shares need one",
            )
        )
    elif not re.match(r"https?://[^\s/]+", site_url):
        problems.append(("error", f"siteUrl must be an absolute http(s) URL, got {_inspect(site_url)}"))
    for status_name in accept:
        if status_name not in ("pending", "approved"):
            problems.append(("error", f"acceptStatuses may hold pending and approved, not {_inspect(status_name)}"))
    if not accept:
        problems.append(("error", "acceptStatuses is empty — nothing could ever publish"))
    elif "approved" not in accept:
        problems.append(
            (
                "warning",
                "acceptStatuses has no approved: nothing can publish outside a merged run on the default branch",
            )
        )
    return bool(block), problems, ledger


def check_distribution(root: Path, findings: list, today: date | None = None) -> None:
    vendored = next((rel for rel in VENDORED_LINKEDIN if (root / rel).is_file()), None)
    if vendored:
        evidence = "a per-site LinkedIn publisher; zer0-cms linkedin replaces it"
        findings.append(finding("distribution", "warning", "vendored-linkedin-publisher", evidence, file=vendored))
    if not (root / "zer0.json").is_file():
        return
    try:
        configured, problems, ledger = _linkedin_problems(root, today or date.today())
    except _ConfigError as e:
        findings.append(finding("distribution", "error", "distribution-config-invalid", str(e), file="zer0.json"))
        return
    if not configured:
        return
    for severity, message in problems:
        rule = "distribution-config-invalid" if severity == "error" else "distribution-config"
        findings.append(finding("distribution", severity, rule, message, file="zer0.json"))
    path = root / ledger
    if path.is_file():
        try:
            readable = isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
        except (ValueError, OSError):
            readable = False
        if not readable:
            evidence = f"{ledger} is not valid JSON"
            findings.append(finding("distribution", "error", "distribution-ledger-unreadable", evidence, file=ledger))


# ── content ─────────────────────────────────────────────────────────────────


def check_content(root: Path, zer0: dict | None, findings: list) -> int:
    """Front matter that does not parse is an error; an empty field the file's
    content type requires is a warning. Returns how many content types applied."""
    try:
        result = catalog.scan(root)
    except catalog.UnsafePath as e:
        findings.append(finding("content", "error", "unsafe-path", str(e), file="_config.yml"))
        return 0
    types = content_types(zer0)
    folders = [
        (content_folder(root, f["path"]), f.get("contentTypes") or [])
        for f in (zer0 or {}).get("contentFolders") or []
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    ]
    for entry in result.entries:
        if entry.error and entry.error.startswith("front matter:"):
            evidence = entry.error
            findings.append(
                finding(
                    "content", "error", "front-matter-invalid", evidence, file=entry.relative, line=entry.error_line
                )
            )
            continue
        ctype = resolve_type(types, folders, entry)
        if ctype is None:
            continue
        for key in missing_fields(ctype.get("fields") or [], entry.data):
            evidence = f"{ctype['name']} requires {key}"
            findings.append(finding("content", "warning", f"missing-key:{key}", evidence, file=entry.relative))
    return len(types)


def content_types(zer0: dict | None) -> list[dict]:
    """The site's content types, or none when it has no zer0.json or switched validation off."""
    if not isinstance(zer0, dict):
        return []
    validation = zer0.get("validation")
    if isinstance(validation, dict) and validation.get("enabled") is False:
        return []
    types = zer0.get("contentTypes")
    return (
        [t for t in types if isinstance(t, dict) and isinstance(t.get("name"), str)] if isinstance(types, list) else []
    )


def resolve_type(types: list[dict], folders: list, entry) -> dict | None:
    """The extension's chain (src/core/content/contentType.ts): the file's own
    `type`, the folder's one bound type, the only type, the type named
    `default` — else the built-in one, which requires nothing."""
    by_name = {t["name"]: t for t in types}
    declared = entry.data.get("type")
    if isinstance(declared, str) and declared in by_name:
        return by_name[declared]
    owning = [(len(str(d)), bound) for d, bound in folders if entry.path.startswith(str(d).rstrip("/") + "/")]
    if owning:
        bound = max(owning, key=lambda pair: pair[0])[1]
        if isinstance(bound, list) and len(bound) == 1 and bound[0] in by_name:
            return by_name[bound[0]]
    if len(types) == 1:
        return types[0]
    return by_name.get("default")


def missing_fields(fields: list, data, parents: tuple = ()) -> list[str]:
    """Every required field that is empty, depth-first in declaration order; a
    `fields` group is walked against its own sub-mapping. A field shown only
    `when` something holds is not checked (the doctor does not evaluate the clause)."""
    out = []
    data = data if isinstance(data, dict) else {}
    for f in fields:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or "when" in f:
            continue
        name = ".".join((*parents, f["name"]))
        value = data.get(f["name"])
        if f.get("type") == "fields" and isinstance(f.get("fields"), list):
            out += missing_fields(f["fields"], value, (*parents, f["name"]))
        elif f.get("required") is True and (value is None or (hasattr(value, "__len__") and len(value) == 0)):
            out.append(name)
    return out


# ── output ──────────────────────────────────────────────────────────────────


def to_jsonl(report: Report) -> str:
    return "\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in report.findings)


def to_text(report: Report) -> str:
    types = f"{report.content_types} from zer0.json" if report.content_types else "none (no zer0.json content types)"
    out = [f"zer0 doctor: {report.root}", f"  content types: {types}"]
    for check in CHECKS:
        mine = [f for f in report.findings if f["check_id"] == check]
        errors = sum(f["severity"] == "error" for f in mine)
        warnings = sum(f["severity"] == "warning" for f in mine)
        out.append(f"  {check.ljust(13)} {'ok' if not mine else f'{errors} error(s), {warnings} warning(s)'}")
        for f in mine:
            if check == "content" and f["severity"] == "warning":
                continue
            where = (f" {f['file']}" + (f":{f['line']}" if f["line"] else "")) if f["file"] else ""
            out.append(f"    {'ERROR' if f['severity'] == 'error' else 'warn '} {f['rule']}{where} — {f['evidence']}")
        by_rule: dict[str, int] = {}
        for f in mine:
            if check == "content" and f["severity"] == "warning":
                by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1
        for rule, count in sorted(by_rule.items(), key=lambda item: (-item[1], item[0])):
            out.append(f"    warn  {rule.ljust(28)} {count} file(s)")
    out.append(f"result: {report.errors} error(s), {report.warnings} warning(s)")
    return "\n".join(out)


def main(argv=None, stdout=None) -> int:
    """`python -m sites.doctor PATH [--format text|findings]`: exit 1 on any error, 2 on bad usage."""
    stdout = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="zer0 doctor", description=__doc__.splitlines()[0])
    parser.add_argument("path", help="the site's root (the directory holding _config.yml)")
    parser.add_argument("--format", choices=["text", "findings"], default="text")
    options = parser.parse_args(argv)
    if not os.path.isdir(options.path):
        parser.error(f"{options.path} is not a directory")
    report = run(options.path)
    text = to_jsonl(report) if options.format == "findings" else to_text(report)
    if text:
        print(text, file=stdout)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
