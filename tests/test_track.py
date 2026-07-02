"""Witnessable adaptive element tracking: MATCH / RELOCATED / DRIFT / GONE."""
from __future__ import annotations

from gather.dom import find, parse_dom
from gather.track import fingerprint, relocate

_V1 = "<html><body><p id='x'>Hello world</p></body></html>"


def _fp():
    return fingerprint(find(parse_dom(_V1), "p"))


def test_match_when_unchanged() -> None:
    r = relocate(_fp(), parse_dom(_V1))
    assert r.verdict == "MATCH"
    assert r.residual == 0.0


def test_relocated_when_element_moves_but_text_identical() -> None:
    v2 = "<html><body><section><p id='x'>Hello world</p></section></body></html>"
    r = relocate(_fp(), parse_dom(v2))
    assert r.verdict == "RELOCATED"
    assert r.residual == 0.0
    assert r.found_path != _fp().path


def test_drift_when_text_changes() -> None:
    v2 = "<html><body><p id='x'>Hello there</p></body></html>"
    r = relocate(_fp(), parse_dom(v2))
    assert r.verdict == "DRIFT"
    assert 0.0 < r.residual <= 1.0


def test_gone_when_element_removed() -> None:
    v2 = "<html><body><div>nothing like it</div></body></html>"
    r = relocate(_fp(), parse_dom(v2))
    assert r.verdict == "GONE"
    assert r.found_path == ""


def test_fingerprint_is_reproducible() -> None:
    assert _fp() == _fp()
    assert _fp().text_sha256 == fingerprint(find(parse_dom(_V1), "p")).text_sha256
