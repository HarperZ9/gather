"""A chat client for a model served on this machine, and only on this machine.

``LocalModel`` talks to an OpenAI-compatible ``/chat/completions`` endpoint (Ollama, llama.cpp's
server, vLLM, LM Studio) and refuses any endpoint whose host is not a loopback address. A hosted
API cannot be reached through it, so a report written with it was written by a model the user
runs locally. Which weights those are is the user's choice; Gather records the model name the
server reports.

The request carries no credential. Reasoning blocks some open models emit (``<think>...</think>``)
are removed from the answer. The HTTP call is injectable for tests.
"""

from __future__ import annotations

import ipaddress
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"
_THINK = re.compile(r"<think>.*?</think>", re.S)

Post = Callable[[str, bytes, float], bytes]


def require_loopback(endpoint: str) -> str:
    """The endpoint without a trailing slash, or ValueError when its host is not loopback."""
    parts = urllib.parse.urlsplit(endpoint.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https"):
        raise ValueError("the model endpoint must be http or https")
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(f"refused: the model endpoint must be on this machine (loopback), got host {host!r}")
    return endpoint.strip().rstrip("/")


def _post(url: str, body: bytes, timeout: float) -> bytes:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    # no proxy: a loopback request must not be handed to an ambient proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return resp.read(10_000_000)


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    model: str
    elapsed_s: float


class LocalModel:
    def __init__(self, model: str, *, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 600.0,
                 post: Post = _post, clock: Callable[[], float] = time.monotonic) -> None:
        if not model.strip():
            raise ValueError("name the local model to use")
        self.model = model.strip()
        self.endpoint = require_loopback(endpoint)
        self._timeout, self._post, self._clock = timeout, post, clock

    def chat(self, system: str, user: str) -> Reply:
        body = json.dumps({"model": self.model, "temperature": 0, "stream": False,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}]}).encode("utf-8")
        start = self._clock()
        raw = self._post(f"{self.endpoint}/chat/completions", body, self._timeout)
        elapsed = max(0.0, self._clock() - start)
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"the local model returned no chat answer: {str(exc)[:120]}") from exc
        if not isinstance(text, str):
            raise RuntimeError("the local model returned no chat answer")
        return Reply(_THINK.sub("", text).strip(), str(data.get("model") or self.model), elapsed)
