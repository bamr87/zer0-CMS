"""`/api/v2/books/`: the studio's Books area over REST (books/README.md).

    GET  /api/v2/books/                        the shelf (`?templates=true` for the templates)
    POST /api/v2/books/                        a new book from the template, as a draft
    GET  /api/v2/books/tasks/                  what the book assistant can do
    POST /api/v2/books/premise/                a premise → an outline brief, generated as a run (202)
    POST /api/v2/books/premise/<brief>/create/ the person accepts the outline: a draft book and its chapter stubs
    GET  /api/v2/books/<id>/                   a book's overview: facts, chapters in order, statistics, findings
    GET  /api/v2/books/<id>/issues/            its validation findings
    POST /api/v2/books/<id>/chapters/          the next chapter, as a draft stub
    GET  /api/v2/books/<id>/manuscript/        the compiled manuscript
    GET  /api/v2/books/<id>/context/           what a task's model would be given
    POST /api/v2/books/<id>/assist/            run a book task (202); draft, continue and revise come back as suggestions

Thin views over books/services.py, for people only (`IsPerson`): a book is
found among the pages the person may open (else a 404), every write is a draft
revision under their page permissions, and a run-creating request honours an
`Idempotency-Key`. A book's own fields are edited through the generic page
endpoints. Every failure is the error envelope.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Site

from ai.models import Assistant, Brief
from ai.serializers import RunAcceptedSerializer, RunRefSerializer
from ai.views import IDEMPOTENCY, idempotent
from api.pages import IsPerson, service_errors
from cms.models import ChapterPage
from cms.services import visible_pages
from ops.errors import NotFound
from ops.openapi import ERROR_RESPONSES

from . import context, library, services
from . import serializers as s


def _valid(serializer_class, request) -> dict:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _parent(request, pk):
    """A page the person can find to create under; whether they may is the service's question."""
    if pk is None:
        return services.library_root()
    page = visible_pages(request.user).filter(pk=pk).first()
    if page is None:
        raise NotFound(f"no page {pk}")
    return page.specific


def _chapter(book, pk):
    chapter = ChapterPage.objects.child_of(book).filter(pk=pk).first() if pk is not None else None
    if pk is not None and chapter is None:
        raise NotFound(f"book {book.pk} has no chapter {pk}")
    return chapter


def _assistant(request, public_id):
    if public_id is None:
        return None
    found = Assistant.objects.visible_to(request.user).filter(public_id=public_id).first()
    if found is None:
        raise NotFound(f"no assistant {public_id}")
    return found


def _detail(request, book, code=status.HTTP_200_OK):
    return Response(s.BookDetailSerializer(services.detail(book, request.user)).data, status=code)


