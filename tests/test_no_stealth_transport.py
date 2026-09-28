"""gather carries no browser-impersonation transport.

The stealth transport imitated a real browser's TLS fingerprint to get past bot
walls. That is detection evasion, so it is removed rather than kept behind an
extra. These tests hold the removal: the module is gone, no capability or extra
names it, and a request that would have needed impersonation comes back unmet
with a reason instead of being answered by some other route.
"""
from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

from gather import backends as B

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "gather"
EVASION_PACKAGES = ("curl_cffi", "curl-cffi", "tls_client", "undetected", "cloudscraper")


def test_the_stealth_module_is_gone():
    assert importlib.util.find_spec("gather.backends_stealth") is None
    assert not (SRC / "backends_stealth.py").exists()


def test_no_capability_names_impersonation():
    named = {value for name, value in vars(B).items() if name.startswith("CAP_")}
    assert "stealth" not in named
    assert not hasattr(B, "CAP_STEALTH")


def test_no_source_file_imports_an_impersonation_client():
    hits = [(path.name, pkg) for path in SRC.rglob("*.py")
            for pkg in EVASION_PACKAGES
            if pkg in path.read_text(encoding="utf-8")]
    assert hits == []


def test_no_extra_installs_an_impersonation_client():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project.get("optional-dependencies", {})
    assert "stealth" not in extras
    pins = [pin for deps in extras.values() for pin in deps] + list(project.get("dependencies", []))
    assert [pin for pin in pins if any(pkg in pin for pkg in EVASION_PACKAGES)] == []


def test_registry_never_reports_stealth_even_when_the_client_is_installed(monkeypatch):
    """Negative control: pretend curl_cffi is installed. The old registry
    self-registered a stealth backend in exactly this case."""
    real = importlib.util.find_spec

    def fake(name, *args, **kwargs):
        if name == "curl_cffi":
            return importlib.machinery.ModuleSpec("curl_cffi", None)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(B, "find_spec", fake)
    assert not B.default_registry(lambda url: "<html></html>").has("stealth")


def test_a_request_that_needed_impersonation_is_reported_unmet():
    result = B.render("https://example.invalid/", registry=B.default_registry(lambda u: ""),
                      require="stealth")
    assert result.status == "UNVERIFIABLE"
    assert result.reason == "no backend for capability 'stealth'"
    assert result.html == ""


def test_the_capability_card_draws_no_stealth_row():
    spec = json.loads((ROOT / "docs" / "art" / "gather.art.json").read_text(encoding="utf-8"))
    keys = [field["key"] for card in spec["cards"] for field in card["fields"]]
    assert "stealth" not in keys
