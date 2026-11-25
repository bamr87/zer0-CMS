"""`/api/v2/switches/` (switches/views.py); included from config/urls.py and, for the OpenAPI document, from
ops/openapi.py."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.Board.as_view(), name="switches"),
    path("config/", views.Config.as_view(), name="switches-config"),
    path("preview/", views.Preview.as_view(), name="switches-preview"),
    path("apply/", views.Apply.as_view(), name="switches-apply"),
]
