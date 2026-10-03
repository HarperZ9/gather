"""Reddit on the official Data API, with the user's own app credentials.

Authentication is the application-only OAuth grant (client credentials) with the user's own
Reddit app: ``REDDIT_CLIENT_ID`` and ``REDDIT_CLIENT_SECRET`` from the environment, plus an
optional ``REDDIT_USERNAME`` for the User-Agent Reddit asks for, or a full ``REDDIT_USER_AGENT``.
Read-only: it lists a subreddit and reads a post with its comments. It never posts or votes.

The contract mirrors the Telos reach reader (HarperZ9/telos, ``demo/reach/reddit.mjs``): the same
environment names, User-Agent form, sorts, time windows, name and id checks, limits and
normalised fields, so a read in either tool means the same thing.

Pacing: at most one request per ``min_interval`` seconds (1 s by default, well under Reddit's
published per-client limit), and when a response says no requests remain in the window, the
source waits for the reset if it falls within ``max_wait``, else it stops and says why. Every
item carries a ``gather.route/1`` record with the measured rate and the last remaining-requests
header. The secret goes only into the Basic header of the token request; the bearer token only
into API request headers. Neither reaches a URL, an item, a receipt or an error.

Targets: ``r/NAME``, ``r/NAME/SORT``, a post URL (``https://www.reddit.com/r/x/comments/ID/...``),
or ``comments/ID``.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
from collections.abc import Callable, Mapping

from gather import __version__
from gather.credentials import MissingCredential
from gather.http_call import Response, http_call
from gather.item import Item
from gather.reddit_items import comment_items, post_item
from gather.route import RouteRecord, stamp

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
ID_ENV, SECRET_ENV = "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"
SORTS = ("hot", "new", "top", "rising", "controversial")
TIMES = ("hour", "day", "week", "month", "year", "all")
METHOD = "reddit-oauth-api"
_SUB = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_POST = re.compile(r"^[a-z0-9]{4,10}$", re.I)

HttpCall = Callable[..., Response]


def credentials(env: Mapping[str, str]) -> tuple[str, str, str | None]:
    cid, secret = (env.get(ID_ENV) or "").strip(), (env.get(SECRET_ENV) or "").strip()
    if not cid or not secret:
        raise MissingCredential(f"Reddit needs {ID_ENV} and {SECRET_ENV} from your own app at "
                                "https://www.reddit.com/prefs/apps")
    return cid, secret, (env.get("REDDIT_USERNAME") or "").strip() or None


def user_agent(cid: str, username: str | None, env: Mapping[str, str]) -> str:
    """Reddit's requested form: ``<platform>:<app id>:<version> (by /u/<username>)``."""
    if (env.get("REDDIT_USER_AGENT") or "").strip():
        return env["REDDIT_USER_AGENT"].strip()
    return f"python:gather-reach.{cid[:8]}:{__version__}" + (f" (by /u/{username})" if username else "")


def parse_target(target: str) -> tuple[str, str, str | None]:
    """``("listing", subreddit, sort)`` or ``("comments", post_id, None)``; ValueError otherwise."""
    value = target.strip()
    parts = urllib.parse.urlsplit(value)
    if parts.scheme:
        host = (parts.hostname or "").lower()
        if host != "reddit.com" and not host.endswith(".reddit.com"):
            raise ValueError(f"not a Reddit URL: {value[:60]!r}")
        value = parts.path
    segs = [s for s in value.split("/") if s]
    if "comments" in segs and segs.index("comments") + 1 < len(segs):
        pid = segs[segs.index("comments") + 1].removeprefix("t3_")
        if _POST.match(pid):
            return "comments", pid, None
        raise ValueError(f"not a Reddit post id: {pid[:20]!r}")
    if len(segs) in (2, 3) and segs[0] == "r":
        sort = segs[2] if len(segs) == 3 else "hot"
        if _SUB.match(segs[1]) and sort in SORTS:
            return "listing", segs[1], sort
    raise ValueError(f"not a Reddit target (r/NAME, r/NAME/SORT, a post URL or comments/ID): {target[:60]!r}")


