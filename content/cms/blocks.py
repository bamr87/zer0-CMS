"""The StreamField blocks every page body is made of.

This is the schema an agent writes against: `manage.py wagtail_ai_schema`
exports it as JSON Schema (agents/schema.py), the content tools validate
every proposed block with `to_python` + `clean` before it can become a
Suggestion, and the help texts below become the schema's descriptions — so
they are written for a model to read as much as for an editor.

`MarkdownBlock` is the lossless one. A Jekyll body carries Liquid tags,
includes, raw HTML and Obsidian wikilinks that no structured block can hold
without changing them, so the importer keeps each such chunk as Markdown,
verbatim, and the exporter writes it back byte for byte (PLAN §7, "Markdown →
StreamField is lossy"). A paragraph that one of the blocks below writes back
exactly as it was becomes that block instead (importers/markdown.py): a pipe
table (`table`, or `typed_table` when a column holds only numbers), an
Obsidian callout, a bare URL (`embed`), a link to a file (`document`), an
HTML block (`raw_html`) or a Liquid template (`liquid`).

The platform is headless and never reaches the network in a request: an
`embed` is checked as a URL, not fetched, and the editor's preview shows an
embed, raw HTML and Liquid as their source — the site's own build renders them.
"""

from django.utils.html import format_html
from wagtail import blocks
from wagtail.contrib.table_block.blocks import TableBlock
from wagtail.contrib.typed_table_block.blocks import TypedTableBlock
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.embeds.blocks import EmbedBlock as WagtailEmbedBlock
from wagtail.images.blocks import ImageChooserBlock

HEADING_LEVELS = [("2", "H2"), ("3", "H3"), ("4", "H4"), ("5", "H5"), ("6", "H6")]


class MarkdownBlock(blocks.TextBlock):
    class Meta:
        icon = "doc-full"
        label = "Markdown"
        help_text = (
            "A chunk of Markdown kept verbatim: paragraphs, lists, tables, Liquid tags, includes, raw HTML "
            "and [[wikilinks]] are all allowed and are never rewritten."
        )


class HeadingBlock(blocks.StructBlock):
    level = blocks.ChoiceBlock(choices=HEADING_LEVELS, default="2", help_text="Heading level, 2 to 6.")
    text = blocks.CharBlock(max_length=200, help_text="The heading text, plain, without leading #.")

    class Meta:
        icon = "title"
        label = "Heading"


class ParagraphBlock(blocks.RichTextBlock):
    def __init__(self, **kwargs):
        kwargs.setdefault("features", ["bold", "italic", "link", "ol", "ul", "code"])
        kwargs.setdefault(
            "help_text", "Rich text as Wagtail's HTML subset: <p>, <b>, <i>, <a href>, <ol>, <ul>, <li>, <code>."
        )
        super().__init__(**kwargs)

    class Meta:
        icon = "pilcrow"
        label = "Paragraph"


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock(help_text="The id of an image in the image library.")
    alt = blocks.CharBlock(required=False, max_length=250, help_text="Alternative text; empty only if decorative.")
    caption = blocks.CharBlock(required=False, max_length=250, help_text="Visible caption.")

    class Meta:
        icon = "image"
        label = "Image"


class CodeBlock(blocks.StructBlock):
    language = blocks.CharBlock(required=False, max_length=40, help_text="Fence language, e.g. python, bash, yaml.")
    code = blocks.TextBlock(help_text="The code, verbatim.")

    class Meta:
        icon = "code"
        label = "Code"


class QuoteBlock(blocks.StructBlock):
    text = blocks.TextBlock(help_text="The quotation, plain text.")
    attribution = blocks.CharBlock(required=False, max_length=200, help_text="Who said it.")

    class Meta:
        icon = "openquote"
        label = "Quote"


class PageLinkBlock(blocks.StructBlock):
    page = blocks.PageChooserBlock(help_text="The id of the page to link to.")
    text = blocks.CharBlock(required=False, max_length=200, help_text="Link text; defaults to the page title.")

    class Meta:
        icon = "link"
        label = "Page link"


class BriefBlock(blocks.StructBlock):
    """What an editor writes before asking the drafter for a first draft."""

    topic = blocks.CharBlock(max_length=250, help_text="What the piece is about, in one line.")
    audience = blocks.CharBlock(required=False, max_length=250, help_text="Who it is for.")
    notes = blocks.TextBlock(required=False, help_text="Points to cover, sources, tone, length.")

    class Meta:
        icon = "help"
        label = "Brief"


