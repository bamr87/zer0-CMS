"""The three channels that are not LinkedIn: WordPress over its REST API, a
GitHub repository as a pull request, and a newsroom newsletter by email.

* **WordPress** (absorbed from AIEO's publisher, `apps/aieo/backend/app/
  publishers/wordpress_publisher.py`): `POST /wp-json/wp/v2/posts` with the
  user's application password, as a draft unless the channel says otherwise,
  with the Yoast title and meta description AIEO's plugin exposes
  (`yoast_title`, `yoast_metadesc`). The site's address is a person's input, so
  every request goes through the research library's SSRF guard
  (`research.fetch.pinned`: public addresses only, the connection pinned to
  the address checked) and follows no redirect.
* **GitHub pull request** (absorbed from barodybroject's
  `push_to_github_and_create_pr`): the page exported as its Jekyll file
  (`exporters.jekyll`) onto a branch, and a pull request — with PyGithub, and a
  sentence a person can act on for a 401, 403, 404, 422 and a pull request that
  is already open. Only a 404 means "not there yet": anything else is reported
  as itself, never answered with a second, unrelated write.
* **Email**: the newsroom's newsletters (`newsroom.services`, django-anymail)
  — an issue of the channel's newsletter carrying the story, sent as the
  newsroom sends every issue. Nothing about sending mail is duplicated here.

Each raises `TransportError`, whose message is safe to show; `doubt` says the
target may have acted anyway (a 5xx or a dropped connection after a write), so
the ledger marks the attempt unconfirmed.
"""

import base64
import functools

import httpx
import markdown
from django.conf import settings

from exporters.jekyll import path_for, render
from importers.markdown import from_blocks
from importers.models import ImportedSource
from research import fetch

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
WP_STATUSES = ("draft", "pending", "private", "publish")


class TransportError(Exception):
    def __init__(self, message: str, *, doubt: bool = False, url: str = ""):
        super().__init__(message)
        self.message, self.doubt, self.url = message, doubt, url


# ── WordPress ───────────────────────────────────────────────────────────────


def _wordpress(channel, credentials, method: str, path: str, body=None) -> dict:
    base = str(channel.setting("url")).rstrip("/")
    url = f"{base}/wp-json/wp/v2/{path}"
    try:
        target, host, name = fetch.pinned(url)
    except fetch.FetchError as e:
        raise TransportError(f"WordPress at {base} cannot be reached: {e}") from e
    user = f"{channel.setting('username')}:{credentials.get('application_password', '')}"
    headers = {
        "Host": host,
        "Accept": "application/json",
        "User-Agent": settings.RESEARCH_USER_AGENT,
        "Authorization": "Basic " + base64.b64encode(user.encode()).decode(),
    }
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=TIMEOUT) as http:
            response = http.request(method, target, json=body, headers=headers, extensions={"sni_hostname": name})
    except httpx.HTTPError as e:
        raise TransportError(f"WordPress at {base} did not answer ({type(e).__name__})", doubt=method != "GET") from e
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.is_success:
        return data if isinstance(data, dict) else {}
    said = (data.get("message") if isinstance(data, dict) else "") or response.reason_phrase
    status = response.status_code
    if response.has_redirect_location:
        raise TransportError(
            f"WordPress answered with a redirect to {response.headers['location']}: set the channel's address to it"
        )
    messages = {
        401: f"WordPress rejected the credentials (401): {said}. Check the username and the application password.",
        403: f"WordPress refused the request (403): {said} — the user may not create posts.",
        404: f"There is no WordPress REST API at {base}/wp-json/ (404): check the site's address.",
    }
    raise TransportError(messages.get(status, f"WordPress refused the post ({status}): {said}"), doubt=status >= 500)


def page_html(page) -> str:
    """A page's body as the HTML WordPress stores, from the Markdown the platform exports."""
    return markdown.markdown(from_blocks(list(page.body.get_prep_value())), extensions=["extra"])


def wordpress_publish(channel, credentials: dict, post, page) -> tuple[str, str]:
    status = channel.setting("status", "draft")
    body = {
        "title": post.title,
        "content": page_html(page) if page is not None else post.commentary,
        "excerpt": post.commentary,
        "status": status if status in WP_STATUSES else "draft",
        "yoast_title": getattr(page, "seo_title", "") or post.title,
        "yoast_metadesc": post.description,
    }
    data = _wordpress(channel, credentials, "POST", "posts", body)
    if not data.get("id"):
        raise TransportError("WordPress answered without the new post's id", doubt=True)
    return str(data["id"]), str(data.get("link") or "")


def wordpress_check(channel, credentials: dict) -> dict:
    me = _wordpress(channel, credentials, "GET", "users/me?context=edit")
    return {"ok": True, "account": me.get("name") or me.get("slug") or "", "roles": me.get("roles", [])}


# ── GitHub pull requests ────────────────────────────────────────────────────


def _github_detail(exc) -> str:
    data = getattr(exc, "data", None)
    return str(data["message"]) if isinstance(data, dict) and data.get("message") else str(exc)


def _github_message(exc, *, action: str, repo: str, base: str) -> str:
    status = getattr(exc, "status", None)
    if status == 401:
        return (
            f"Could not {action}: GitHub rejected the credential (401). The channel's GitHub token is invalid or "
            "has expired — set a new one and publish again."
        )
    if status == 403:
        return (
            f"Could not {action}: GitHub refused the request (403). Either the API rate limit has been exceeded "
            f"— wait for it to reset and publish again — or the token has no write access to {repo}."
        )
    if status == 404:
        return (
            f"Could not {action}: GitHub returned 404. Check that the repository {repo} and the branch {base} "
            "exist and that the token can see them."
        )
    return f"Could not {action}: GitHub returned an error ({status}). {_github_detail(exc)}"


