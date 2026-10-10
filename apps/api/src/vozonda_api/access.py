"""Who may read and write what once Vozonda is reachable from outside the host.

Local use (the default: the API and the web UI published on 127.0.0.1 only) stays open, exactly as before:
nobody else can reach it. A request counts as *remote* when

- the install says it is exposed (VOZONDA_HOST is not a loopback address and the port is not published on
  loopback only), or
- it came through a reverse proxy: it carries X-Forwarded-For or Forwarded. A proxy in front of the web UI
  (Caddy, nginx, Tailscale serve, a tunnel) adds them; the bundled web container passes on only what it
  received, so a local browser sends none. A client cannot make itself local by sending fewer headers than its
  proxy adds.

Remote requests are denied by default (GHSA-crq5-73gf-fv2h). They pass when

- they carry the VOZONDA_TOKEN: as `Authorization: Bearer`, or as the session cookie the web UI gets once from
  POST /auth/session (HttpOnly, SameSite=Strict), so the audio player and live updates work without headers;
- the path is public by nature (health, voice probes, intro music, default artwork, the login itself);
- the path is a feed (the feed checks its own key) or an episode's media or share page, and the request carries
  the feed key (?key=, as the links in a private feed do) or the episode is public: its show's feed is public
  or it was published to Nostr.

Without a configured token, remote requests that need one get 503 with a hint, like writes always did.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from contextvars import ContextVar

from fastapi import Request

from .env import env

# Set per request by the access middleware in main.py, read by require_write_auth, so the many existing
# require_write_auth(authorization) calls keep their signature.
request_remote: ContextVar[bool] = ContextVar("vozonda_request_remote", default=False)
request_authed: ContextVar[bool] = ContextVar("vozonda_request_authed", default=False)

SESSION_COOKIE = "vozonda_session"
SESSION_MAX_AGE = 30 * 24 * 3600
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Always public: nothing private behind them.
_PUBLIC_EXACT = {"/health", "/og-default.png", "/img/og-default.png", "/llms.txt", "/styles/custom",
                 "/auth/session", "/auth/nostr/challenge"}
_PUBLIC_PREFIXES = ("/music/", "/audio/probe-")
_FEED = re.compile(r"^/(?:feed\.xml|[^/]+/[^/]+/feed\.xml)$")
# Paths that belong to one episode; group 1 is the file or id that starts with the job id.
_EPISODE_PATHS = [
    re.compile(r"^/audio/(.+)\.mp3$"),
    re.compile(r"^/audio/(.+)\.peaks\.json$"),
    re.compile(r"^/vtt/(.+)\.vtt$"),
    re.compile(r"^/srt/(.+)\.srt$"),
    re.compile(r"^/e/([^/]+)(?:/clip/.*)?$"),
    re.compile(r"^/share/([^/]+)$"),
    re.compile(r"^/source/([^/]+)$"),
    re.compile(r"^/img/(.+)$"),
]


def install_exposed() -> bool:
    """The install itself listens beyond loopback (or bills money): every request is remote."""
    billing = env("ENABLE_BILLING", "false").strip().lower() == "true"
    exposed = env("HOST", "127.0.0.1").strip() not in _LOOPBACK_HOSTS
    if env("PUBLISHED_ON", "").strip().lower() == "loopback":
        exposed = False
    return billing or exposed


def is_remote(request: Request) -> bool:
    if install_exposed():
        return True
    h = request.headers
    return bool(h.get("x-forwarded-for", "").strip() or h.get("forwarded", "").strip())


def token() -> str:
    return env("TOKEN", "")


def session_value(tok: str) -> str:
    """Cookie value derived from the token: changing VOZONDA_TOKEN ends every session."""
    return hmac.new(tok.encode(), b"vozonda-session-v1", hashlib.sha256).hexdigest()


def is_authed(request: Request) -> bool:
    tok = token()
    if not tok:
        return False
    auth = request.headers.get("authorization") or ""
    if hmac.compare_digest(auth.encode(), f"Bearer {tok}".encode()):
        return True
    cookie = request.cookies.get(SESSION_COOKIE) or ""
    return bool(cookie) and hmac.compare_digest(cookie.encode(), session_value(tok).encode())


def is_public_path(path: str) -> bool:
    return path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES)


def is_feed_path(path: str) -> bool:
    return bool(_FEED.match(path))


def episode_ref(path: str) -> str | None:
    """The file or id an episode path names (its job id plus a suffix), or None if it is no episode path."""
    for rx in _EPISODE_PATHS:
        m = rx.match(path)
        if m:
            return m.group(1)
    return None


def _job_for_ref(ref: str) -> dict | None:
    """The job a media name belongs to: the name itself, the part before -clip-, or a cover name's prefix."""
    from .main import store

    candidates = [ref, ref.split("-clip-")[0]]
    stem = ref.rsplit(".", 1)[0]
    candidates += [stem, stem.rsplit("-", 1)[0]]
    for c in dict.fromkeys(candidates):
        try:
            return store.get(c)
        except KeyError:
            continue
    return None


def feed_key_ok(request: Request) -> bool:
    from .settings_store import get_private_feed_key

    key = request.query_params.get("key") or ""
    return bool(key) and hmac.compare_digest(key.encode(), get_private_feed_key().encode())


def job_is_public(job: dict) -> bool:
    """Public when its feed is public (feed.public and its show's RSS on) or it was published to Nostr."""
    from .jobs import DB_PATH
    from .routers.feeds import _feed_is_public, _show_num_for_slug
    from .settings_store import resolve_show_rss

    if _feed_is_public():
        slug = (job.get("show_slug") or "").strip()
        num = _show_num_for_slug(slug) if slug else "default"
        if resolve_show_rss(num or "default") == "1":
            return True
    try:
        with sqlite3.connect(DB_PATH) as c:
            row = c.execute("SELECT 1 FROM nostr_publish WHERE job_id = ? AND kind = 54 LIMIT 1",
                            (job.get("id"),)).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def episode_media_allowed(request: Request, ref: str) -> bool:
    if feed_key_ok(request):
        return True
    job = _job_for_ref(ref)
    if job is None:
        # watchlist show artwork is public; anything else unknown is not
        return ref.startswith("watchlist-")
    return job_is_public(job)


