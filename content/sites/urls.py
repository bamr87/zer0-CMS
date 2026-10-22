"""`/api/v2/sites/` (sites/views.py); included from config/urls.py and, for the
OpenAPI document, from ops/openapi.py."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.Sites.as_view(), name="sites"),
    path("discover/", views.Discover.as_view(), name="sites-discover"),
    path("<int:pk>/", views.SiteDetail.as_view(), name="site"),
    path("<int:pk>/settings/", views.Settings.as_view(), name="site-settings"),
    path("<int:pk>/findings/", views.Findings.as_view(), name="site-findings"),
    path("<int:pk>/sync/", views.Sync.as_view(), name="site-sync"),
    path("<int:pk>/export/", views.Export.as_view(), name="site-export"),
    path("<int:pk>/doctor/", views.Doctor.as_view(), name="site-doctor"),
]
