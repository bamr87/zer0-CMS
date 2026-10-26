"""Templates: an output schema's result → Markdown, an assistant's prompt.

Both are Django templates, rendered by a standalone engine with autoescaping
off (the output is Markdown, not HTML) and nothing to load: no template
libraries beyond the built-ins, no loaders, so a template a person wrote can
format the data it is given and do nothing else. A result with no template is
rendered generically — headings for keys, paragraphs for text, bullets for
lists — so no provider output is ever lost.
"""

import re

from django.core.exceptions import ValidationError
from django.template import Context, Engine, TemplateSyntaxError

ENGINE = Engine(autoescape=False, loaders=[], libraries={})
BLANK_LINES = re.compile(r"\n{3,}")


def check(template: str) -> None:
    """Raise ValidationError when `template` does not compile."""
    try:
        ENGINE.from_string(template or "")
    except TemplateSyntaxError as e:
        raise ValidationError(f"the template does not compile: {e}") from e


def render(template: str, context: dict) -> str:
    text = ENGINE.from_string(template).render(Context(context))
    return BLANK_LINES.sub("\n\n", text).strip()


def to_markdown(data, template: str = "") -> str:
    """A structured result as Markdown: through `template` when there is one."""
    if template:
        return render(template, data if isinstance(data, dict) else {"result": data})
    return "\n\n".join(_generic(data, 2)).strip()


def prompt(template: str, text: str, **context) -> str:
    """An assistant's prompt template filled with the request (`{{ prompt }}`)."""
    return render(template, {"prompt": text, **context}) if template else text


def _humanize(key: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(key)).replace("_", " ").strip().capitalize()


def _generic(value, level: int) -> list[str]:
    if isinstance(value, dict):
        out = []
        for key, sub in value.items():
            out.append(f"{'#' * min(level, 6)} {_humanize(key)}")
            out.extend(_generic(sub, level + 1))
        return out
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            return ["\n".join(f"- {v}" for v in value)] if value else []
        return [part for v in value for part in _generic(v, level)]
    return [str(value)] if value not in (None, "") else []
