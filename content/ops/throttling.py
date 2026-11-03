"""API rate limits (UPS-BE-05): one bucket per anonymous address, one per
signed-in person, and one per agent token — not per agent user, so two
clients holding tokens for the same agent cannot starve each other. A scope
whose rate is `None` is off (DRF's own rule), which is how the test settings
disable them and how an operator can.

The same buckets hold where DRF does not run: GraphQL (api/views.py) and
`/mcp/` (mcp_server/views.py) ask `refusal()`, which runs the throttles over a
DRF `Request` around the Django one, and answer a spent bucket in their own
protocol's shape with `Retry-After`. `RunThrottle` is one more allowance on
top, for starting a model run (`THROTTLE_AI_RUN_RATE`), on every surface that
starts one."""

import math

from rest_framework.request import Request
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle

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


class RunThrottle(UserRateThrottle):
    """Per caller, how often a model run may start over REST and GraphQL (`THROTTLE_AI_RUN_RATE`, 30 a minute):
    `ai.run_assistant`'s rate over MCP, so no surface starts more paid calls than another."""

    scope = "ai_run"


def refusal(request, *, user=None, auth=None, throttles=(AnonThrottle, PrincipalThrottle)) -> int | None:
    """The whole seconds to wait when one of `throttles` refuses `request`, else None. `request` is DRF's, or a
    Django request whose caller is `user` (by default its own `user`), with `auth` the agent's token if that is
    who. Every throttle spends its bucket, as DRF's own check does, so a refused request still counts."""
    if isinstance(request, Request):
        drf = request
    else:
        drf = Request(request)
        drf.user, drf.auth = user if user is not None else request.user, auth
    waits = []
    for throttle in (cls() for cls in throttles):
        if not throttle.allow_request(drf, None):
            waits.append(throttle.wait() or 1)
    return max(1, math.ceil(max(waits))) if waits else None
