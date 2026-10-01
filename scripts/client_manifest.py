"""Native client setup fields become explicit launch arguments only."""


def native_manifest(spec, version, exe_name):
    return {
        "manifest_version": "0.3", "name": spec["name"] + "-local", "version": version,
        "display_name": spec["name"].title() + " Local", "description": spec["desc"],
        "author": {"name": "Zain Dana Harper"}, "license": "FSL-1.1-MIT",
        "server": {"type": "binary", "entry_point": "server/" + exe_name, "mcp_config": {
            "command": "${__dirname}/server/" + exe_name,
            "args": ["--workspace", "${user_config.workspace}",
                     "--allow-origins-json", "${user_config.allowed_origins}",
                     "--allow-loopback-origins-json", "${user_config.loopback_origins}"], "env": {}}},
        "user_config": {
            "workspace": {"type": "directory", "title": "Readable workspace",
                "description": "Local directory this profile may read. Choose only approved files.", "required": True},
            "allowed_origins": {"type": "string", "title": "Allowed public HTTPS origins (optional)",
                "description": 'JSON array, for example ["https://example.com"]. Leave [] to deny public network access. Requests send model-selected paths and queries to these origins.',
                "required": False, "default": "[]"},
            "loopback_origins": {"type": "string", "title": "Allowed local service origins (optional)",
                "description": 'JSON array, for example ["http://127.0.0.1:8080"]. Leave [] to deny local service access. Grant only services you intend the calling model to query.',
                "required": False, "default": "[]"}},
        "compatibility": {"platforms": ["win32"]},
    }
