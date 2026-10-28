"""A Markdown body as StreamField blocks, and back.

`to_blocks` cuts a body into sections: a fenced code block becomes a `code`
block, a plain ATX heading (`## Text`, levels 2–6, nothing but text) becomes a
`heading` block, and everything between them — paragraphs, lists, Liquid,
includes, raw HTML, wikilinks — stays one `markdown` block, verbatim. Within
that text, a paragraph one of the structured blocks writes back exactly as it
was becomes that block instead (`structured`):

| A paragraph that is …                                         | becomes      |
|---------------------------------------------------------------|--------------|
| a pipe table (`| a | b |`, then `|---|---|`)                  | `table`, or `typed_table` when a column holds only numbers |
| an Obsidian callout (`> [!note] Title`, every line quoted)    | `callout`    |
| one bare http(s) URL                                          | `embed`      |
| one link to a file a site serves as a document (`[t](x.pdf)`) | `document`   |
| an HTML block (it starts with a block-level tag or a comment) | `raw_html`   |
| a Liquid template (it starts and ends with a Liquid tag)      | `liquid`     |

"Exactly" is checked, not assumed: the value goes through the block's own
`to_python`, `clean` and `get_prep_value`, and only a paragraph whose
`block_to_markdown` is the paragraph itself is taken; anything else stays in
the Markdown block. A paragraph is cut only at a single blank line (`\\n\\n`
between two lines of text), so joining the blocks back with a blank line gives
the text they were cut from — the body's other whitespace stays inside the
Markdown blocks. `from_blocks` writes them back joined by a blank line. A body
whose sections were separated by single blank lines comes back identical;
anything else is whitespace-normalised, which is why an *unchanged* page is
exported from its stored source instead (importers/models.py).
"""

import re
from functools import cache

from django.conf import settings
from django.core.exceptions import ValidationError

FENCE_OPEN = re.compile(r"^(```+|~~~+)[ \t]*([\w+#.-]*)[ \t]*$")
HEADING = re.compile(r"^(#{2,6})[ \t]+([^\n]+?)[ \t]*$")
PLAIN_HEADING = re.compile(r"^[^\[\]<>{}*`_|!#\\]+$")
# A paragraph ends at a single blank line between two lines of text.
PARAGRAPH = re.compile(r"(?<=[^\n])\n\n(?=[^\n])")
RULE = re.compile(r"^\|(?:[ \t]*:?-+:?[ \t]*\|)+$")
PIPE = re.compile(r"(?<!\\)\|")
NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
CALLOUT = re.compile(r"^> ?\[!([A-Za-z][\w-]*)\]([+-]?)(?: (.*))?$")
URL = re.compile(r"^https?://\S+$")
LINK = re.compile(r"^\[([^\[\]\n]+)\]\(([^()\s]+)\)$")
# CommonMark's HTML blocks: a comment, the raw-text elements, and the block-level tags (types 2, 1 and 6).
HTML_START = re.compile(
    r"^<(?:!--|/?(script|pre|style|textarea|address|article|aside|base|basefont|blockquote|body|caption|center|"
    r"col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|"
    r"head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|"
    r"search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:[\s/>]|$))",
    re.I,
)
LIQUID_TAG = re.compile(r"\{%-?\s*(\w+)")
LIQUID_BLOCKS = {"if", "unless", "for", "case", "capture", "comment", "raw", "tablerow", "highlight"}
LIQUID_VERBATIM = {"raw", "comment"}  # their contents are not tags


