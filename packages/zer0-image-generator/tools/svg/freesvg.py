#!/usr/bin/env python3
"""
freesvg.py — FreeSVG.org API client with a local cache. Stdlib only.

FreeSVG hosts public-domain (CC0) vector art behind a small JWT API
(https://freesvg.org/pages/api-and-usage). This client makes it usable
from the authoring loop while keeping API traffic near zero:

    search "rocket"      query the catalog (cache-first, 7-day TTL)
    fetch 12345          download one SVG into the cache (immutable)
    info 12345           show an item's metadata
    promote 12345        copy a cached file into library/external/freesvg/
                         and append its MANIFEST.json entry
    prune --max-mb 50    trim the cache, oldest first
    status               cache + auth health

Cache layout (git-ignored; delete freely, it rebuilds):

    library/cache/freesvg/
      token.json          JWT + parsed expiry, chmod 600
      searches/<key>.json search responses, TTL 7 days
      meta/<id>.json      per-item metadata, TTL 30 days
      files/<id>.svg      downloaded art — immutable, cached forever

Freshness rules: a fresh cache entry never touches the network;
--refresh forces a refetch; if the network fails and a stale entry
exists, the stale entry is served with a warning (offline-first).

Credentials: FREESVG_EMAIL / FREESVG_PASSWORD in the environment or in
a git-ignored .env at the repo root. The API allows registered users
only; register at https://freesvg.org.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://freesvg.org/api/v1"
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SEARCH_TTL = 7 * 86400
META_TTL = 30 * 86400
TIMEOUT = 30

URL_KEYS = ("svg", "url", "file", "path", "download_url", "svg_url", "image", "link")


def _now() -> float:
    return time.time()


def cache_dir() -> str:
    return os.environ.get("FREESVG_CACHE_DIR") or os.path.join(
        ROOT, "tools", "svg", "library", "cache", "freesvg")


def manifest_path() -> str:
    return os.environ.get("FREESVG_MANIFEST") or os.path.join(
        ROOT, "tools", "svg", "library", "MANIFEST.json")


def _ensure(*parts: str) -> str:
    path = os.path.join(cache_dir(), *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data, private: bool = False) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    if private:
        os.chmod(path, 0o600)


def warn(msg: str) -> None:
    print(f"freesvg: {msg}", file=sys.stderr)


# -- credentials + token ------------------------------------------------------

def _env_file_creds() -> dict:
    creds = {}
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*(?:export\s+)?(FREESVG_[A-Z_]+)\s*=\s*(.*)\s*$", line)
                if m:
                    creds[m.group(1)] = m.group(2).strip("'\"")
    except OSError:
        pass
    return creds


def credentials():
    fallback = _env_file_creds()
    email = os.environ.get("FREESVG_EMAIL") or fallback.get("FREESVG_EMAIL")
    password = os.environ.get("FREESVG_PASSWORD") or fallback.get("FREESVG_PASSWORD")
    return email, password


def _jwt_exp(token: str) -> float:
    """Best-effort expiry from the JWT payload; short fallback if unreadable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except Exception:
        return _now() + 6 * 3600


