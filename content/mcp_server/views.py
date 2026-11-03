"""`/mcp/`: MCP's Streamable HTTP transport, JSON responses only.

- POST one JSON-RPC message; a request gets a JSON response, a notification
  gets 202. Batches are refused (MCP 2025-06-18 removed them).
- GET is 405: this server does not open server-initiated streams.
- `Authorization: Bearer <agent token>` is required; the token's agent user
  is the principal for every call (agents/models.py `AgentToken`).
- Every request spends a bucket before it is answered, as a REST request does
  (ops/throttling.py): a token's own, else the address's — a request refused
  for its token included. Over the limit is HTTP 429 with `Retry-After` and a
  JSON-RPC error whose `data` carries `code: rate.limited` and `retry_after`.
- A request carrying an `Origin` header not in `MCP_ALLOWED_ORIGINS` is
  refused — MCP's guard against DNS rebinding from a browser.
"""

import json
import logging

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from agents.auth import bearer
from agents.models import AgentToken
from ops.throttling import refusal

from .protocol import INTERNAL_ERROR, PARSE_ERROR, SUPPORTED_VERSIONS, Principal, error, handle

log = logging.getLogger("mcp_server")
RATE_LIMITED = -32000  # JSON-RPC's implementation-defined server error; `data.code` says which


@csrf_exempt
def mcp_endpoint(request):
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response
    origin = request.headers.get("Origin")
    if origin and origin not in settings.MCP_ALLOWED_ORIGINS:
        return JsonResponse(error(None, -32600, f"origin {origin} is not allowed"), status=403)
    version = request.headers.get("MCP-Protocol-Version")
    if version and version not in SUPPORTED_VERSIONS:
        return JsonResponse(error(None, -32600, f"unsupported MCP-Protocol-Version {version}"), status=400)
    raw = bearer(request.headers.get("Authorization"))
    token = AgentToken.authenticate(raw) if raw else None
    if (wait := refusal(request, user=token.user if token else AnonymousUser(), auth=token)) is not None:
        limited = {"code": "rate.limited", "retry_after": wait}
        response = JsonResponse(
            error(None, RATE_LIMITED, f"too many requests; try again in {wait} s", limited), status=429
        )
        response["Retry-After"] = str(wait)
        return response
    if token is None:
        response = JsonResponse(error(None, -32600, "an agent token is required"), status=401)
        response["WWW-Authenticate"] = 'Bearer realm="zer0-content"'
        return response
    try:
        message = json.loads(request.body or b"null")
    except ValueError:
        return JsonResponse(error(None, PARSE_ERROR, "the body is not JSON"), status=400)
    if isinstance(message, list):
        return JsonResponse(error(None, -32600, "batches are not supported"), status=400)
    try:
        reply = handle(message, Principal.for_user(token.user, token=token))
    except Exception:  # noqa: BLE001 — JSON-RPC: a crash is an error response with the request id, never a traceback
        log.exception("mcp request failed")
        id_ = message.get("id") if isinstance(message, dict) else None
        return JsonResponse(error(id_, INTERNAL_ERROR, "internal error"), status=500)
    if reply is None:
        return HttpResponse(status=202)
    return JsonResponse(reply)
