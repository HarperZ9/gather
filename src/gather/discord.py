from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any

from gather.credentials import require_secret
from gather.item import Item, make_item
from gather.net import decode_body, http_get

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_METHOD = "discord-api-message"
MESSAGEABLE_CHANNEL_TYPES = {0, 5}
THREAD_CHANNEL_TYPES = {10, 11, 12}


def channel_id_from_target(target: str) -> str:
    """Return a Discord channel/thread id from a raw id, discord:// URL, or channel URL."""
    value = target.strip()
    if value.isdigit():
        return value
    if value.startswith("discord://channel/"):
        candidate = value.rsplit("/", 1)[-1].strip()
        if candidate.isdigit():
            return candidate
    parsed = urllib.parse.urlsplit(value)
    if parsed.netloc.lower() in {"discord.com", "www.discord.com", "canary.discord.com", "ptb.discord.com"}:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "channels" and parts[2].isdigit():
            return parts[2]
    raise ValueError("Discord target must be a channel id, discord://channel/<id>, or Discord channel URL")


def guild_id_from_target(target: str) -> str:
    """Return a Discord guild id from a raw id, guild: id, discord:// URL, or server URL."""
    value = target.strip()
    if value.startswith("guild:"):
        candidate = value.split(":", 1)[1].strip()
        if candidate.isdigit():
            return candidate
    if value.isdigit():
        return value
    if value.startswith("discord://guild/"):
        candidate = value.rsplit("/", 1)[-1].strip()
        if candidate.isdigit():
            return candidate
    parsed = urllib.parse.urlsplit(value)
    if parsed.netloc.lower() in {"discord.com", "www.discord.com", "canary.discord.com", "ptb.discord.com"}:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "channels" and parts[1].isdigit():
            return parts[1]
    raise ValueError("Discord guild target must be a guild id, guild:<id>, discord://guild/<id>, or Discord server URL")


def _author_label(author: dict[str, Any]) -> str:
    name = author.get("global_name") or author.get("username") or "unknown"
    author_id = author.get("id")
    return f"{name} ({author_id})" if author_id else str(name)


