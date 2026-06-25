import json

from gather.cli import main


def _write(tmp_path):
    info = tmp_path / "v.info.json"
    info.write_text(json.dumps({
        "id": "abc123", "title": "Test Video", "uploader": "TestChan",
        "comments": [{"id": "c1", "text": "great", "author": "v"}],
    }), encoding="utf-8")
    vtt = tmp_path / "v.en.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello world\n", encoding="utf-8")
    return info, vtt


def test_parse_command_emits_catalog_and_digest(tmp_path, capsys):
    info, vtt = _write(tmp_path)
    rc = main(["parse", str(info), "--vtt", str(vtt), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert sorted(r["kind"] for r in out["catalog"]) == ["comment", "metadata", "transcript"]
    assert len(out["digest"]["seal"]) == 64


def test_parse_command_scope_filters(tmp_path, capsys):
    info, vtt = _write(tmp_path)
    rc = main(["parse", str(info), "--vtt", str(vtt), "--scope", "hello", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "transcript" in {r["kind"] for r in out["catalog"]}  # the transcript says "hello"
    assert out["dropped"] >= 1                                   # metadata/comment do not, dropped


def test_run_command_with_model_synthesizer_persists_a_synthesized_item(tmp_path):
    import sys

    from gather.store import Corpus

    note = tmp_path / "n.md"
    note.write_text("about tiling and monotiles", encoding="utf-8")
    corp = tmp_path / "corpus"
    cfg = tmp_path / "job.json"
    cfg.write_text(json.dumps({
        "jobs": [{"source": "docs", "target": str(note)}],
        "synthesizer": [sys.executable, "-c", "import sys; sys.stdout.write('SUMMARY: tilings')"],
        "store": str(corp),
    }), encoding="utf-8")
    assert main(["run", str(cfg)]) == 0
    methods = {r["method"] for r in Corpus(str(corp)).rows()}
    assert "synthesized" in methods   # the model edge ran and produced a synthesized item


def test_run_command_rejects_a_non_list_synthesizer(tmp_path, capsys):
    cfg = tmp_path / "bad.json"
    cfg.write_text(json.dumps({"jobs": [{"source": "docs", "target": "x"}], "synthesizer": "llm"}),
                   encoding="utf-8")
    assert main(["run", str(cfg)]) == 1
    assert "bad config" in capsys.readouterr().err


def test_no_command_prints_help(capsys):
    assert main([]) == 1
    assert "usage: gather" in capsys.readouterr().out