def _http(method: str, url: str, body=None, token=None):
    """Returns (status, bytes). Raises OSError/URLError only on transport failure."""
    headers = {"Accept": "application/json", "User-Agent": "zer0-image-generator/freesvg-cache"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class AuthError(RuntimeError):
    pass


def get_token(force: bool = False) -> str:
    path = _ensure("token.json")
    if not force:
        cached = _read_json(path)
        if cached and cached.get("exp", 0) > _now() + 60:
            return cached["token"]
    email, password = credentials()
    if not email or not password:
        raise AuthError(
            "FreeSVG credentials missing. Set FREESVG_EMAIL and FREESVG_PASSWORD "
            "in the environment or the repo's git-ignored .env "
            "(register at https://freesvg.org — the API is for registered users).")
    status, body = _http("POST", f"{API}/auth/login", body={"email": email, "password": password})
    if status != 200:
        raise AuthError(f"login failed (HTTP {status}): {body[:200].decode('utf-8', 'replace')}")
    token = json.loads(body).get("token")
    if not token:
        raise AuthError("login response had no token")
    _write_json(path, {"token": token, "exp": _jwt_exp(token)}, private=True)
    return token


def api_get(path: str):
    """Authenticated GET returning parsed JSON; one re-login retry on 401."""
    token = get_token()
    status, body = _http("GET", f"{API}{path}", token=token)
    if status == 401:
        token = get_token(force=True)
        status, body = _http("GET", f"{API}{path}", token=token)
    if status != 200:
        raise RuntimeError(f"GET {path} failed (HTTP {status}): {body[:200].decode('utf-8', 'replace')}")
    return json.loads(body)


# -- cached operations --------------------------------------------------------

def _cached(path: str, ttl: float, refresh: bool, fetch):
    """Freshness core: fresh hit -> no network; miss/stale -> fetch;
    fetch failure with any cached copy -> serve stale, warn."""
    entry = _read_json(path)
    fresh = entry and (_now() - entry.get("fetched_at", 0) < ttl)
    if fresh and not refresh:
        return entry["data"], True
    try:
        data = fetch()
    except (AuthError, RuntimeError):
        raise
    except OSError as exc:
        if entry:
            warn(f"network unavailable ({exc}); serving stale cache from "
                 f"{time.strftime('%Y-%m-%d', time.localtime(entry['fetched_at']))}")
            return entry["data"], True
        raise
    _write_json(path, {"fetched_at": _now(), "data": data})
    return data, False


def _items_of(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "svgs", "results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return [payload]


def search(query: str, page: int = 1, refresh: bool = False):
    key = hashlib.sha256(f"{query.strip().lower()}|{page}".encode()).hexdigest()[:16]
    path = _ensure("searches", f"{key}.json")
    q = urllib.parse.urlencode({"query": query, "page": page})
    payload, cached = _cached(path, SEARCH_TTL, refresh, lambda: api_get(f"/search?{q}"))
    return _items_of(payload), cached


def item_info(svg_id: str, refresh: bool = False):
    path = _ensure("meta", f"{svg_id}.json")
    payload, cached = _cached(path, META_TTL, refresh, lambda: api_get(f"/svg/{svg_id}"))
    items = _items_of(payload)
    return (items[0] if items else payload), cached


def _looks_like_svg(body: bytes) -> bool:
    head = body[:2048].lstrip().lower()
    return head.startswith(b"<?xml") and b"<svg" in body[:4096].lower() or head.startswith(b"<svg")


def _extract_svg(item: dict) -> bytes:
    """The item schema is under-documented; try inline markup, then URL-ish
    fields, and fail with the observed keys so the caller can adapt."""
    for value in item.values():
        if isinstance(value, str) and value.lstrip().startswith(("<?xml", "<svg")):
            return value.encode("utf-8")
    for key in URL_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http") and (
                ".svg" in value.lower() or "download" in value.lower()):
            status, body = _http("GET", value, token=get_token())
            if status == 200 and _looks_like_svg(body):
                return body
    raise RuntimeError(
        "could not locate SVG content in item; fields present: "
        + ", ".join(sorted(item.keys()))
        + " — update URL_KEYS/_extract_svg in tools/svg/freesvg.py for this shape")


def fetch(svg_id: str, refresh: bool = False) -> str:
    path = _ensure("files", f"{svg_id}.svg")
    if os.path.exists(path) and not refresh:
        return path
    item, _ = item_info(svg_id, refresh=refresh)
    body = _extract_svg(item)
    with open(path, "wb") as f:
        f.write(body)
    check = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "svg", "svg-check.py"), path, "--max-kb", "1024"],
        capture_output=True, text=True)
    if check.returncode != 0:
        warn(f"downloaded file has lint errors (kept in cache, blocked from promote):\n{check.stderr.strip()}")
    return path


def _slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "untitled"


