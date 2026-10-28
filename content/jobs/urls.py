"""`/api/v2/jobs/` (jobs/views.py); included from config/urls.py and, for the
OpenAPI document, from ops/openapi.py."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.JobList.as_view(), name="jobs"),
    path("<uuid:public_id>/", views.job_detail, name="job"),
    path("<uuid:public_id>/stream/", views.job_stream, name="job-stream"),
    path("<uuid:public_id>/cancel/", views.job_cancel, name="job-cancel"),
    path("<uuid:public_id>/artifacts/<str:name>/", views.job_artifact, name="job-artifact"),
]
