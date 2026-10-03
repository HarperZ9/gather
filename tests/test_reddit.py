"""Reddit through the official Data API: OAuth with the user's app, pacing, items and receipts."""
import base64
import json

import pytest

from gather.credentials import MissingCredential
from gather.http_call import Response
from gather.reddit import TOKEN_URL, RedditSource, parse_target, user_agent
from gather.source import Catalog

ENV = {"REDDIT_CLIENT_ID": "appid12345", "REDDIT_CLIENT_SECRET": "s3cret-planted-value", "REDDIT_USERNAME": "me"}
TOKEN = "bearer-planted-token-xyz"


def post(pid="abc123", title="Hello", selftext="body text", sub="python"):
    return {"kind": "t3", "data": {"id": pid, "title": title, "selftext": selftext, "subreddit": sub,
                                   "author": "op", "score": 10, "num_comments": 2, "created_utc": 1.0,
                                   "url": f"https://www.reddit.com/r/{sub}/comments/{pid}/x/",
                                   "permalink": f"/r/{sub}/comments/{pid}/x/"}}


def comment(cid, body, replies=None):
    return {"kind": "t1", "data": {"id": cid, "body": body, "author": "u", "score": 1, "created_utc": 2.0,
                                   "parent_id": "t3_abc123", "permalink": f"/r/python/comments/abc123/x/{cid}/",
                                   "replies": {"data": {"children": replies}} if replies else ""}}


LISTING = {"data": {"children": [post("aaa111"), post("bbb222", selftext="")], "after": None}}
THREAD = [{"data": {"children": [post()]}},
          {"data": {"children": [comment("c1", "top", [comment("c2", "reply")]), {"kind": "more", "data": {}},
                                 comment("c3", "")]}}]


class FakeReddit:
    def __init__(self, api_body=LISTING, headers=None, statuses=None):
        self.calls, self.api_body = [], api_body
        self.headers = headers or {"x-ratelimit-remaining": "99.0", "x-ratelimit-reset": "300"}
        self.statuses = list(statuses or [])

    def __call__(self, url, *, method="GET", data=None, headers=None):
        self.calls.append({"url": url, "method": method, "data": data, "headers": dict(headers or {})})
        if url == TOKEN_URL:
            return Response(200, json.dumps({"access_token": TOKEN, "expires_in": 3600}).encode())
        status = self.statuses.pop(0) if self.statuses else 200
        return Response(status, json.dumps(self.api_body).encode(), dict(self.headers))


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.1
        return self.t


def make(fake, env=ENV, **kw):
    slept = []
    clock = Clock()

    def sleep(s):
        slept.append(round(s, 3))
        clock.t += s
    return RedditSource(env=env, http=fake, clock=clock, sleep=sleep, wall=lambda: 5.0, **kw), slept


def test_token_exchange_uses_basic_auth_from_the_environment():
    fake = FakeReddit()
    make(fake)[0].fetch("r/python")
    tok = fake.calls[0]
    assert tok["url"] == TOKEN_URL and tok["method"] == "POST" and tok["data"] == b"grant_type=client_credentials"
    assert tok["headers"]["Authorization"] == "Basic " + base64.b64encode(b"appid12345:s3cret-planted-value").decode()
    api = fake.calls[1]
    assert api["url"] == "https://oauth.reddit.com/r/python/hot?limit=25&t=day&raw_json=1"
    assert api["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert api["headers"]["User-Agent"] == "python:gather-reach.appid123:" + api["headers"]["User-Agent"].split(":")[2]
    assert api["headers"]["User-Agent"].endswith("(by /u/me)")


def test_listing_becomes_post_items_with_permalinks_and_a_route():
    items = make(FakeReddit())[0].fetch("https://www.reddit.com/r/python/new")
    assert [i.kind for i in items] == ["post", "post"]
    first = items[0]
    assert first.provenance.method == "reddit-oauth-api" and first.provenance.source == "reddit"
    assert first.provenance.ref == "https://www.reddit.com/r/python/comments/aaa111/x/"
    assert first.text == "Hello\n\nbody text" and first.meta["subreddit"] == "python"
    assert items[1].text.endswith("/r/python/comments/bbb222/x/"), "a link post's text carries the link"
    route = first.meta["route"]
    assert route["path"] == "reddit-oauth-api" and route["auth"] == "present" and route["requests"] == 2
    assert route["extra"] == {"ratelimit_remaining": "99.0"}


def test_a_thread_flattens_comments_depth_first_and_skips_stubs_and_empty_bodies():
    items = make(FakeReddit(api_body=THREAD))[0].fetch("comments/abc123")
    assert [(i.kind, i.text) for i in items] == [("post", "Hello\n\nbody text"), ("comment", "top"),
                                                 ("comment", "reply")]
    assert [i.meta.get("depth") for i in items[1:]] == [0, 1]
    assert items[2].provenance.ref.endswith("/c2/")


def test_requests_are_paced_at_least_one_second_apart():
    fake = FakeReddit()
    src, slept = make(fake)
    src.fetch("r/python")
    src.fetch("r/rust")
    assert len(fake.calls) == 3, "the token is reused"
    assert slept and all(s >= 0.8 for s in slept)


def test_no_remaining_requests_waits_for_the_reset_within_budget():
    src, slept = make(FakeReddit(headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "30"}))
    src.fetch("r/python")
    assert 30.0 in slept