class RedditSource:
    name = "reddit"

    def __init__(self, *, env: Mapping[str, str] | None = None, http: HttpCall = http_call,
                 limit: int = 25, time_window: str = "day", depth: int = 3, comment_limit: int = 100,
                 min_interval: float = 1.0, max_wait: float = 120.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 wall: Callable[[], float] = time.time) -> None:
        import os
        if time_window not in TIMES:
            raise ValueError(f"time window must be one of {TIMES}")
        if min_interval < 1.0:
            raise ValueError("min_interval must be at least 1 second")
        self._env = os.environ if env is None else env
        self._http, self._clock, self._sleep, self._wall = http, clock, sleep, wall
        self._limit, self._window = max(1, min(100, int(limit))), time_window
        self._depth, self._climit = max(1, min(10, int(depth))), max(1, min(500, int(comment_limit)))
        self._min_interval, self._max_wait = min_interval, max_wait
        self._token: str | None = None
        self._last: float | None = None
        self._calls: list[dict] = []
        self._remaining: str | None = None

    def fetch(self, target: str) -> list[Item]:
        kind, name, sort = parse_target(target)
        mark = len(self._calls)
        if kind == "listing":
            data = self._api(f"/r/{name}/{sort}?limit={self._limit}&t={self._window}&raw_json=1")
            children = (data.get("data") or {}).get("children") or [] if isinstance(data, dict) else []
            items = [post_item(c, METHOD, float(self._wall())) for c in children if c.get("kind") == "t3"]
        else:
            data = self._api(f"/comments/{name}?depth={self._depth}&limit={self._climit}&raw_json=1")
            items = self._thread(data)
        return stamp(items, self._record(self._calls[mark:]))

    def _thread(self, data: object) -> list[Item]:
        if not isinstance(data, list) or not data:
            raise ValueError("Reddit returned no thread for that post")
        posts = ((data[0].get("data") or {}).get("children") or []) if isinstance(data[0], dict) else []
        if not posts:
            raise ValueError("Reddit returned no post in that thread")
        at = float(self._wall())
        post = post_item(posts[0], METHOD, at)
        tree = ((data[1].get("data") or {}).get("children") or []) if len(data) > 1 and isinstance(data[1], dict) else []
        return [post, *comment_items(tree, post, METHOD, at)]

    def _record(self, calls: list[dict]) -> RouteRecord:
        extra = {"ratelimit_remaining": self._remaining} if self._remaining is not None else {}
        return RouteRecord("reddit", METHOD, sum(c["elapsed_s"] for c in calls), len(calls),
                           sum(c["bytes"] for c in calls), auth="present", extra=extra)

    def _authorize(self, ua: str, cid: str, secret: str) -> str:
        if self._token:
            return self._token
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        resp = self._send(TOKEN_URL, method="POST", data=b"grant_type=client_credentials",
                          headers={"Authorization": f"Basic {basic}", "User-Agent": ua,
                                   "Content-Type": "application/x-www-form-urlencoded"})
        token = _json(resp.body).get("access_token") if resp.status == 200 else None
        if not isinstance(token, str) or not token:
            raise RuntimeError(f"Reddit token exchange failed with status {resp.status}")
        self._token = token
        return token

    def _api(self, path: str) -> object:
        cid, secret, username = credentials(self._env)
        ua = user_agent(cid, username, self._env)
        token = self._authorize(ua, cid, secret)
        headers = {"Authorization": f"Bearer {token}", "User-Agent": ua}
        resp = self._send(API_BASE + path, headers=headers)
        if resp.status == 429:
            self._wait_reset(resp.headers, force=True)
            resp = self._send(API_BASE + path, headers=headers)
        if resp.status != 200:
            raise RuntimeError(f"Reddit API returned {resp.status} for {path.split('?')[0]}")
        self._wait_reset(resp.headers)
        return json.loads(resp.body)

    def _send(self, url: str, **kw) -> Response:
        if self._last is not None:
            gap = self._min_interval - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        start = self._clock()
        resp = self._http(url, **kw)
        self._last = self._clock()
        self._calls.append({"elapsed_s": max(0.0, self._last - start), "bytes": len(resp.body)})
        if "x-ratelimit-remaining" in resp.headers:
            self._remaining = resp.headers["x-ratelimit-remaining"]
        return resp

    def _wait_reset(self, headers: Mapping[str, str], *, force: bool = False) -> None:
        """Wait out Reddit's window when none remain (or on a 429), within ``max_wait``."""
        remaining, reset = _num(headers.get("x-ratelimit-remaining")), _num(headers.get("x-ratelimit-reset"))
        if not force and (remaining is None or remaining >= 1):
            return
        wait = reset if reset is not None else self._max_wait + 1
        if wait > self._max_wait:
            raise RuntimeError(f"Reddit rate limit reached; the window resets in {wait:g}s, past the "
                               f"{self._max_wait:g}s this source waits")
        self._sleep(wait)


def _num(value: object) -> float | None:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _json(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
