"""Wagtail's log for both bearer tokens (`accounts.tokens.HashedToken`: a
person's `UserToken` and an agent's `AgentToken`): issuing one and revoking one
are log entries (`wagtail.log_actions.log`), the audit trail of who holds a
credential to the platform. Never the token itself: a log entry names the
token's holder, name and shown prefix."""

from wagtail import hooks
from wagtail.models import ModelLogEntry

from .tokens import HashedToken


@hooks.register("register_log_actions")
def token_log_actions(actions):
    actions.register_model(HashedToken, ModelLogEntry)
    actions.register_action("zer0.token.issue", "Issue a token", "Token issued")
    actions.register_action("zer0.token.revoke", "Revoke a token", "Token revoked")
