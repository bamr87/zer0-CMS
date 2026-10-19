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
StreamField is lossy").
"""

from wagtail import blocks
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

    class Meta:
        block_counts = {"brief": {"max_num": 1}}
