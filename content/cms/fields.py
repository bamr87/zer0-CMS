"""`EmbeddingField`: one column type for vectors on every database.

On Postgres it is pgvector's `vector` (compose and CI run
`pgvector/pgvector:pg16`, and `graph`'s first migration creates the
extension); everywhere else it is JSON text. Values are plain lists of floats
in Python either way, so SQLite development and tests and Postgres production
share one migration (ADR 0001). The text form `[0.1,0.2]` is also pgvector's
input syntax, which is why one `get_prep_value` serves both.
"""

import json

from django.db import models


class EmbeddingField(models.Field):
    description = "A vector of floats (pgvector on Postgres, JSON text elsewhere)"

    def __init__(self, *args, dimensions=None, **kwargs):
        self.dimensions = dimensions
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        return name, path, args, kwargs

    def db_type(self, connection):
        if connection.vendor == "postgresql":
            return f"vector({self.dimensions})" if self.dimensions else "vector"
        return "text"

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            return [float(x) for x in json.loads(value)] if value.strip() else None
        return [float(x) for x in value]

    def get_prep_value(self, value):
        value = self.to_python(value)
        if value is None:
            return None
        return "[" + ",".join(repr(float(x)) for x in value) + "]"


class OrderedJSONField(models.TextField):
    """JSON stored as text, so key order survives on every database.

    Postgres' `jsonb` — what Django's `JSONField` uses there — sorts object
    keys, and front matter's key order is part of the file a person wrote. This
    keeps the JSON text as written (nested objects included), and gives Python
    a plain dict back.
    """

    description = "JSON that keeps key order (stored as text)"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default", dict)
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if value is None or isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            if not value.strip():
                return {}
            try:
                return json.loads(value)
            except ValueError as e:
                from django.core.exceptions import ValidationError

                raise ValidationError(f"not valid JSON: {e}") from e
        return value

    def get_prep_value(self, value):
        value = self.to_python(value)
        return None if value is None else json.dumps(value, ensure_ascii=False)

    def value_to_string(self, obj):
        return self.get_prep_value(self.value_from_object(obj))

    def formfield(self, **kwargs):
        from django import forms

        return super().formfield(**{"form_class": forms.JSONField, **kwargs})