def exported_file(page) -> tuple[str, str]:
    """(path in the site, text): the stored source of an unchanged imported page, byte for byte, else the page
    rendered — what `export_jekyll` writes for it."""
    from cms.models import SiteRootPage
    from newsroom.services import with_front_matter

    page = page.specific
    root = page.get_ancestors(inclusive=True).type(SiteRootPage).last()
    if root is None:
        raise TransportError("the page is not in a site that exports to Jekyll files")
    root = root.specific
    source = ImportedSource.objects.filter(page_id=page.pk).first()
    unchanged = source is not None and page.compute_content_hash() == source.import_hash
    if unchanged and page.pk not in with_front_matter():
        return path_for(page, root), source.source_text
    return path_for(page, root), render(page)


def github_publish(channel, credentials: dict, post, page) -> tuple[str, str]:
    from github import Auth, Github, GithubException

    repo_name = str(channel.setting("repo"))
    base = str(channel.setting("branch", "main"))
    directory = str(channel.setting("directory")).strip("/")
    describe = functools.partial(_github_message, repo=repo_name, base=base)
    path, text = exported_file(page)
    repo_path = f"{directory}/{path}" if directory else path
    branch = f"distribute/{post.public_id.hex[:12]}"

    hub = Github(auth=Auth.Token(credentials.get("token", "")), retry=None, timeout=20)
    try:
        repo = hub.get_repo(repo_name)
        head = repo.get_branch(base)
    except GithubException as e:
        raise TransportError(describe(e, action=f"open the repository {repo_name}")) from e
    try:
        repo.get_branch(branch)
    except GithubException as e:
        # Only a 404 means "the branch is not there yet": a 401 or a rate-limit 403 must not be answered by
        # creating one.
        if e.status != 404:
            raise TransportError(describe(e, action=f"look up the branch {branch}")) from e
        try:
            repo.create_git_ref(ref=f"refs/heads/{branch}", sha=head.commit.sha)
        except GithubException as create_error:
            raise TransportError(describe(create_error, action=f"create the branch {branch}")) from create_error
    try:
        existing = repo.get_contents(repo_path, ref=branch)
    except GithubException as e:
        if e.status != 404:
            raise TransportError(describe(e, action=f"read {repo_path} in {repo_name}")) from e
        existing = None
    message = f"{'Update' if existing else 'Add'} {post.title or path}"
    try:
        if existing is None:
            repo.create_file(path=repo_path, message=message, content=text, branch=branch)
        else:
            repo.update_file(path=repo_path, message=message, content=text, sha=existing.sha, branch=branch)
    except GithubException as e:
        raise TransportError(describe(e, action=f"write {repo_path} in {repo_name}")) from e
    body = "\n\n".join(
        p
        for p in (
            post.commentary,
            f"Canonical URL: {post.link}" if post.link else "",
            "Opened by zer0-CMS distribution; merging it publishes the page.",
        )
        if p
    )
    try:
        pull = repo.create_pull(title=post.title or f"Publish {path}", body=body, head=branch, base=base)
    except GithubException as e:
        if e.status == 422:
            url = _open_pull(repo, branch, base)
            if url:
                raise TransportError(
                    f"A pull request for this post is already open: {url}. Review or close it, then publish again.",
                    url=url,
                ) from e
            raise TransportError(
                f"GitHub would not open a pull request ({branch} into {base}). One may already exist, or the branch "
                f"has nothing to merge. GitHub said: {_github_detail(e)}"
            ) from e
        raise TransportError(describe(e, action=f"open the pull request for {branch}")) from e
    return str(pull.number), pull.html_url


def _open_pull(repo, branch: str, base: str) -> str | None:
    """Best effort: the open pull request for `branch`, only to enrich an error — never to replace it."""
    from github import GithubException

    try:
        return next((p.html_url for p in repo.get_pulls(state="open", base=base) if p.head.ref == branch), None)
    except GithubException:
        return None


def github_check(channel, credentials: dict) -> dict:
    from github import Auth, Github, GithubException

    repo_name = str(channel.setting("repo"))
    hub = Github(auth=Auth.Token(credentials.get("token", "")), retry=None, timeout=20)
    try:
        login = hub.get_user().login
        repo = hub.get_repo(repo_name)
        can_push = bool(getattr(repo.permissions, "push", False))
    except GithubException as e:
        raise TransportError(_github_message(e, action=f"read {repo_name}", repo=repo_name, base="")) from e
    problems = [] if can_push else [f"{login} may not push to {repo_name}: pull requests cannot be opened"]
    return {"ok": not problems, "account": login, "problems": problems}


# ── email: a newsroom newsletter ────────────────────────────────────────────


def email_publish(channel, post, user) -> tuple[str, str]:
    from newsroom import services as newsroom
    from newsroom.models import Issue
    from ops.errors import ApiError

    if channel.newsletter is None:
        raise TransportError("the channel has no newsletter: pick one of the site's newsletters")
    if post.story is None:
        raise TransportError(
            "email goes out as a newsletter issue, which carries newsroom stories: this is not a story"
        )
    issue = Issue.objects.create(
        newsletter=channel.newsletter, subject=post.title[:200], intro=post.commentary, created_by=user
    )
    try:
        newsroom.set_issue_stories(issue, [post.story])
        newsroom.send_issue(issue, user=user)
    except ApiError as e:
        issue.delete()
        raise TransportError(f"The newsletter refused the issue: {e.message}") from e
    return str(issue.public_id), ""
