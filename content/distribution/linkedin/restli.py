"""Rest.li 2.0 encoding, and the Posts API's `little` text format.

A URN inside a URL is percent-encoded (`urn:li:share:1` → `urn%3Ali%3Ashare%3A1`),
but the structural characters of a Rest.li value — `List(` `,` `)` and a
record's `(key:value)` — are not. So a value is either a plain string, which
`encode` escapes completely, or a `Raw` built by `listing` / `record`, inserted
as written.

`escape` turns commentary into LinkedIn's `little` format. Fifteen characters
are reserved — `| { } @ [ ] ( ) < > # \\ * _ ~` — and LinkedIn's documentation
says every one must be backslash-escaped to read as text; sent raw, the text
around one is misparsed (the classic symptom: a post cut off at its first
parenthesis). Two things an author writes on purpose stay elements: a hashtag
(`#` and letters or digits, not glued to a word — `#SmallBusiness` stays, `C#`
becomes `C\\#`) and a mention in LinkedIn's own syntax,
`@[Name](urn:li:person:…)` or `…(urn:li:organization:…)`.
"""

import re
from urllib.parse import quote


class Raw(str):
    """A Rest.li value already encoded, inserted into a URL as written."""


def encode(value) -> str:
    """RFC 3986 percent-encoding of every byte outside the unreserved set."""
    if isinstance(value, Raw):
        return str(value)
    return quote(str(value), safe="-._~")


def listing(values) -> Raw:
    """`List(urn%3Ali%3Ashare%3A1,urn%3Ali%3Ashare%3A2)`"""
    return Raw(f"List({','.join(encode(v) for v in values)})")


def record(pairs) -> Raw:
    """`(share:urn%3Ali%3Ashare%3A1)` — a Rest.li record with encoded values."""
    return Raw("(" + ",".join(f"{key}:{encode(value)}" for key, value in pairs) + ")")


def query(pairs) -> str:
    """`a=1&b=List(...)` from ordered pairs; None values are dropped."""
    return "&".join(f"{encode(key)}={encode(value)}" for key, value in pairs if value is not None)


# Letters and digits are `[^\W_]` (Python's word characters without the underscore).
LITTLE = re.compile(
    r"(?P<mention>@\[[^\[\]\n]{1,200}\]\(urn:li:(?:person|organization|organizationBrand):[A-Za-z0-9_-]+\))"
    r"|(?P<hashtag>(?<![^\W_])(?<!\\)#[^\W_]+)"
    r"|(?P<reserved>[|{}@\[\]()<>#\\*_~])"
)


def escape(text) -> str:
    return LITTLE.sub(lambda m: m.group("mention") or m.group("hashtag") or "\\" + m.group("reserved"), str(text or ""))
