"""Every yt-dlp call the video edge makes starts through gather.spawn.

The channel listing, the metadata extraction and the one-track caption download each start
yt-dlp from an absolute path, in a private empty folder, with an environment allowlist and
``--ignore-config`` first. Decoys named ``yt-dlp``, ``ffmpeg`` and ``node`` sit in the working
folder, which is also on PATH, and must never run or count as found. The stand-in yt-dlp starts
its own ``ffmpeg`` by bare name during the caption download, the way the real one starts its
helpers, so the child's own lookup is checked too.
"""
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from test_spawn_children import (
    NO_STUB,
    WINDOWS,
    _executable,
    _launcher,
    _launcher_stub,
    _log,
    _write,
    decoy,
    no_stub_under_ci,
)

from gather.cli import main
from gather.grants import Grants
from gather.mcp import handle_request
from gather.video import VideoSource

URL = "https://www.youtube.com/watch?v=v1"
CHAN = "https://www.youtube.com/@chan"
FAKE_SECRET = "planted-fake-secret-value-91ad"

# The stand-in: log what it received, then answer the three call shapes Gather makes.
YT_DLP = r'''
import json, os, re, subprocess, sys
args = sys.argv[1:]
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"tool": "yt-dlp", "argv": args, "cwd": os.getcwd(),
                         "listing": sorted(os.listdir(".")), "env": sorted(os.environ)}) + "\n")
if "--flat-playlist" in args:
    entry = {"_type": "url", "ie_key": "Youtube", "id": "v1", "title": "REAL-VIDEO",
             "url": "https://www.youtube.com/watch?v=v1"}
    sys.stdout.write(json.dumps({"_type": "playlist", "id": "chan", "entries": [entry]}))
elif "--load-info-json" in args:
    info = json.load(open(args[args.index("--load-info-json") + 1], encoding="utf-8"))
    lang = re.sub(r"\\(.)", r"\1", args[args.index("--sub-langs") + 1])
    helper = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.strip()
    out = os.path.dirname(args[args.index("-o") + 1])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, info["id"] + "." + lang + ".vtt"), "w", encoding="utf-8") as fh:
        fh.write("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nREAL-caption " + helper + "\n")
else:
    asr = [{"ext": "vtt", "url": "https://example.org/timedtext?lang=en&kind=asr"}]
    sys.stdout.write(json.dumps({"id": "v1", "title": "REAL-VIDEO", "uploader": "Chan",
                                 "webpage_url": "https://www.youtube.com/watch?v=v1",
                                 "automatic_captions": {"en-orig": asr}}))
'''
FFMPEG = "import sys\nsys.stdout.write('REAL-ffmpeg')\n"


