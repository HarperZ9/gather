import json

import pytest

from gather.discord import DiscordSource, channel_id_from_target, parse_discord_messages


def _msg(mid: str, content: str) -> dict:
    return {
        "id": mid,
        "content": content,
        "timestamp": "2026-07-09T00:00:00.000000+00:00",
        "author": {"id": "u1", "username": "operator", "global_name": "Operator"},
        "attachments": [],
        "embeds": [],
    }


def test_channel_id_from_discord_targets():
    assert channel_id_from_target("1346756824233148527") == "1346756824233148527"
    assert channel_id_from_target("discord://channel/1105891499641684019") == "1105891499641684019"
    assert channel_id_from_target("https://discord.com/channels/1/1081121447960915989") == "1081121447960915989"


def test_parse_discord_messages_builds_receipted_items():
    payload = json.dumps([_msg("m1", "alpha"), _msg("m2", "beta")])
    items = parse_discord_messages(payload, "channel:123", fetched_at=1.0)
    assert [i.id for i in items] == ["m1", "m2"]
    assert items[0].kind == "message"
    assert items[0].provenance.source == "discord"
    assert items[0].provenance.method == "discord-api-message"
    assert items[0].provenance.ref == "channel:123"
    assert "raw_json:" in items[0].text
    assert all(i.verify() for i in items)


def test_parse_discord_messages_rejects_non_list_payload():
    with pytest.raises(ValueError, match="must be a list"):
        parse_discord_messages(json.dumps({"id": "m1"}), "channel:123", fetched_at=1.0)


def test_discord_source_uses_bot_header_and_paginates(monkeypatch):
    import gather.discord as discord_mod

    monkeypatch.setenv("GATHER_DISCORD_BOT_TOKEN", "bot-secret")
    calls = []

    def fake_http_get(url, *, timeout=20.0, headers=None, **kw):
        calls.append(url)
        assert headers == {"Authorization": "Bot bot-secret"}
        assert "bot-secret" not in url
        if len(calls) == 1:
            return json.dumps([_msg("3", "third"), _msg("2", "second")]).encode(), "application/json"
        assert "before=2" in url
        return json.dumps([_msg("1", "first")]).encode(), "application/json"

    monkeypatch.setattr(discord_mod, "http_get", fake_http_get)
    items = DiscordSource(clock=lambda: 1.0, max_messages=3, page_size=2).fetch("123")
    assert [i.id for i in items] == ["3", "2", "1"]
    assert len(calls) == 2
    assert all("bot-secret" not in i.text for i in items)
    assert all("bot-secret" not in i.provenance.ref for i in items)


def test_discord_source_refuses_credential_in_target(monkeypatch):
    monkeypatch.setenv("GATHER_DISCORD_BOT_TOKEN", "bot-secret")
    with pytest.raises(ValueError, match="must not appear"):
        DiscordSource().fetch("https://discord.com/channels/1/123?token=bot-secret")


def test_discord_guild_source_discovers_message_channels_and_active_threads(monkeypatch):
    import gather.discord as discord_mod
    from gather.discord import DiscordGuildSource

    monkeypatch.setenv("GATHER_DISCORD_BOT_TOKEN", "bot-secret")
    calls = []

    def fake_http_get(url, *, timeout=20.0, headers=None, **kw):
        calls.append(url)
        assert headers == {"Authorization": "Bot bot-secret"}
        assert "bot-secret" not in url
        if url.endswith("/guilds/42/channels"):
            return json.dumps([
                {"id": "1001", "name": "general", "type": 0},
                {"id": "1002", "name": "category", "type": 4},
                {"id": "1003", "name": "voice", "type": 2},
            ]).encode(), "application/json"
        if url.endswith("/guilds/42/threads/active"):
            return json.dumps({
                "threads": [
                    {"id": "2001", "name": "topic", "type": 11, "parent_id": "1001"}
                ]
            }).encode(), "application/json"
        if "/channels/1001/messages" in url:
            return json.dumps([_msg("m1", "channel message")]).encode(), "application/json"
        if "/channels/2001/messages" in url:
            return json.dumps([_msg("m2", "thread message")]).encode(), "application/json"
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(discord_mod, "http_get", fake_http_get)
    items = DiscordGuildSource(clock=lambda: 1.0, max_channels=10, max_messages_per_channel=1).fetch("guild:42")
    assert [i.id for i in items] == ["m1", "m2"]
    assert [i.provenance.ref for i in items] == ["channel:1001", "channel:2001"]
    assert all(i.meta["guild_id"] == "42" for i in items)
    assert [i.meta["discord_source_kind"] for i in items] == ["guild_channel", "guild_thread"]
    assert not any("/channels/1002/messages" in call or "/channels/1003/messages" in call for call in calls)


def test_run_config_builds_discord_guild_source():
    from gather.discord import DiscordGuildSource
    from gather.run_config import build_source

    source = build_source(
        "discord_guild",
        {"auth_env": "X", "max_channels": 3, "max_messages_per_channel": 2},
    )
    assert isinstance(source, DiscordGuildSource)
