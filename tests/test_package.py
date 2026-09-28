import re
import subprocess
import sys
import tomllib
from pathlib import Path

import gather

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_exposed():
    assert isinstance(gather.__version__, str) and gather.__version__.count(".") == 2


def test_stable_surface_is_importable_from_the_top_level():
    # the curated public API works without reaching into submodules
    it = gather.make_item(kind="document", id="a", title="A", text="hello",
                          source="web", ref="a", method="http-get", fetched_at=1.0)
    assert isinstance(it, gather.Item)
    d = gather.digest([it])
    assert gather.verify_digest(d) is True
    for name in ("Corpus", "gather_run", "recall", "Query", "RunRecord", "Source", "Catalog",
                 "derive", "synthesize_item", "NullSynthesizer", "content_hash"):
        assert hasattr(gather, name), name


def test_all_names_resolve():
    for name in gather.__all__:
        assert hasattr(gather, name), name


def test_source_checkout_supports_cli_module_path():
    completed = subprocess.run(
        [sys.executable, "-m", "gather.cli", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Gather: accountable research intake" in completed.stdout


# Packages whose purpose is to get past bot detection: TLS or browser fingerprint
# impersonation, patched automation browsers, challenge solvers, rotating User-Agents.
# A name list catches these by name only; a new tool under another name still needs review.
EVASION_PACKAGES = frozenset({
    "curl-cffi", "tls-client", "primp", "rnet", "hrequests", "cloudscraper",
    "undetected-chromedriver", "playwright-stealth", "selenium-stealth", "patchright",
    "camoufox", "nodriver", "botasaurus", "fake-useragent",
})


def _requirement_name(req: str) -> str:
    return re.sub(r"[-_.]+", "-", re.split(r"[\s<>=!~;\[(@]", req.strip(), maxsplit=1)[0]).lower()


def test_no_dependency_or_extra_ships_bot_detection_evasion():
    """The stealth extra (curl_cffi TLS impersonation) is gone, and the all extra no longer
    pulls it. Nothing the package can install is there to impersonate a browser."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project.get("optional-dependencies", {})
    assert "stealth" not in extras
    groups = {"dependencies": project.get("dependencies", []), **extras}
    shipped = {(group, _requirement_name(req)) for group, reqs in groups.items() for req in reqs}
    assert not {(g, n) for g, n in shipped if n in EVASION_PACKAGES}
    assert _requirement_name("curl_cffi>=0.7") == "curl-cffi"  # the name check can match