class LetterBlock(blocks.StructBlock):
    """One plate of an ABC book: the letter, its word, the read-aloud line and
    the text-free art subject the illustrator draws (the ABC Book Spec)."""

    letter = blocks.RegexBlock(regex=r"^[A-Z]$", max_length=1, help_text="One capital letter, A to Z.")
    word = blocks.CharBlock(max_length=80, help_text="The word the letter stands for.")
    tagline = blocks.CharBlock(max_length=250, help_text="The line a grown-up reads aloud.")
    subject = blocks.CharBlock(
        required=False, max_length=400, help_text="A concrete, drawable scene with no text in it, for the art model."
    )
    alt = blocks.CharBlock(required=False, max_length=250, help_text="Accessible description of the intended plate.")
    image = ImageChooserBlock(required=False, help_text="The drawn plate, once it exists.")

    class Meta:
        icon = "pick"
        label = "Letter"


class EmbedBlock(WagtailEmbedBlock):
    """Wagtail's embed, checked as a URL rather than fetched: saving a page
    never reaches a provider, and the preview links to it."""

    def __init__(self, **kwargs):
        kwargs.setdefault("help_text", "The address of a video, post or other page to embed, e.g. a YouTube URL.")
        super().__init__(**kwargs)

    def clean(self, value):
        return blocks.URLBlock.clean(self, value)

    def render_basic(self, value, context=None):
        return format_html('<p><a href="{0}">{0}</a></p>', value.url) if value else ""

    class Meta:
        icon = "media"
        label = "Embed"


class DocumentBlock(blocks.StructBlock):
    """A link to a file — a PDF, a spreadsheet — written as `[title](href)`."""

    title = blocks.CharBlock(max_length=250, help_text="The link text.")
    href = blocks.CharBlock(
        max_length=500,
        help_text="Where the site serves the file, e.g. /assets/files/report.pdf, or its full URL.",
    )
    document = DocumentChooserBlock(required=False, help_text="The file in the document library, when it is there.")

    class Meta:
        icon = "doc-full-inverse"
        label = "Document"


class RawHTMLBlock(blocks.RawHTMLBlock):
    """HTML the site renders as it is (Liquid inside it included); the preview shows its source."""

    def __init__(self, **kwargs):
        kwargs.setdefault("help_text", "An HTML block, verbatim: the site's build renders it.")
        super().__init__(**kwargs)

    def render_basic(self, value, context=None):
        return format_html("<pre>{}</pre>", value)

    class Meta:
        icon = "code"
        label = "Raw HTML"


class LiquidBlock(blocks.TextBlock):
    class Meta:
        icon = "cogs"
        label = "Liquid"
        help_text = "A Liquid template — an include, a loop, a capture — verbatim: the site's build evaluates it."


class CalloutBlock(blocks.StructBlock):
    """An Obsidian callout: `> [!kind]± title`, then its body, each line quoted."""

    kind = blocks.RegexBlock(
        regex=r"^[A-Za-z][\w-]*$", max_length=40, help_text="note, tip, warning, quote … as written, e.g. NOTE."
    )
    fold = blocks.ChoiceBlock(
        choices=[("+", "foldable, open"), ("-", "foldable, closed")],
        required=False,
        help_text="Empty: not foldable.",
    )
    title = blocks.CharBlock(required=False, help_text="The callout's title; empty uses its kind.")
    body = blocks.TextBlock(required=False, help_text="The callout's Markdown, without the > quoting.")

    class Meta:
        icon = "warning"
        label = "Callout"


class TypedTable(TypedTableBlock):
    text = blocks.CharBlock(required=False, help_text="Text, Markdown allowed.")
    number = blocks.RegexBlock(
        regex=r"^-?\d+(\.\d+)?$",
        error_messages={"invalid": "a number column takes numbers, e.g. 21 or -3.5"},
        help_text="A number as written, e.g. 21 or -3.5.",
    )

    class Meta:
        icon = "table"
        label = "Typed table"
        help_text = "A table whose columns each hold text or numbers; written as a Markdown pipe table."


class BodyBlock(blocks.StreamBlock):
    markdown = MarkdownBlock()
    heading = HeadingBlock()
    paragraph = ParagraphBlock()
    image = ImageBlock()
    code = CodeBlock()
    quote = QuoteBlock()
    page_link = PageLinkBlock()
    brief = BriefBlock()
    letter = LetterBlock()
    embed = EmbedBlock()
    document = DocumentBlock()
    table = TableBlock(
        help_text="A Markdown pipe table: `data` is its rows of cells, the first row its header.",
        icon="table",
        label="Table",
    )
    typed_table = TypedTable()
    raw_html = RawHTMLBlock()
    liquid = LiquidBlock()
    callout = CalloutBlock()

    class Meta:
        block_counts = {"brief": {"max_num": 1}}