class Shelf(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="books_list",
        summary="The shelf: every book the caller may open, with its status and progress",
        parameters=[
            OpenApiParameter("site", int, description="Only this site's books."),
            OpenApiParameter("templates", bool, description="The templates new books start from instead."),
        ],
        responses={200: s.BookSummarySerializer(many=True), **ERROR_RESPONSES},
    )
    def get(self, request):
        site_id = request.query_params.get("site")
        site = Site.objects.filter(pk=site_id).first() if site_id and site_id.isdigit() else None
        templates = request.query_params.get("templates") in ("true", "1")
        books = services.shelf(request.user, site=site, templates=templates)
        return Response(s.BookSummarySerializer([services.summary(b) for b in books], many=True).data)

    @extend_schema(
        operation_id="books_create",
        summary="A new book from the template, as a draft (`books new`)",
        request=s.NewBookSerializer,
        responses={201: s.BookDetailSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        data = _valid(s.NewBookSerializer, request)
        parent = _parent(request, data.get("parent"))
        with service_errors():
            book = services.new_book(
                parent,
                request.user,
                title=data["title"],
                slug=data.get("slug") or "",
                logline=data.get("logline") or "",
                genre=data.get("genre") or "",
            )
        return _detail(request, book, status.HTTP_201_CREATED)


@extend_schema(
    operation_id="books_tasks", summary="The book assistant's tasks", responses={200: s.BookTaskSerializer(many=True)}
)
@api_view(["GET"])
@permission_classes([IsPerson])
def tasks(request):
    data = [
        {
            "key": t.key,
            "label": t.label,
            "description": t.description,
            "chapter": t.chapter,
            "suggests": t.key in services.WRITING_TASKS,
        }
        for t in context.TASKS.values()
    ]
    return Response(s.BookTaskSerializer(data, many=True).data)


class Premise(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="books_premise",
        summary="Outline a book from a premise: a brief the bundled outliner generates, as a run",
        request=s.PremiseSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.PremiseAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def post(self, request):
        data = _valid(s.PremiseSerializer, request)
        parent = _parent(request, data.get("parent"))
        brief, run = services.outline_from_premise(
            request.user, premise=data["premise"], parent=parent, assistant=_assistant(request, data.get("assistant"))
        )
        body = {"brief": s.OutlineBriefSerializer(brief).data, "run": RunRefSerializer(run).data}
        return Response(body, status=status.HTTP_202_ACCEPTED)


@extend_schema(
    operation_id="books_premise_create",
    summary="Accept a ready outline: a draft book with its facts, outline and a stub per planned chapter",
    request=s.CreateFromBriefSerializer,
    responses={201: s.BookDetailSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsPerson])
def create_from_brief(request, brief):
    data = _valid(s.CreateFromBriefSerializer, request)
    found = Brief.objects.visible_to(request.user).filter(public_id=brief).first()
    if found is None:
        raise NotFound(f"no brief {brief}")
    parent = _parent(request, data["parent"]) if data.get("parent") is not None else None
    with service_errors():
        book = services.create_from_brief(found, request.user, parent=parent)
    return _detail(request, book, status.HTTP_201_CREATED)


@extend_schema(
    operation_id="books_retrieve",
    summary="A book's overview: facts, chapters in order, statistics and findings",
    responses={200: s.BookDetailSerializer, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def book(request, pk):
    return _detail(request, services.find(request.user, pk))


@extend_schema(
    operation_id="books_issues",
    summary="A book's validation findings, with the books package's codes",
    responses={200: s.IssueSerializer(many=True), **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def issues(request, pk):
    found = services.validate(services.find(request.user, pk))
    return Response(s.IssueSerializer([i.as_dict() for i in found], many=True).data)


@extend_schema(
    operation_id="books_chapters_create",
    summary="Add the next chapter, as a draft stub (`books add-chapter`)",
    request=s.NewChapterSerializer,
    responses={201: s.BookDetailSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsPerson])
def add_chapter(request, pk):
    data = _valid(s.NewChapterSerializer, request)
    found = services.find(request.user, pk)
    with service_errors():
        services.add_chapter(found, request.user, title=data["title"], number=data.get("number"), act=data.get("act"))
    return _detail(request, found, status.HTTP_201_CREATED)


@extend_schema(
    operation_id="books_manuscript",
    summary="The compiled manuscript (`books build`)",
    parameters=[OpenApiParameter("include_outline", bool, description="Put the outline after the title page.")],
    responses={200: s.ManuscriptSerializer, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def manuscript(request, pk):
    found = services.find(request.user, pk)
    rm = services.read(found)
    text = library.manuscript(rm, include_outline=request.query_params.get("include_outline") in ("true", "1"))
    data = {"filename": f"{rm.slug}-manuscript.md", "markdown": text, "word_count": rm.word_count}
    return Response(s.ManuscriptSerializer(data).data)


@extend_schema(
    operation_id="books_context",
    summary="What a book task's model would be given, without calling it (`books context`)",
    parameters=[
        OpenApiParameter("chapter", int, description="A chapter's page id."),
        OpenApiParameter("task", str, enum=list(context.TASKS), description="Default: draft (or outline)."),
    ],
    responses={200: s.ContextSerializer, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def book_context(request, pk):
    found = services.find(request.user, pk)
    raw = request.query_params.get("chapter", "")
    chapter = _chapter(found, int(raw)) if raw.isdigit() else None
    task = context.TASKS.get(request.query_params.get("task") or ("draft" if chapter else "outline"))
    if task is None:
        raise NotFound("no such task")
    rm = services.read(found)
    rm_chapter = services.chapter_in(rm, chapter) if chapter else None
    return Response(s.ContextSerializer({"text": context.request(rm, rm_chapter, task)}).data)


class Assist(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="books_assist",
        summary="Run a book task as a run of the book assistant; draft, continue and revise propose suggestions",
        request=s.AssistSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def post(self, request, pk):
        data = _valid(s.AssistSerializer, request)
        found = services.find(request.user, pk)
        run = services.run_task(
            found,
            request.user,
            task=data["task"],
            chapter=_chapter(found, data.get("chapter")),
            instruction=data.get("instruction") or "",
            selection=data.get("selection") or "",
            assistant=_assistant(request, data.get("assistant")),
        )
        return Response({"run": RunRefSerializer(run).data}, status=status.HTTP_202_ACCEPTED)
