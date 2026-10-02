"""Client setup fields become explicit launch arguments only.

The native MCPB manifest and the Claude plugin manifest share one set of setup
fields, so both clients offer the same options with the same defaults.
"""

SITE = "https://harperz9.github.io"
REPOSITORY = "https://github.com/HarperZ9/gather"

USER_CONFIG = {
    "workspace": {"type": "directory", "title": "Readable workspace",
        "description": "Local directory this profile may read. Choose only approved files.", "required": True},
    "allowed_origins": {"type": "string", "title": "Allowed public HTTPS origins (optional)",
        "description": 'JSON array, for example ["https://example.com"]. Leave [] to deny public network access. Requests send model-selected paths and queries to these origins.',
        "required": False, "default": "[]"},
    "loopback_origins": {"type": "string", "title": "Allowed local service origins (optional)",
        "description": 'JSON array, for example ["http://127.0.0.1:8080"]. Leave [] to deny local service access. Grant only services you intend the calling model to query.',
        "required": False, "default": "[]"},
}

LAUNCH_FLAGS = (("--workspace", "workspace"), ("--allow-origins-json", "allowed_origins"),
                ("--allow-loopback-origins-json", "loopback_origins"))


def launch_args():
    """Setup values as plain flag/value pairs; the client substitutes each value."""
    return [item for flag, key in LAUNCH_FLAGS for item in (flag, "${user_config." + key + "}")]


def native_manifest(spec, version, exe_name):
    return {
        "manifest_version": "0.3", "name": spec["name"] + "-local", "version": version,
        "display_name": spec["name"].title() + " Local", "description": spec["desc"],
        "author": {"name": "Zain Dana Harper"}, "license": "FSL-1.1-MIT",
        "server": {"type": "binary", "entry_point": "server/" + exe_name, "mcp_config": {
            "command": "${__dirname}/server/" + exe_name, "args": launch_args(), "env": {}}},
        "user_config": {key: dict(value) for key, value in USER_CONFIG.items()},
        "compatibility": {"platforms": ["win32"]},
    }


def claude_manifest(spec, version):
    """Claude plugin manifest: shared plugin fields plus the directory listing fields."""
    return {
        "name": spec["name"] + "-local", "version": version, "description": spec["desc"],
        "author": {"name": "Zain Dana Harper"}, "license": "FSL-1.1-MIT",
        "repository": REPOSITORY, "displayName": spec["name"].title(),
        "keywords": ["documents", "provenance", "citations", "receipts", "research", "local-first", "read-only"],
        "homepage": SITE + "/gather.html",
        "documentationUrl": REPOSITORY + "/blob/main/client-plugin/README.md",
        "supportUrl": SITE + "/plugins/gather/support.html",
        "privacyPolicyUrl": SITE + "/plugins/gather/privacy.html",
        "termsOfServiceUrl": SITE + "/plugins/gather/terms.html",
        "icon": "./.claude-plugin/icon.png",
        "userConfig": {key: dict(value) for key, value in USER_CONFIG.items()},
    }


def claude_mcp(spec):
    """Claude .mcp.json: plain arguments the directory validator can read."""
    args = ["-I", "-S", "-B", "${CLAUDE_PLUGIN_ROOT}/server/serve.py", *launch_args()]
    return {"mcpServers": {spec["name"]: {"command": "python3", "args": args, "env": {}}}}