def _attachment_lines(message: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for attachment in message.get("attachments", []) or []:
        if not isinstance(attachment, dict):
            continue
        filename = attachment.get("filename", "")
        url = attachment.get("url", "")
        ctype = attachment.get("content_type", "")
        size = attachment.get("size", "")
        lines.append(f"- {filename} {url} {ctype} {size}".strip())
    return lines


def _embed_lines(message: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for embed in message.get("embeds", []) or []:
        if not isinstance(embed, dict):
            continue
        title = embed.get("title", "")
        url = embed.get("url", "")
        description = embed.get("description", "")
        lines.append(f"- {title} {url} {description}".strip())
    return lines


def _message_text(message: dict[str, Any]) -> str:
    raw_author = message.get("author")
    author = raw_author if isinstance(raw_author, dict) else {}
    content = message.get("content", "")
    timestamp = message.get("timestamp", "")
    lines = [
        f"message_id: {message.get('id', '')}",
        f"timestamp: {timestamp}",
        f"author: {_author_label(author)}",
        "content:",
        str(content),
    ]
    attachments = _attachment_lines(message)
    if attachments:
        lines.append("attachments:")
        lines.extend(attachments)
    embeds = _embed_lines(message)
    if embeds:
        lines.append("embeds:")
        lines.extend(embeds)
    lines.append("raw_json:")
    lines.append(json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


def parse_discord_messages(payload: str | bytes, channel_ref: str, *, fetched_at: float) -> list[Item]:
    """Turn a Discord messages API payload into one receipted Item per message."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid Discord JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("Discord messages payload must be a list")
    items: list[Item] = []
    for i, message in enumerate(data):
        if not isinstance(message, dict):
            continue
        message_id = str(message.get("id", i))
        raw_author = message.get("author")
        author = raw_author if isinstance(raw_author, dict) else {}
        items.append(
            make_item(
                kind="message",
                id=message_id,
                title=f"Discord message {message_id}",
                text=_message_text(message),
                source="discord",
                ref=channel_ref,
                method=DISCORD_METHOD,
                fetched_at=fetched_at,
                meta={
                    "channel": channel_ref,
                    "message_id": message_id,
                    "author_id": str(author.get("id", "")),
                    "timestamp": str(message.get("timestamp", "")),
                    "attachment_count": len(message.get("attachments", []) or []),
                    "embed_count": len(message.get("embeds", []) or []),
                },
            )
        )
    return items


def parse_discord_guild_channels(payload: str | bytes) -> list[dict[str, Any]]:
    """Return raw Discord channel records from a guild channels payload."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid Discord guild channels JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("Discord guild channels payload must be a list")
    return [record for record in data if isinstance(record, dict) and str(record.get("id", "")).isdigit()]


def parse_discord_active_threads(payload: str | bytes) -> list[dict[str, Any]]:
    """Return raw active thread records from Discord's guild active-threads payload."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid Discord active threads JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Discord active threads payload must be an object")
    threads = data.get("threads", [])
    if not isinstance(threads, list):
        return []
    return [record for record in threads if isinstance(record, dict) and str(record.get("id", "")).isdigit()]


class DiscordSource:
    """Discord channel/thread intake through the official REST API.

    This adapter uses a bot token from the environment and sends it only in an
    Authorization header. It does not use a personal user token, selfbot access,
    browser session scraping, or desktop UI automation. The witnessed ref is the
    channel id, not the credential-bearing API request.
    """

    name = "discord"

    def __init__(
        self,
        *,
        clock=time.time,
        auth_env: str = "GATHER_DISCORD_BOT_TOKEN",
        max_messages: int = 100,
        page_size: int = 100,
        api_base: str = DISCORD_API_BASE,
        timeout: float = 20.0,
    ) -> None:
        self._clock = clock
        self._auth_env = auth_env
        self._max_messages = max(0, int(max_messages))
        self._page_size = max(1, min(100, int(page_size)))
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout

    def fetch(self, target: str) -> list[Item]:
        token = require_secret(self._auth_env)
        if token in target:
            raise ValueError("the Discord credential must not appear in the target")
        channel_id = channel_id_from_target(target)
        channel_ref = f"channel:{channel_id}"
        items: list[Item] = []
        before: str | None = None
        while len(items) < self._max_messages:
            limit = min(self._page_size, self._max_messages - len(items))
            params = {"limit": str(limit)}
            if before:
                params["before"] = before
            url = f"{self._api_base}/channels/{channel_id}/messages?{urllib.parse.urlencode(params)}"
            body, ctype = http_get(
                url,
                timeout=self._timeout,
                headers={"Authorization": f"Bot {token}"},
            )
            batch = parse_discord_messages(
                decode_body(body, ctype),
                channel_ref,
                fetched_at=float(self._clock()),
            )
            if not batch:
                break
            items.extend(batch)
            before = batch[-1].id
            if len(batch) < limit:
                break
        return items


class DiscordGuildSource:
    """Discord guild/server intake through official bot API discovery.

    A guild capture first discovers accessible text/news channels and active
    threads, then captures each target through the same message receipt path as
    DiscordSource. This keeps server-wide intake explicit and bounded rather
    than treating a raw id as both a channel and a guild.
    """

    name = "discord_guild"

    def __init__(
        self,
        *,
        clock=time.time,
        auth_env: str = "GATHER_DISCORD_BOT_TOKEN",
        max_channels: int = 25,
        max_messages_per_channel: int = 100,
        page_size: int = 100,
        api_base: str = DISCORD_API_BASE,
        timeout: float = 20.0,
    ) -> None:
        self._clock = clock
        self._auth_env = auth_env
        self._max_channels = max(0, int(max_channels))
        self._max_messages_per_channel = max(0, int(max_messages_per_channel))
        self._page_size = max(1, min(100, int(page_size)))
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout

    def _get_json(self, token: str, path: str) -> str:
        body, ctype = http_get(
            f"{self._api_base}{path}",
            timeout=self._timeout,
            headers={"Authorization": f"Bot {token}"},
        )
        return decode_body(body, ctype)

    def _message_targets(self, token: str, guild_id: str) -> list[dict[str, str]]:
        channels = parse_discord_guild_channels(
            self._get_json(token, f"/guilds/{guild_id}/channels")
        )
        targets: list[dict[str, str]] = []
        seen: set[str] = set()
        for channel in channels:
            try:
                channel_type = int(channel.get("type", -1))
            except (TypeError, ValueError):
                continue
            if channel_type not in MESSAGEABLE_CHANNEL_TYPES:
                continue
            channel_id = str(channel["id"])
            if channel_id in seen:
                continue
            seen.add(channel_id)
            targets.append({
                "id": channel_id,
                "name": str(channel.get("name", "")),
                "kind": "guild_channel",
            })
        threads = parse_discord_active_threads(
            self._get_json(token, f"/guilds/{guild_id}/threads/active")
        )
        for thread in threads:
            try:
                thread_type = int(thread.get("type", -1))
            except (TypeError, ValueError):
                continue
            if thread_type not in THREAD_CHANNEL_TYPES:
                continue
            thread_id = str(thread["id"])
            if thread_id in seen:
                continue
            seen.add(thread_id)
            targets.append({
                "id": thread_id,
                "name": str(thread.get("name", "")),
                "kind": "guild_thread",
            })
        return targets[:self._max_channels]

    def fetch(self, target: str) -> list[Item]:
        token = require_secret(self._auth_env)
        if token in target:
            raise ValueError("the Discord credential must not appear in the target")
        guild_id = guild_id_from_target(target)
        if self._max_channels <= 0 or self._max_messages_per_channel <= 0:
            return []
        channel_source = DiscordSource(
            clock=self._clock,
            auth_env=self._auth_env,
            max_messages=self._max_messages_per_channel,
            page_size=self._page_size,
            api_base=self._api_base,
            timeout=self._timeout,
        )
        items: list[Item] = []
        for message_target in self._message_targets(token, guild_id):
            for item in channel_source.fetch(message_target["id"]):
                item.meta.update({
                    "guild_id": guild_id,
                    "channel_id": message_target["id"],
                    "channel_name": message_target["name"],
                    "discord_source_kind": message_target["kind"],
                })
                items.append(item)
        return items
