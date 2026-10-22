"""`/api/v2/ai/`: the AI content layer's router (ai/views.py); included from
config/urls.py and, for the OpenAPI document, from ops/openapi.py."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("providers", views.ProviderViewSet, basename="ai-provider")
router.register("models", views.ModelEntryViewSet, basename="ai-model")
router.register("output-schemas", views.OutputSchemaViewSet, basename="ai-output-schema")
router.register("assistants", views.AssistantViewSet, basename="ai-assistant")
router.register("pipelines", views.PipelineViewSet, basename="ai-pipeline")
router.register("briefs", views.BriefViewSet, basename="ai-brief")
router.register("conversations", views.ConversationViewSet, basename="ai-conversation")
router.register("messages", views.MessageViewSet, basename="ai-message")

urlpatterns = router.urls
