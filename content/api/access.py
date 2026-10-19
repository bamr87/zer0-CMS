"""Who may start an agent run, from any surface.

A person may run an agent on a page they can edit (or, with no page, if they
are staff). An agent token may start runs of its own agent only — the Rails
plane holds a token per agent it drives, never a token that can start any
agent. Nobody anonymous starts anything.
"""


def may_request_run(user, definition, page) -> tuple[bool, str]:
    if user is None or not user.is_authenticated:
        return False, "sign in, or send an agent token"
    if user.username.startswith("agent:"):
        if user.username != definition.username:
            return False, f"{user.username} may start runs of {user.username[6:]} only"
        return True, ""
    if page is not None:
        if page.permissions_for_user(user).can_edit():
            return True, ""
        return False, f"{user} may not edit page {page.pk}"
    if user.is_staff:
        return True, ""
    return False, "a run without a page needs a staff user"
