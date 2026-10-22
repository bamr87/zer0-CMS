"""`/api/v2/books/` (books/views.py); included from config/urls.py and, for the
OpenAPI document, from ops/openapi.py."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.Shelf.as_view(), name="books"),
    path("tasks/", views.tasks, name="books-tasks"),
    path("premise/", views.Premise.as_view(), name="books-premise"),
    path("premise/<uuid:brief>/create/", views.create_from_brief, name="books-premise-create"),
    path("<int:pk>/", views.book, name="book"),
    path("<int:pk>/issues/", views.issues, name="book-issues"),
    path("<int:pk>/chapters/", views.add_chapter, name="book-chapters"),
    path("<int:pk>/manuscript/", views.manuscript, name="book-manuscript"),
    path("<int:pk>/context/", views.book_context, name="book-context"),
    path("<int:pk>/assist/", views.Assist.as_view(), name="book-assist"),
]
