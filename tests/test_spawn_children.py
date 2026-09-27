"""Every child Gather starts resolves to an absolute path and runs in a private empty folder.

A decoy named like each child is planted in the caller's folder, with "." and an empty entry on
PATH, and it must never run. The real tool is a stand-in that logs its argv, working folder and
environment. On Windows the decoy is a real .exe (a pip-style launcher), because CreateProcess
looks in the current folder for NAME.exe before PATH; a .cmd decoy is planted beside it.
"""
import json
import os
import stat
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from gather.browser import BrowserSource
from gather.model import SubprocessSynthesizer
from gather.ocr import OcrSource
from gather.pdf import PdfSource
from gather.provenance import SubprocessProvenanceProvider
from gather.transcribe import TranscribeSource
from gather.video import VideoSource

WINDOWS = os.name == "nt"
FAKE_SECRET = "planted-fake-secret-value-4b2d"
TOOLS = ("pdftotext", "tesseract", "whisper", "yt-dlp", "chromium")

# The stand-in: log what it received, then answer like the tool it stands in for.
STAND_IN = r'''
import json, os, sys
args = sys.argv[1:]
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"tool": TOOL, "argv": args, "cwd": os.getcwd(),
                         "listing": sorted(os.listdir(".")),
                         "env": sorted(os.environ)}) + "\n")
target = {"pdftotext": lambda: args[args.index("--") + 1], "tesseract": lambda: args[0],
          "whisper": lambda: args[0]}.get(TOOL)
if target is not None and not os.path.isfile(target()):
    sys.stderr.write("input file not found from the child's folder")
    sys.exit(1)
if TOOL == "pdftotext":
    sys.stdout.buffer.write(b"REAL-PDF text\r\nline two")
elif TOOL == "tesseract":
    sys.stdout.write("REAL-OCR text")
elif TOOL == "whisper":
    out = args[args.index("--output_dir") + 1]
    open(os.path.join(out, "talk.txt"), "w", encoding="utf-8").write("REAL-ASR text")
elif TOOL == "yt-dlp":
    if "--dump-single-json" in args:
        sys.stdout.write(json.dumps({"id": "v1", "title": "REAL-VIDEO", "description": "d",
                                     "webpage_url": "https://example.org/v"}))
elif TOOL == "chromium":
    sys.stdout.write("<html><head><title>REAL-DOM</title></head><body>REAL-DOM</body></html>")
else:
    sys.stdout.write("REAL-" + TOOL + " " + sys.stdin.read()[:40])
'''


def _write(path, text, newline=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)
    return path


