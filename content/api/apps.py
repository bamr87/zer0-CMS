"""App config for `api`: GraphQL additions, REST endpoints, the GraphQL view."""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "api"
    verbose_name = "APIs"
    default_auto_field = "django.db.models.BigAutoField"