def _closes(line: str, marker: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(marker) and set(stripped) == {marker[0]}


def to_blocks(body: str) -> list[dict]:
    lines = body.split("\n")
    blocks: list[dict] = []
    buffer: list[str] = []

    def flush():
        text = "\n".join(buffer).strip("\n")
        if text.strip():
            blocks.extend(structured(text))
        buffer.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = FENCE_OPEN.match(line)
        if fence:
            marker = fence.group(1)
            j = i + 1
            while j < len(lines) and not _closes(lines[j], marker):
                j += 1
            code = "\n".join(lines[i + 1 : j])
            if j < len(lines) and code.strip():
                flush()
                blocks.append({"type": "code", "value": {"language": fence.group(2), "code": code}})
                i = j + 1
                continue
        heading = HEADING.match(line)
        if heading and PLAIN_HEADING.match(heading.group(2)) and len(heading.group(2)) <= 200:
            flush()
            blocks.append({"type": "heading", "value": {"level": str(len(heading.group(1))), "text": heading.group(2)}})
            i += 1
            continue
        buffer.append(line)
        i += 1
    flush()
    return blocks


# ── the structured blocks a paragraph can be ───────────────────────────────


def structured(text: str) -> list[dict]:
    """A Markdown section as blocks: each paragraph a structured block writes
    back exactly is that block, and the paragraphs between them stay Markdown."""
    paragraphs = PARAGRAPH.split(text)
    out: list[dict] = []
    plain: list[str] = []
    i = 0
    while i < len(paragraphs):
        taken, block = _liquid(paragraphs, i) if _starts_liquid(paragraphs[i]) else (1, _block(paragraphs[i]))
        if block is None:
            plain.append(paragraphs[i])
            i += 1
            continue
        if plain:
            out.append({"type": "markdown", "value": "\n\n".join(plain)})
            plain = []
        out.append(block)
        i += taken
    if plain:
        out.append({"type": "markdown", "value": "\n\n".join(plain)})
    return out


def _block(text: str) -> dict | None:
    if text != text.strip():
        return None  # the blocks' fields strip their text: it would not come back as it was
    lines = text.split("\n")
    if text.startswith("|"):
        return _table(lines, text)
    if (match := CALLOUT.match(lines[0])) and all(line.startswith(">") for line in lines):
        body = "\n".join(line[2:] if line.startswith("> ") else line[1:] for line in lines[1:])
        value = {"kind": match.group(1), "fold": match.group(2), "title": match.group(3) or "", "body": body}
        return _exact("callout", value, text)
    if URL.match(text):
        return _exact("embed", text, text)
    if (match := LINK.match(text)) and match.group(2).split("?")[0].split("#")[0].lower().endswith(_documents()):
        return _exact("document", {"title": match.group(1), "href": match.group(2), "document": None}, text)
    if (match := HTML_START.match(text)) and _html_ends(match.group(1), text):
        return _exact("raw_html", text, text)
    return None


def _html_ends(tag: str | None, text: str) -> bool:
    """An HTML block that ends inside this paragraph: a block-level tag's ends at
    the blank line, a comment's and a raw-text element's at their closing."""
    if text.startswith("<!--"):
        return "-->" in text
    if tag and tag.lower() in ("script", "pre", "style", "textarea"):
        return f"</{tag.lower()}>" in text.lower()
    return True


def _cells(row: str) -> list[str] | None:
    if not row.endswith("|") or row.endswith("\\|"):
        return None
    return [cell.strip() for cell in PIPE.split(row)[1:-1]]


def _table(lines: list[str], text: str) -> dict | None:
    if len(lines) < 2 or not RULE.match(lines[1]):
        return None
    rows = [_cells(line) for line in lines[:1] + lines[2:]]
    width = len(rows[0] or [])
    if not width or any(row is None or len(row) != width for row in rows):
        return None
    body = rows[1:]
    numeric = [bool(body) and all(NUMBER.match(row[c]) for row in body) for c in range(width)]
    if any(numeric):
        value = {
            "columns": [
                {"type": "number" if n else "text", "heading": h} for n, h in zip(numeric, rows[0], strict=True)
            ],
            "rows": [{"values": row} for row in body],
            "caption": "",
        }
        return _exact("typed_table", value, text)
    value = {
        "data": rows,
        "first_row_is_table_header": True,
        "first_col_is_header": False,
        "table_caption": "",
        "table_header_choice": "row",
    }
    return _exact("table", value, text)


def _starts_liquid(text: str) -> bool:
    return text.startswith(("{%", "{{"))


def _liquid(paragraphs: list[str], start: int) -> tuple[int, dict | None]:
    """A Liquid template from `paragraphs[start]`: through the paragraph that
    closes every block tag it opens (a `{% capture %}` can hold blank lines),
    ending on a tag or an output. (1, None) when there is none."""
    depth, verbatim = 0, None
    for end in range(start, len(paragraphs)):
        for tag in LIQUID_TAG.findall(paragraphs[end]):
            if verbatim is not None:
                verbatim = None if tag == f"end{verbatim}" else verbatim
                depth -= verbatim is None
            elif tag in LIQUID_BLOCKS:
                depth += 1
                verbatim = tag if tag in LIQUID_VERBATIM else None
            elif tag.startswith("end") and tag[3:] in LIQUID_BLOCKS:
                depth -= 1
            if depth < 0:
                return 1, None
        if depth == 0:
            text = "\n\n".join(paragraphs[start : end + 1])
            if text.rstrip().endswith(("%}", "}}")) and text == text.strip():
                return end - start + 1, _exact("liquid", text, text)
            return 1, None
    return 1, None


@cache
def _documents() -> tuple[str, ...]:
    return tuple(f".{ext}" for ext in settings.WAGTAILDOCS_EXTENSIONS)


def _exact(block_type: str, value, text: str) -> dict | None:
    """The block, as the platform stores it, when it writes `text` back; else None."""
    from cms.models import BasePage

    child = BasePage._meta.get_field("body").stream_block.child_blocks[block_type]
    try:
        stored = child.get_prep_value(child.clean(child.to_python(value)))
    except (ValidationError, TypeError, ValueError, KeyError):
        return None
    return {"type": block_type, "value": stored} if block_to_markdown(block_type, stored) == text else None


# ── blocks → Markdown ──────────────────────────────────────────────────────


def _row(cells) -> str:
    return "| " + " | ".join(PIPE.sub(r"\\|", str(cell or "").replace("\n", " ")) for cell in cells) + " |"


def _pipe_table(header, rows) -> str:
    return "\n".join([_row(header), "|" + "---|" * len(header), *(_row(row) for row in rows)])


def block_to_markdown(block_type: str, value) -> str:
    if block_type in ("markdown", "embed", "raw_html", "liquid"):
        return str(value or "")
    if block_type == "heading":
        return "#" * int(value["level"]) + " " + value["text"]
    if block_type == "code":
        return f"```{value.get('language') or ''}\n{value['code']}\n```"
    if block_type == "paragraph":
        return re.sub(r"<[^>]+>", "", str(value))
    if block_type == "quote":
        quote = "\n".join("> " + line for line in str(value["text"]).split("\n"))
        return quote + (f"\n>\n> — {value['attribution']}" if value.get("attribution") else "")
    if block_type == "image":
        return f"![{value.get('alt') or ''}]({value.get('url', '')})"
    if block_type == "document":
        return f"[{value.get('title') or ''}]({value.get('href') or ''})"
    if block_type == "callout":
        head = f"> [!{value['kind']}]{value.get('fold') or ''}" + (f" {value['title']}" if value.get("title") else "")
        body = value.get("body") or ""
        return head + "".join(f"\n> {line}" if line else "\n>" for line in (body.split("\n") if body else []))
    if block_type == "table":
        data = value.get("data") or [[]]
        return _pipe_table(data[0], data[1:])
    if block_type == "typed_table":
        header = [column["heading"] for column in value.get("columns") or []]
        return _pipe_table(header, [row["values"] for row in value.get("rows") or []])
    return ""


def from_blocks(blocks, leading: str = "\n") -> str:
    """Raw StreamField data ({type, value}) → a Markdown body."""
    parts = [
        block_to_markdown(b["type"], b["value"]) for b in blocks if b["type"] not in ("brief", "letter", "page_link")
    ]
    text = "\n\n".join(p for p in parts if p)
    return f"{leading}{text}\n" if text else leading
