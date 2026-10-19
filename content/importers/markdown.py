"""A Markdown body as StreamField blocks, and back.

`to_blocks` cuts a body into sections: a fenced code block becomes a `code`
block, a plain ATX heading (`## Text`, levels 2–6, nothing but text) becomes a
`heading` block, and everything between them — paragraphs, lists, tables,
Liquid, includes, raw HTML, wikilinks — stays one `markdown` block, verbatim.
`from_blocks` writes them back joined by a blank line. A body whose sections
were separated by single blank lines comes back identical; anything else is
whitespace-normalised, which is why an *unchanged* page is exported from its
stored source instead (importers/models.py).
"""

import re

FENCE_OPEN = re.compile(r"^(```+|~~~+)[ \t]*([\w+#.-]*)[ \t]*$")
HEADING = re.compile(r"^(#{2,6})[ \t]+([^\n]+?)[ \t]*$")
PLAIN_HEADING = re.compile(r"^[^\[\]<>{}*`_|!#\\]+$")


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
            blocks.append({"type": "markdown", "value": text})
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


def block_to_markdown(block_type: str, value) -> str:
    if block_type == "markdown":
        return value
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
    return ""


def from_blocks(blocks, leading: str = "\n") -> str:
    """Raw StreamField data ({type, value}) → a Markdown body."""
    parts = [
        block_to_markdown(b["type"], b["value"]) for b in blocks if b["type"] not in ("brief", "letter", "page_link")
    ]
    text = "\n\n".join(p for p in parts if p)
    return f"{leading}{text}\n" if text else leading