def test_a_reset_past_the_budget_stops_with_the_reason():
    src, _ = make(FakeReddit(headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "500"}))
    with pytest.raises(RuntimeError, match="resets in 500s"):
        src.fetch("r/python")


def test_a_429_waits_once_then_retries():
    fake = FakeReddit(statuses=[429, 200], headers={"x-ratelimit-remaining": "5", "x-ratelimit-reset": "10"})
    src, slept = make(fake)
    assert len(src.fetch("r/python")) == 2 and 10.0 in slept and len(fake.calls) == 3


def test_an_api_error_is_raised_without_the_query():
    src, _ = make(FakeReddit(statuses=[403]))
    with pytest.raises(RuntimeError, match=r"returned 403 for /r/python/hot$"):
        src.fetch("r/python")


def test_missing_credentials_name_the_variables_and_make_no_request():
    fake = FakeReddit()
    with pytest.raises(MissingCredential, match="REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET"):
        make(fake, env={})[0].fetch("r/python")
    assert fake.calls == []


def test_secret_and_token_appear_in_no_url_item_or_receipt(capsys):
    fake = FakeReddit(api_body=THREAD)
    items = make(fake)[0].fetch("comments/abc123")
    cat = Catalog()
    cat.add(items)
    blob = cat.to_json() + json.dumps([i.meta for i in items]) + "".join(c["url"] for c in fake.calls)
    blob += "".join(capsys.readouterr())
    assert ENV["REDDIT_CLIENT_SECRET"] not in blob and TOKEN not in blob


@pytest.mark.parametrize("target,want", [
    ("r/python", ("listing", "python", "hot")), ("r/python/top", ("listing", "python", "top")),
    ("https://old.reddit.com/r/python/comments/abc123/title/", ("comments", "abc123", None)),
    ("comments/t3_abc123", ("comments", "abc123", None)),
])
def test_parse_target(target, want):
    assert parse_target(target) == want


@pytest.mark.parametrize("target", ["r/a", "r/python/best", "https://evil.example/r/python",
                                    "comments/../../x", "u/someone"])
def test_parse_target_refuses_other_forms(target):
    with pytest.raises(ValueError):
        parse_target(target)


def test_options_are_checked_and_clamped():
    with pytest.raises(ValueError):
        RedditSource(env=ENV, time_window="decade")
    with pytest.raises(ValueError):
        RedditSource(env=ENV, min_interval=0.2)
    fake = FakeReddit()
    make(fake, limit=1000)[0].fetch("r/python")
    assert "limit=100&" in fake.calls[1]["url"]


def test_user_agent_override_wins():
    assert user_agent("id", None, {"REDDIT_USER_AGENT": "custom:ua:1"}) == "custom:ua:1"
    assert user_agent("abcdefghij", None, {}).startswith("python:gather-reach.abcdefgh:")
