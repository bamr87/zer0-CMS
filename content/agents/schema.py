"""The content schema a model can read (note §2.1, M11).

`export()` walks every concrete page type under `cms.BasePage`, its editable
fields and its StreamField blocks, and emits JSON Schema: one definition per
block (help texts become descriptions), and per page type the fields an agent
may set and the shape of `body`. The result is versioned by its own hash —
`schema_version()` — and every `AgentRun` records the version it saw, so an
output that stops validating after a schema change can be traced to the
change (note §9, "StreamField JSON drift").

`manage.py wagtail_ai_schema` prints or writes it; the committed copy is
`schemas/content/ai-schema.json`, and a test fails when the two differ.
Tools validate block JSON with the blocks themselves (`validate_block`), not
with this schema: the schema tells a model what to write, `to_python` +
`clean` decide whether it is acceptable.
"""

import inspect
import json
from functools import lru_cache

from django.apps import apps
from django.core.exceptions import ValidationError
from wagtail import blocks
from wagtail.blocks.base import Block
from wagtail.images.blocks import ImageChooserBlock

from cms.models import BasePage, stable_hash

# The fields an agent may propose through `op: meta`, per page type. Anything
# else (slug, tree position, policy) is an editor's decision.
META_FIELDS = ("title", "seo_title", "search_description", "ai_summary", "ai_keywords")


def _description(block: Block) -> str | None:
    # A field block keeps its help text on its form field; a struct or stream
    # block keeps it in Meta.
    text = getattr(getattr(block, "field", None), "help_text", None) or getattr(block.meta, "help_text", None)
    return str(text) if text else None


def block_schema(block: Block) -> dict:
    schema: dict
    if isinstance(block, blocks.StreamBlock):
        schema = {
            "type": "array",
            "items": {"oneOf": [stream_child_schema(name, b) for name, b in block.child_blocks.items()]},
        }
    elif isinstance(block, blocks.StructBlock):
        props = {name: block_schema(b) for name, b in block.child_blocks.items()}
        required = [name for name, b in block.child_blocks.items() if getattr(b, "required", False)]
        schema = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    elif isinstance(block, blocks.ListBlock):
        schema = {"type": "array", "items": block_schema(block.child_block)}
    elif isinstance(block, blocks.ChoiceBlock):
        schema = {"type": "string", "enum": [str(k) for k, _ in block.field.choices if k != ""]}
    elif isinstance(block, blocks.BooleanBlock):
        schema = {"type": "boolean"}
    elif isinstance(block, blocks.IntegerBlock):
        schema = {"type": "integer"}
    elif isinstance(block, (blocks.FloatBlock, blocks.DecimalBlock)):
        schema = {"type": "number"}
    elif isinstance(block, (ImageChooserBlock, blocks.PageChooserBlock)):
        schema = {"type": "integer"} if block.required else {"type": ["integer", "null"]}
    elif isinstance(block, blocks.RichTextBlock):
        schema = {"type": "string", "contentMediaType": "text/html"}
    elif isinstance(block, blocks.RegexBlock):
        schema = {"type": "string", "pattern": block.field.regex.pattern}
    else:
        schema = {"type": "string"}
        max_length = getattr(getattr(block, "field", None), "max_length", None)
        if max_length:
            schema["maxLength"] = max_length
    description = _description(block)
    if description:
        schema["description"] = description
    return schema


def stream_child_schema(name: str, block: Block) -> dict:
    return {
        "type": "object",
        "title": name,
        "properties": {"type": {"const": name}, "value": {"$ref": f"#/$defs/blocks/{name}"}},
        "required": ["type", "value"],
        "additionalProperties": False,
    }


def summary(model) -> str:
    """A model docstring's first paragraph on one line. Whitespace is collapsed
    because Python 3.13 strips docstring indentation at compile time and 3.12
    does not, and the exported schema must not depend on the interpreter."""
    return " ".join(inspect.cleandoc(model.__doc__ or "").split("\n\n")[0].split())


def page_types():
    return sorted(
        (m for m in apps.get_models() if issubclass(m, BasePage) and not m._meta.abstract),
        key=lambda m: m._meta.label,
    )


def _field_schema(field) -> dict:
    internal = field.get_internal_type()
    schema = {
        "CharField": {"type": "string"},
        "TextField": {"type": "string"},
        "SlugField": {"type": "string"},
        "JSONField": {},
        "DateTimeField": {"type": "string", "format": "date-time"},
        "PositiveIntegerField": {"type": "integer", "minimum": 0},
    }.get(internal, {"type": "string"})
    if getattr(field, "max_length", None) and schema.get("type") == "string":
        schema["maxLength"] = field.max_length
    if field.help_text:
        schema["description"] = str(field.help_text)
    return dict(schema)


@lru_cache(maxsize=1)
def export() -> dict:
    body_block = BasePage._meta.get_field("body").stream_block
    defs = {name: block_schema(b) for name, b in body_block.child_blocks.items()}
    pages = {}
    for model in page_types():
        meta = {}
        for name in META_FIELDS:
            field = model._meta.get_field(name)
            meta[name] = (
                {"type": "array", "items": {"type": "string"}, "description": str(field.help_text)}
                if name == "ai_keywords"
                else _field_schema(field)
            )
        pages[model._meta.label] = {
            "description": summary(model),
            "meta_fields": meta,
            "body": {
                "type": "array",
                "items": {"oneOf": [stream_child_schema(n, b) for n, b in body_block.child_blocks.items()]},
            },
        }
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "zer0-CMS content schema for agents",
        "description": (
            "Block JSON an agent proposes must match this schema and is then validated by the blocks themselves. "
            "A body is a list of {type, value} blocks; `id` is assigned by the CMS."
        ),
        "$defs": {"blocks": defs},
        "pages": pages,
    }
    document["version"] = stable_hash(document)[:12]
    return document


def schema_version() -> str:
    return export()["version"]


def dumps(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class BlockInvalid(ValueError):
    pass


def validate_block(block_type: str, value):
    """Run a proposed block through the block itself. Returns the cleaned
    native value; raises `BlockInvalid` with the block's own messages."""
    body_block = BasePage._meta.get_field("body").stream_block
    child = body_block.child_blocks.get(block_type)
    if child is None:
        raise BlockInvalid(f"unknown block type {block_type!r}; known: {', '.join(body_block.child_blocks)}")
    try:
        native = child.to_python(value)
        return child.clean(native)
    except ValidationError as e:
        raise BlockInvalid(f"{block_type}: {_messages(e)}") from e
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        raise BlockInvalid(f"{block_type}: {type(e).__name__}: {e}") from e


def _messages(error: ValidationError) -> str:
    if hasattr(error, "block_errors") and error.block_errors:
        parts = []
        items = error.block_errors.items() if isinstance(error.block_errors, dict) else enumerate(error.block_errors)
        for key, sub in items:
            parts.append(f"{key}: {_messages(sub) if isinstance(sub, ValidationError) else sub}")
        return "; ".join(parts)
    return "; ".join(str(m) for m in error.messages)
