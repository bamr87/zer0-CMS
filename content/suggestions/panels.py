"""`SuggestionsPanel`: pending agent suggestions inside the page editor, with a
link to accept or reject them (note §2.3: tracked changes, not a chatbot)."""

from wagtail.admin.panels import Panel


class SuggestionsPanel(Panel):
    class BoundPanel(Panel.BoundPanel):
        template_name = "suggestions/panel.html"

        def get_context_data(self, parent_context=None):
            from .services import pending_for

            context = super().get_context_data(parent_context)
            page = self.instance
            context["pending"] = list(pending_for(page.specific)) if page and page.pk else []
            context["page"] = page
            return context
