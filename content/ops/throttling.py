"""API rate limits (UPS-BE-05): one bucket per anonymous address, one per
signed-in person, and one per agent token — not per agent user, so two
clients holding tokens for the same agent cannot starve each other. A scope
whose rate is `None` is off (DRF's own rule), which is how the test settings
disable them and how an operator can."""

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from agents.models import AgentToken


class AnonThrottle(AnonRateThrottle):
    scope = "anon"


class PrincipalThrottle(SimpleRateThrottle):
    scope = "principal"

    def get_cache_key(self, request, view):
        if isinstance(request.auth, AgentToken):
            ident = f"token_{request.auth.pk}"
        elif request.user and request.user.is_authenticated:
            ident = f"user_{request.user.pk}"
        else:
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}