def _executable(path):
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def stand_in(folder: Path, tool: str, log: Path) -> Path:
    code = f"LOG = {str(log)!r}\nTOOL = {tool!r}\n" + STAND_IN
    if WINDOWS:
        folder.mkdir(parents=True, exist_ok=True)
        exe = _launcher(folder / f"{tool}.exe", code)
        if exe is not None:
            return exe
        body = _write(folder / f"{tool}-body.py", code)
        return _write(folder / f"{tool}.cmd", f'@echo off\r\n"{sys.executable}" "{body}" %*\r\n', newline="")
    body = _write(folder / f"{tool}-body.py", code)
    return _executable(_write(folder / tool, f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n'))


def _launcher(path: Path, code: str):
    """A real NAME.exe that runs ``code`` under this Python, the way pip builds console scripts."""
    stub = _launcher_stub()
    if stub is None:
        return None
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("__main__.py", code)
    exe = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    path.write_bytes(stub + f"#!{exe}\n".encode() + buf.getvalue())
    return path


def _launcher_stub():
    """A pip-style console-script launcher, if one ships with this Python."""
    names = ("t64.exe",) if sys.maxsize > 2**32 else ("t32.exe",)
    for base in {sys.prefix, sys.base_prefix}:
        for name in names:
            path = Path(base) / "Lib" / "site-packages" / "pip" / "_vendor" / "distlib" / name
            if path.is_file():
                return path.read_bytes()
    return None


NO_STUB = "no pip launcher stub to build a real .exe decoy"


def no_stub_under_ci() -> None:
    """Fail, under CI, a Windows run that cannot build a real .exe decoy.

    Without pip's launcher stub the decoy is only a .cmd, and CreateProcess never picks a .cmd
    for a bare name, so the decoy tests would pass on code that runs a planted NAME.exe.
    """
    if os.environ.get("CI", "").strip().lower() not in ("", "0", "false"):
        pytest.fail(f"{NO_STUB}; CI must run the Windows decoy tests with pip installed")


def decoy(folder: Path, name: str, marker: Path) -> None:
    """Files named like the child that write ``marker`` if they ever run."""
    code = f"open({str(marker)!r}, 'a').write('ran')\nprint('PLANTED')\n"
    if WINDOWS:
        _write(folder / f"{name}.cmd", f'@echo off\r\necho x>> "{marker}"\r\necho PLANTED\r\n', newline="")
        if _launcher(folder / f"{name}.exe", code) is None:
            no_stub_under_ci()
    else:
        _executable(_write(folder / name, f'#!/bin/sh\necho x >> "{marker}"\necho PLANTED\n'))


def _log(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


@pytest.fixture
def planted(tmp_path, monkeypatch):
    """A caller folder full of decoys, "." first on PATH, stand-ins later on PATH."""
    repo, bindir, log, marker = tmp_path / "repo", tmp_path / "bin", tmp_path / "log.jsonl", tmp_path / "PLANTED-RAN"
    repo.mkdir()
    for tool in (*TOOLS, "planted-llm", "planted-prov"):
        decoy(repo, tool, marker)
        stand_in(bindir, tool, log)
    (repo / "yt-dlp.conf").write_text('--exec "echo planted"\n', encoding="utf-8")
    for name in ("doc.pdf", "scan.png", "talk.wav"):
        (repo / name).write_bytes(b"not really media")
    system = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")] if WINDOWS else ["/usr/bin", "/bin"]
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", str(bindir), *system]))
    for var in ("GATHER_PDFTOTEXT", "GATHER_YT_DLP", "GATHER_TESSERACT", "GATHER_WHISPER",
                "GATHER_CHROMIUM", "GATHER_CHILD_ENV", "NoDefaultCurrentDirectoryInExePath"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLANTED_FAKE_API_KEY", FAKE_SECRET)
    monkeypatch.setattr("gather.net._host_is_private", lambda host: False)
    monkeypatch.chdir(repo)
    return {"repo": repo, "log": log, "marker": marker}


def _fetch(tool):
    if tool == "pdftotext":
        return PdfSource().fetch("doc.pdf")
    if tool == "tesseract":
        return OcrSource().fetch("scan.png")
    if tool == "whisper":
        return TranscribeSource().fetch("talk.wav")
    if tool == "yt-dlp":
        return VideoSource().fetch("https://example.org/v")
    return BrowserSource().fetch("https://example.org/page")


def _assert_private(entries, repo):
    assert entries, "the stand-in never ran"
    for entry in entries:
        assert os.path.normcase(os.path.realpath(entry["cwd"])) != os.path.normcase(os.path.realpath(repo))
        assert entry["listing"] == [], f"the child's folder is not empty: {entry['listing']}"


@pytest.mark.parametrize("tool", TOOLS)
def test_a_child_planted_in_the_callers_folder_never_runs(tool, planted):
    items = _fetch(tool)
    assert not planted["marker"].exists(), f"a planted {tool} in the caller's folder ran"
    assert "REAL-" in " ".join(it.text + it.title for it in items)
    _assert_private(_log(planted["log"]), planted["repo"])


def test_tool_output_reaches_the_receipt_byte_for_byte(planted):
    # no newline translation: a CRLF the tool wrote is the CRLF the receipt hashes
    assert PdfSource().fetch("doc.pdf")[0].text == "REAL-PDF text\r\nline two"


@pytest.mark.parametrize("tool", TOOLS)
def test_a_child_never_sees_an_unlisted_variable(tool, planted):
    _fetch(tool)
    assert _log(planted["log"]), "the stand-in never ran"
    for entry in _log(planted["log"]):
        assert "PLANTED_FAKE_API_KEY" not in {k.upper() for k in entry["env"]}


def test_a_planted_yt_dlp_conf_has_no_effect(planted):
    VideoSource().fetch("https://example.org/v")
    calls = _log(planted["log"])
    assert calls and all(c["argv"][0] == "--ignore-config" for c in calls)
    assert all("yt-dlp.conf" not in c["listing"] for c in calls)


@pytest.mark.parametrize("key", ["synthesizer", "provenance"])
def test_a_command_planted_in_the_callers_folder_never_runs(key, planted):
    from gather.item import make_item

    item = make_item(kind="document", id="a", title="A", text="x", source="docs", ref="a",
                     method="read", fetched_at=0.0)
    if key == "synthesizer":
        out = SubprocessSynthesizer(["planted-llm", "-m", "x"]).synthesize([item], "summarize")
        assert out.startswith("REAL-planted-llm")
    else:
        verdict = SubprocessProvenanceProvider(["planted-prov"]).origin(item)
        assert "error" in verdict  # the stand-in prints text, not JSON: it ran, the decoy did not
    assert not planted["marker"].exists()
    _assert_private(_log(planted["log"]), planted["repo"])


def test_child_env_passes_only_the_variables_the_operator_names(planted, monkeypatch):
    monkeypatch.setenv("GATHER_CHILD_ENV", "PLANTED_FAKE_API_KEY")
    from gather.item import make_item

    item = make_item(kind="document", id="a", title="A", text="x", source="docs", ref="a",
                     method="read", fetched_at=0.0)
    SubprocessSynthesizer(["planted-llm"]).synthesize([item], "p")
    assert "PLANTED_FAKE_API_KEY" in {k.upper() for k in _log(planted["log"])[-1]["env"]}


def test_a_relative_command_path_is_refused(planted):
    from gather.item import make_item

    item = make_item(kind="document", id="a", title="A", text="x", source="docs", ref="a",
                     method="read", fetched_at=0.0)
    with pytest.raises(FileNotFoundError):
        SubprocessSynthesizer([os.path.join(".", "planted-llm")]).synthesize([item], "p")
    assert "error" in SubprocessProvenanceProvider([os.path.join(".", "planted-prov")]).origin(item)
    assert not planted["marker"].exists()


def test_the_override_variable_wins_and_must_be_absolute(planted, monkeypatch, tmp_path):
    other_log = tmp_path / "other.jsonl"
    monkeypatch.setenv("GATHER_PDFTOTEXT", str(stand_in(tmp_path / "elsewhere", "pdftotext", other_log)))
    PdfSource().fetch("doc.pdf")
    assert _log(other_log) and not _log(planted["log"])
    monkeypatch.setenv("GATHER_PDFTOTEXT", "pdftotext")
    with pytest.raises(FileNotFoundError, match="GATHER_PDFTOTEXT|absolute"):
        PdfSource().fetch("doc.pdf")


def test_a_missing_tool_is_reported_by_name_without_a_path(planted, monkeypatch):
    monkeypatch.setenv("PATH", ".")
    with pytest.raises(FileNotFoundError) as info:
        PdfSource().fetch("doc.pdf")
    assert info.value.filename == "pdftotext"
    assert str(planted["repo"]) not in str(info.value)
    assert not planted["marker"].exists()


# --- the real tools, where installed ------------------------------------------------------------

_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 41>>stream\nBT /F1 12 Tf 20 50 Td (gather real pdf) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def _real(name):
    import shutil

    return shutil.which(name)


@pytest.mark.skipif(not _real("pdftotext"), reason="pdftotext is not installed")
def test_real_pdftotext_reads_a_relative_path_from_a_private_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "real.pdf").write_bytes(_MINIMAL_PDF)
    items = PdfSource().fetch("real.pdf")
    assert "gather real pdf" in items[0].text


@pytest.mark.skipif(not _real("yt-dlp"), reason="yt-dlp is not installed")
def test_real_yt_dlp_ignores_a_conf_planted_in_the_callers_folder(tmp_path, monkeypatch):
    import subprocess

    (tmp_path / "yt-dlp.conf").write_text("--version\n", encoding="utf-8")
    control = subprocess.run([_real("yt-dlp"), "--dump-single-json", "--skip-download", "--",
                              "https://example.invalid/x"], cwd=tmp_path, capture_output=True,
                             text=True, timeout=120)
    assert control.returncode == 0 and control.stdout.strip()[:2].isdigit(), \
        "the planted conf must work without the fix, or this test proves nothing"
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="yt-dlp failed"):
        VideoSource(timeout=120).fetch("https://example.invalid/x")