def _program(folder: Path, name: str, code: str) -> Path:
    """An executable ``name`` in ``folder`` that runs ``code`` under this Python."""
    if WINDOWS:
        folder.mkdir(parents=True, exist_ok=True)
        exe = _launcher(folder / f"{name}.exe", code)
        assert exe is not None, NO_STUB
        return exe
    import sys

    body = _write(folder / f"{name}-body.py", code)
    return _executable(_write(folder / name, f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n'))


def _yt_dlp(folder: Path, log: Path) -> Path:
    return _program(folder, "yt-dlp", f"LOG = {str(log)!r}\n" + YT_DLP)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Decoys in the working folder, which is on PATH; the real stand-ins elsewhere."""
    if WINDOWS and _launcher_stub() is None:
        no_stub_under_ci()
        pytest.skip(NO_STUB)  # a .cmd stand-in is refused the "%" in yt-dlp's -o template
    repo, bindir = tmp_path / "repo", tmp_path / "bin"
    log, marker = tmp_path / "log.jsonl", tmp_path / "PLANTED-RAN"
    repo.mkdir()
    for name in ("yt-dlp", "ffmpeg", "node"):
        decoy(repo, name, marker)
    (repo / "yt-dlp.conf").write_text('--exec "echo planted"\n', encoding="utf-8")
    _yt_dlp(bindir, log)
    _program(bindir, "ffmpeg", FFMPEG)
    system = ([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")] if WINDOWS
              else ["/usr/bin", "/bin"])
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", str(repo), str(bindir), *system]))
    for var in ("GATHER_YT_DLP", "GATHER_CHILD_ENV", "NoDefaultCurrentDirectoryInExePath"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLANTED_FAKE_API_KEY", FAKE_SECRET)
    monkeypatch.chdir(repo)
    return {"tmp": tmp_path, "repo": repo, "bindir": bindir, "log": log, "marker": marker,
            "store": str(tmp_path / "corpus")}


def _shape(call: dict) -> str:
    argv = call["argv"]
    if "--flat-playlist" in argv:
        return "listing"
    return "captions" if "--load-info-json" in argv else "metadata"


def _assert_spawned(calls: list[dict], repo: Path) -> None:
    assert calls, "the stand-in never ran"
    for call in calls:
        assert call["argv"][0] == "--ignore-config", call["argv"]
        assert os.path.normcase(os.path.realpath(call["cwd"])) != os.path.normcase(os.path.realpath(repo))
        assert call["listing"] == [], f"the child's folder is not empty: {call['listing']}"
        assert "PLANTED_FAKE_API_KEY" not in {k.upper() for k in call["env"]}


def test_extraction_and_caption_download_start_through_the_spawn_layer(world):
    out = VideoSource(js_runtime="none").gather(URL)
    assert not world["marker"].exists(), "a yt-dlp or ffmpeg planted in the working folder ran"
    calls = _log(world["log"])
    assert [_shape(c) for c in calls] == ["metadata", "captions"]
    _assert_spawned(calls, world["repo"])
    assert out.caption == "auto" and out.caption_lang == "en-orig"
    transcript = next(i for i in out.items if i.kind == "transcript")
    # the stand-in's own bare-name lookup of ffmpeg reached the real helper, not the plant
    assert transcript.text == "REAL-caption REAL-ffmpeg"


def test_a_channel_run_lists_and_gathers_through_the_spawn_layer(world, capsys):
    code = main(["channel", CHAN, "--store", world["store"], "--tabs", "videos", "--interval", "0",
                 "--jitter", "0", "--js-runtime", "none", "--json"])
    summary = json.loads(capsys.readouterr().out)
    assert code == 0 and summary["run"]["captions"]["auto"] == 1
    assert not world["marker"].exists()
    calls = _log(world["log"])
    assert [_shape(c) for c in calls] == ["listing", "metadata", "captions"]
    _assert_spawned(calls, world["repo"])
    assert summary["settings"]["yt_dlp_argv_prefix"] == ["yt-dlp", "--ignore-config"]


def test_the_override_variable_starts_every_call(world, monkeypatch):
    other = world["tmp"] / "other.jsonl"
    monkeypatch.setenv("GATHER_YT_DLP", str(_yt_dlp(world["tmp"] / "elsewhere", other)))
    VideoSource(js_runtime="none").gather(URL)
    assert [_shape(c) for c in _log(other)] == ["metadata", "captions"]
    assert not _log(world["log"]) and not world["marker"].exists()


@pytest.mark.parametrize("command", ["video", "channel"])
def test_a_relative_yt_dlp_path_is_refused_and_recorded(world, command, capsys):
    relative = os.path.join(".", "yt-dlp")
    extra = ["--store", world["store"], "--tabs", "videos"] if command == "channel" else []
    code = main([command, URL if command == "video" else CHAN, *extra, "--yt-dlp", relative,
                 "--js-runtime", "none"])
    err = capsys.readouterr().err
    assert code == 1 and not world["marker"].exists() and not _log(world["log"])
    assert "could not run yt-dlp" in err and str(world["repo"]) not in err
    if command == "channel":
        listing = json.loads(Path(world["store"], "intake", "listing.json").read_text(encoding="utf-8"))
        assert listing["tabs"]["videos"]["code"] == "tool-missing"


def test_auto_js_runtime_ignores_a_node_only_the_working_folder_holds(world, monkeypatch):
    assert shutil.which("node"), "a node reachable through the working folder must exist, or this proves nothing"
    assert "--js-runtimes" not in VideoSource(js_runtime="auto").base_argv
    tools = world["tmp"] / "node-home"
    tools.mkdir()
    if WINDOWS:
        (tools / "node.exe").write_bytes(b"MZ")  # found, never started: base_argv only looks
    else:
        _executable(_write(tools / "node", "#!/bin/sh\n"))
    monkeypatch.setenv("PATH", os.pathsep.join([str(world["repo"]), str(tools), os.environ["PATH"]]))
    assert VideoSource(js_runtime="auto").base_argv[2:4] == ["--js-runtimes", "node"]
    assert not world["marker"].exists()


# --- the MCP surface: a video job, with the new pass options, still needs its launch grant --------

def _run(config, grants=None):
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "gather.run", "arguments": {"config": config}}}
    return handle_request(req, grants=grants)["result"]


@pytest.fixture
def sealed(monkeypatch):
    attempts = []

    def refuse(kind):
        def _refuse(*args, **kwargs):
            attempts.append(kind)
            raise OSError(f"sealed test: {kind} refused")
        return _refuse

    monkeypatch.setattr(socket, "getaddrinfo", refuse("dns"))
    monkeypatch.setattr(socket, "create_connection", refuse("connect"))
    monkeypatch.setattr(subprocess, "run", refuse("subprocess"))
    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess"))
    return attempts


@pytest.mark.parametrize("captions", ["with", "skip", "only", "sometimes"])
def test_a_video_job_needs_the_network_grant_whatever_its_pass(sealed, captions):
    result = _run({"jobs": [{"source": "video", "target": URL, "captions": captions, "comments": True}]})
    body = result["structuredContent"]
    assert result["isError"] is True and body["code"] == "GRANT_REQUIRED"
    assert body["setup"] == "GATHER_ALLOW_NETWORK" and sealed == []


def test_an_unknown_pass_is_a_config_error_before_any_child_starts(sealed):
    grants = Grants(network_sources=frozenset({"video"}))
    result = _run({"jobs": [{"source": "video", "target": URL, "captions": "sometimes"}]}, grants)
    assert result["isError"] is True and "captions must be one of" in result["content"][0]["text"]
    assert sealed == []


def test_a_granted_video_job_runs_its_pass_through_the_spawn_layer(world):
    grants = Grants(network_sources=frozenset({"video"}))
    result = _run({"jobs": [{"source": "video", "target": URL, "captions": "skip"}]}, grants)
    assert result.get("isError") is not True, result
    calls = _log(world["log"])
    assert [_shape(c) for c in calls] == ["metadata"]
    _assert_spawned(calls, world["repo"])
    assert not world["marker"].exists()
