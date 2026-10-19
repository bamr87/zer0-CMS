"""Front matter in and out, with dates kept as strings.

PyYAML would turn `date: 2026-07-31 10:00:00 -0500` into a `datetime`, and a
round trip through it is how a CMS silently shifts a published timestamp by a
timezone (AGENTS.md, the extension's rule). The loader and dumper here have no
timestamp resolver, so a date is a string in and the same string out; the
typed `ArticlePage.date` is parsed separately (`parse_date`) and only replaces
the string when an editor changed it.
"""

import re
from datetime import UTC, datetime

import yaml

FENCE = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n?", re.S | re.M)


class _Loader(yaml.SafeLoader):
    pass


class _Dumper(yaml.SafeDumper):
    pass


for cls in (_Loader, _Dumper):
    cls.yaml_implicit_resolvers = {
        key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


def _str_presenter(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str_presenter)


def split(text: str) -> tuple[dict | None, str]:
    """(front matter or None, body). A file without a leading fence has none."""
    match = FENCE.match(text)
    if not match:
        return None, text
    data = yaml.load(match.group(1), Loader=_Loader) or {}  # noqa: S506 — _Loader is a SafeLoader
    if not isinstance(data, dict):
        return None, text
    return data, text[match.end() :]


def dump(data: dict) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10_000, default_flow_style=False)


def join(data: dict, body: str) -> str:
    return f"---\n{dump(data)}---\n{body}"


DATE_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


def parse_date(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+0000")
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S %z")
