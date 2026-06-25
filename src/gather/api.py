from __future__ import annotations

import json
import time
from typing import Any

from gather.credentials import require_secret
from gather.item import Item, make_item
from gather.net import decode_body, http_get


def _records(payload: Any, items_key: str | None) -> list[dict]:
    """The records in an API payload: the array at ``items_key``, or the top-level list, or the
    single object wrapped in a list."""
    if items_key is not None:
        data = payload.get(items_key, []) if isinstance(payload, dict) else []
    else:
        data = payload
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def parse_api(
    payload: str | bytes,
    url: str,
    *,
    fetched_at: float,
    items_key: str | None = None,
    id_key: str = "id",
    title_key: str = "title",
    text_key: str | None = None,
    method: str = "api-get",
) -> list[Item]:
    """Turn a JSON API response into one Item per record. Pure: no network.

    Each record becomes an Item whose text is the record's ``text_key`` field if given, else the
    record serialized as canonical JSON (so the receipt fingerprints the exact record). The id and
    title are read from ``id_key`` / ``title_key`` when present. ``ref`` is the request URL. No
    credential is ever placed in an Item or its receipt. Raises ValueError on malformed JSON.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid API JSON: {exc}") from exc
    items: list[Item] = []
    for i, rec in enumerate(_records(data, items_key)):
        text = str(rec.get(text_key, "")) if text_key else json.dumps(rec, sort_keys=True, ensure_ascii=False)
        rid = str(rec.get(id_key, i))
        items.append(
            make_item(
                kind="record", id=rid, title=str(rec.get(title_key, "")), text=text,
                source="api", ref=url, method=method, fetched_at=fetched_at,
            )
        )
    return items


class ApiSource:
    """An authenticated JSON-API adapter: the worked example of the credentials-isolation pattern.

    The impure edge that needs a secret. The token is read from the environment by name through
    require_secret (never from source, a config, or the URL), sent in an Authorization header (so
    it never reaches the URL, the receipt, or the disk), and the records come back through the pure
    parse_api. Point another authenticated source at this shape: env in, header out, secret never
    witnessed. fetch(target) takes the full request URL; needs the named env var set and network.
    """

    name = "api"

    def __init__(
        self,
        *,
        clock=time.time,
        auth_env: str = "GATHER_API_TOKEN",
        auth_scheme: str = "Bearer",
        items_key: str | None = None,
        id_key: str = "id",
        title_key: str = "title",
        text_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._clock = clock
        self._auth_env = auth_env
        self._auth_scheme = auth_scheme
        self._items_key = items_key
        self._id_key = id_key
        self._title_key = title_key
        self._text_key = text_key
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        token = require_secret(self._auth_env)
        body, ctype = http_get(
            target, timeout=self._timeout,
            headers={"Authorization": f"{self._auth_scheme} {token}"},
        )
        return parse_api(
            decode_body(body, ctype), target, fetched_at=float(self._clock()),
            items_key=self._items_key, id_key=self._id_key,
            title_key=self._title_key, text_key=self._text_key,
        )
