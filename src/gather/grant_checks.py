"""Grant checks for run configs and pilot manifests, made before anything runs.

These belong to the full CLI and MCP server. The local client profile does not
import this module.
"""
from __future__ import annotations

from collections.abc import Mapping

from gather.grants import Grants

DEFAULT_BROWSER = "chromium"
DEFAULT_AUTH_ENV = "GATHER_API_TOKEN"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"


def check_run_config(cfg: Mapping[str, object], grants: Grants) -> None:
    """Raise GrantRequired before anything runs if ``cfg`` needs a grant ``grants`` lacks."""
    jobs = cfg.get("jobs")
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, Mapping):
            continue
        source = job.get("source")
        if isinstance(source, str):
            grants.require_network(source)
            if source == "api":
                grants.require_credential(job.get("auth_env", DEFAULT_AUTH_ENV), job.get("target"))
            if source == "reddit":  # the app id and secret go only to the token host
                for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
                    grants.require_credential(name, REDDIT_TOKEN_URL)
            if source == "video" and job.get("api_key_env"):
                grants.require_credential(job.get("api_key_env"), YOUTUBE_API_URL)
    for key in ("synthesizer", "provenance"):
        command = cfg.get(key)
        if command:
            grants.require_command(command[0] if isinstance(command, list) and command else None)


def check_pilot_manifest(manifest: object, grants: Grants) -> None:
    """The same check for a validated pilot manifest (``gather.pilot_manifest.PilotManifest``)."""
    if getattr(manifest, "mode", None) != "live":
        return  # offline manifests replay local fixtures only
    for mission in getattr(manifest, "missions", ()):
        for source in mission.sources:
            grants.require_network(source.adapter)
            if source.adapter == "api":
                grants.require_credential(source.options.get("auth_env", DEFAULT_AUTH_ENV), source.target)
            if source.adapter == "browser":
                browser = source.options.get("browser", DEFAULT_BROWSER)
                if browser != DEFAULT_BROWSER or source.options.get("no_sandbox", False) is not False:
                    grants.require_command(browser)  # another executable, or the sandbox turned off
