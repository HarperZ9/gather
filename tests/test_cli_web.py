"""CLI wiring for the web-data capabilities (offline: caps + local-file paths)."""
from __future__ import annotations

import json

from gather.cli import build_parser, main

_HTML = "<html><head><title>T</title></head><body><h1>H</h1><p>para</p></body></html>"


def test_caps_command_reports_json(capsys) -> None:
    assert main(["caps", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "parser" in out and "capabilities" in out
    assert "fetch" in out["capabilities"]


def test_extract_command_on_local_file(tmp_path, capsys) -> None:
    f = tmp_path / "page.html"
    f.write_text(_HTML, encoding="utf-8")
    assert main(["extract", str(f)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["url"].startswith("file://")
    assert receipt["title"] == "T"
    assert any(b["tag"] == "h1" for b in receipt["blocks"])


def test_markdown_command_on_local_file(tmp_path, capsys) -> None:
    f = tmp_path / "page.html"
    f.write_text(_HTML, encoding="utf-8")
    assert main(["markdown", str(f)]) == 0
    assert "# H" in capsys.readouterr().out


def test_crawl_subcommand_is_wired() -> None:
    args = build_parser().parse_args(["crawl", "http://e.com", "--depth", "1", "--max-pages", "3"])
    assert args.func.__name__ == "cmd_crawl"
    assert args.depth == 1 and args.max_pages == 3