def promote(svg_id: str, name: str = "", tags=None) -> str:
    local = fetch(svg_id)
    check = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "svg", "svg-check.py"), local, "--max-kb", "1024"],
        capture_output=True, text=True)
    if check.returncode != 0:
        raise RuntimeError(f"refusing to promote {svg_id}: lint errors\n{check.stderr.strip()}")
    item, _ = item_info(svg_id)
    title = str(item.get("title") or item.get("name") or f"freesvg {svg_id}")
    slug = name or _slugify(title)
    dest_rel = f"tools/svg/library/external/freesvg/freesvg-{slug}.svg"
    dest = os.path.join(ROOT, dest_rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        with open(local, "rb") as src, open(dest, "wb") as out:
            out.write(src.read())

    manifest = _read_json(manifest_path()) or {"entries": []}
    if any(e.get("file") == dest_rel for e in manifest["entries"]):
        warn(f"{dest_rel} already in manifest; leaving entry unchanged")
        return dest_rel
    item_tags = item.get("tags")
    if isinstance(item_tags, str):
        item_tags = [t.strip() for t in item_tags.split(",") if t.strip()]
    entry_tags = list(tags or item_tags or [])[:6] or ["illustration"]
    warns = [line for line in check.stderr.splitlines() if line.startswith("WARN")]
    manifest["entries"].append({
        "file": dest_rel, "title": title,
        "source_url": f"{API}/svg/{svg_id}",
        "license": "CC0 / Public domain",
        "license_url": "https://freesvg.org",
        "tags": [str(t).lower() for t in entry_tags] + ["freesvg"],
        "lint": "clean" if not warns else "warn: " + "; ".join(w[5:].strip() for w in warns)[:160],
        "size_kb": round(os.path.getsize(dest) / 1024, 1),
    })
    manifest["entries"].sort(key=lambda e: e["file"])
    _write_json(manifest_path(), manifest)
    return dest_rel


def prune(max_mb: float = 50.0):
    victims = []
    for sub in ("files", "meta", "searches"):
        base = os.path.join(cache_dir(), sub)
        if os.path.isdir(base):
            for fn in os.listdir(base):
                p = os.path.join(base, fn)
                victims.append((os.path.getmtime(p), os.path.getsize(p), p))
    total = sum(size for _, size, _ in victims)
    removed = 0
    for _, size, path in sorted(victims):
        if total <= max_mb * 1024 * 1024:
            break
        os.remove(path)
        total -= size
        removed += 1
    return removed, total


# -- CLI ----------------------------------------------------------------------

def _print_items(items, as_json: bool, limit: int):
    if as_json:
        print(json.dumps(items[:limit], indent=2))
        return
    for it in items[:limit]:
        if not isinstance(it, dict):
            print(it)
            continue
        ident = it.get("id") or it.get("svg_id") or "?"
        title = it.get("title") or it.get("name") or "(untitled)"
        tags = it.get("tags")
        if isinstance(tags, list):
            tags = ",".join(str(t) for t in tags[:5])
        print(f"{ident}\t{title}" + (f"\t[{tags}]" if tags else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("search"); sp.add_argument("query"); sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--refresh", action="store_true"); sp.add_argument("--json", action="store_true")
    sp.add_argument("--limit", type=int, default=25)
    fp = sub.add_parser("fetch"); fp.add_argument("id"); fp.add_argument("--refresh", action="store_true")
    ip = sub.add_parser("info"); ip.add_argument("id"); ip.add_argument("--refresh", action="store_true")
    ip.add_argument("--json", action="store_true")
    pp = sub.add_parser("promote"); pp.add_argument("id"); pp.add_argument("--name", default="")
    pp.add_argument("--tags", default="")
    rp = sub.add_parser("prune"); rp.add_argument("--max-mb", type=float, default=50.0)
    sub.add_parser("status")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "search":
            items, cached = search(args.query, args.page, args.refresh)
            warn(f"{len(items)} result(s) ({'cache' if cached else 'network'})")
            _print_items(items, args.json, args.limit)
        elif args.cmd == "fetch":
            print(fetch(args.id, args.refresh))
        elif args.cmd == "info":
            item, cached = item_info(args.id, args.refresh)
            warn(f"({'cache' if cached else 'network'})")
            print(json.dumps(item, indent=2) if args.json else
                  "\n".join(f"{k}: {v}" for k, v in item.items() if not str(v).startswith("<")))
        elif args.cmd == "promote":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
            print(promote(args.id, args.name, tags))
        elif args.cmd == "prune":
            removed, total = prune(args.max_mb)
            print(f"removed {removed} file(s); cache now {total / 1048576:.1f}MB")
        elif args.cmd == "status":
            email, password = credentials()
            token = _read_json(os.path.join(cache_dir(), "token.json"))
            counts = {}
            for sub_dir in ("files", "meta", "searches"):
                base = os.path.join(cache_dir(), sub_dir)
                counts[sub_dir] = len(os.listdir(base)) if os.path.isdir(base) else 0
            print(f"cache: {cache_dir()}")
            print(f"  files={counts['files']} meta={counts['meta']} searches={counts['searches']}")
            print(f"credentials: {'set' if email and password else 'MISSING (FREESVG_EMAIL/FREESVG_PASSWORD)'}")
            if token:
                left = token.get("exp", 0) - _now()
                print(f"token: cached, {'valid %.1fh' % (left / 3600) if left > 0 else 'expired'}")
            else:
                print("token: none cached")
    except AuthError as exc:
        warn(str(exc))
        return 2
    except RuntimeError as exc:
        warn(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
