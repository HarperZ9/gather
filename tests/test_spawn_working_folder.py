"""A PATH entry that reaches Gather's working folder never starts a program planted there.

Gather 1.9.0 skipped only relative PATH entries. An absolute entry could still reach the working
folder: one naming it or a folder below it, another spelling of it, the same folder in quotes,
or a junction or symlink to it. On Windows a drive-relative command such as ``C:llm`` named a
file in the working folder too. The child also got those entries on its PATH, so a tool that
starts its own helper by bare name could start a copy planted there.

Each test plants decoys named like the program in the working folder, which leave a marker if
they ever run, and requires the real stand-in to answer instead. The controls keep entries that
only look related to the working folder, so a guard that drops too much fails them.
"""
import os
import sys
from types import SimpleNamespace

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
    stand_in,
)

from gather.item import make_item
from gather.model import SubprocessSynthesizer
from gather.pdf import PdfSource

SYSTEM = ([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")] if WINDOWS
          else ["/usr/bin", "/bin"])
windows_only = pytest.mark.skipif(not WINDOWS, reason="a Windows path form")


@pytest.fixture
def exe_decoys():
    """CreateProcess finds a bare name only as NAME.exe, so these tests need a real .exe decoy.

    Without pip's launcher stub they skip, except under CI, where they fail: a runner without
    the stub would otherwise report the working-folder routes as covered when nothing ran.
    """
    if WINDOWS and _launcher_stub() is None:
        no_stub_under_ci()
        pytest.skip(NO_STUB)


needs_exe = pytest.mark.usefixtures("exe_decoys")

# A tool that starts its own helper by bare name, the way whisper and yt-dlp start ffmpeg.
CHAIN = (
    "import subprocess, sys\n"
    "done = subprocess.run(['planted-helper'], capture_output=True, text=True)\n"
    "sys.stdout.write('REAL-chain ' + done.stdout.strip())\n"
)
HELPER = "import sys\nsys.stdout.write('REAL-helper')\n"


def _program(folder, name, code):
    """An executable ``name`` in ``folder`` that runs ``code`` under this Python."""
    if WINDOWS:
        folder.mkdir(parents=True, exist_ok=True)
        return _launcher(folder / f"{name}.exe", code)
    body = _write(folder / f"{name}-body.py", code)
    return _executable(_write(folder / name, f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n'))


def _item():
    return make_item(kind="document", id="a", title="A", text="x", source="docs", ref="a",
                     method="read", fetched_at=0.0)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Decoys in the working folder and one folder below it; the real stand-ins elsewhere."""
    repo, bindir = tmp_path / "repo", tmp_path / "bin"
    marker = tmp_path / "PLANTED-RAN"
    for folder in (repo, repo / "sub"):
        for name in ("pdftotext", "planted-llm"):
            decoy(folder, name, marker)
    log, other = tmp_path / "log.jsonl", tmp_path / "other.jsonl"
    for name in ("pdftotext", "planted-llm"):
        stand_in(bindir, name, log)
    (repo / "doc.pdf").write_bytes(b"not really a pdf")
    for var in ("GATHER_PDFTOTEXT", "GATHER_YT_DLP", "GATHER_TESSERACT", "GATHER_WHISPER",
                "GATHER_CHROMIUM", "GATHER_CHILD_ENV", "NoDefaultCurrentDirectoryInExePath"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(repo)

    def use_path(*entries, real=True):
        tail = [str(bindir)] if real else []
        monkeypatch.setenv("PATH", os.pathsep.join([*entries, *tail, *SYSTEM]))

    return SimpleNamespace(tmp=tmp_path, repo=repo, bindir=bindir, marker=marker, log=log,
                           other=other, path=use_path)


def _expect_the_real_pdftotext(world, log):
    items = PdfSource().fetch("doc.pdf")
    assert not world.marker.exists(), "a pdftotext planted in the working folder ran"
    assert items[0].text == "REAL-PDF text\r\nline two"
    assert _log(log), "the real pdftotext never ran"


ENTRIES = [
    pytest.param(lambda w: str(w.repo), id="names the working folder"),
    pytest.param(lambda w: str(w.repo / "sub"), id="names a folder below it"),
    pytest.param(lambda w: str(w.repo) + os.sep, id="ends in a separator"),
    pytest.param(lambda w: os.path.join(str(w.repo / "sub"), ".."), id="climbs back with dot-dot"),
    pytest.param(lambda w: f'"{w.repo}"', id="is quoted"),
    pytest.param(lambda w: f'"{w.repo / "sub"}"', id="is a quoted folder below it"),
    pytest.param(lambda w: str(w.repo).upper(), id="differs in letter case", marks=windows_only),
]


@needs_exe
@pytest.mark.parametrize("entry", ENTRIES)
def test_a_path_entry_reaching_the_working_folder_never_starts_a_plant(world, entry):
    world.path(entry(world))
    _expect_the_real_pdftotext(world, world.log)


def _link(target, link, kind):
    if kind == "junction":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as exc:  # a Windows symlink needs Developer Mode or the symlink privilege
            pytest.skip(f"symlink creation is not permitted here: {exc}")
    assert os.path.samefile(link, target), "the link does not reach its target, so it proves nothing"


@needs_exe
@pytest.mark.parametrize("kind", [pytest.param("junction", marks=windows_only), "symlink"])
@pytest.mark.parametrize("below", [False, True], ids=["to the working folder", "to a folder below it"])
def test_a_link_on_path_to_the_working_folder_never_starts_a_plant(world, kind, below):
    link = world.tmp / "link"
    _link(world.repo / "sub" if below else world.repo, link, kind)
    world.path(str(link))
    _expect_the_real_pdftotext(world, world.log)


@windows_only
@needs_exe
def test_a_drive_relative_command_never_starts_a_plant(world):
    drive = os.path.splitdrive(str(world.repo))[0]
    assert len(drive) == 2 and drive[1] == ":", "the working folder needs a drive letter"
    other = next(f"{c}:" for c in "QRSTUVWXYZ" if f"{c}:" != drive.upper())
    # an absolute entry on another drive joins with "C:planted-llm.exe" to that name alone,
    # which names the file in drive C:'s current folder: the working folder
    world.path(other + "\\nowhere")
    try:
        outcome = SubprocessSynthesizer([f"{drive}planted-llm"]).synthesize([_item()], "p")
    except FileNotFoundError as exc:
        outcome = exc
    assert not world.marker.exists(), "a drive-relative command started the program planted there"
    assert isinstance(outcome, FileNotFoundError), f"the command was not refused: {outcome!r}"


@needs_exe
def test_the_childs_own_lookup_never_reaches_the_working_folder(world):
    _program(world.bindir, "chain-llm", CHAIN)
    _program(world.bindir, "planted-helper", HELPER)
    decoy(world.repo, "planted-helper", world.marker)
    world.path(str(world.repo))
    out = SubprocessSynthesizer(["chain-llm"]).synthesize([_item()], "p")
    assert not world.marker.exists(), "the child's own lookup started the helper planted there"
    assert out == "REAL-chain REAL-helper"


# --- controls: entries that only look related to the working folder stay ------------------------

def test_a_sibling_folder_sharing_the_name_stays_on_path(world):
    sibling = world.tmp / f"{world.repo.name}-tools"
    stand_in(sibling, "pdftotext", world.other)
    world.path(str(sibling), real=False)
    _expect_the_real_pdftotext(world, world.other)


def test_a_folder_holding_the_working_folder_stays_on_path(world):
    stand_in(world.tmp, "pdftotext", world.other)
    world.path(str(world.tmp), real=False)
    _expect_the_real_pdftotext(world, world.other)


def test_an_override_inside_the_working_folder_still_runs(world, monkeypatch):
    tool = stand_in(world.repo / "tools", "pdftotext", world.other)
    monkeypatch.setenv("GATHER_PDFTOTEXT", str(tool))
    world.path(str(world.repo))
    _expect_the_real_pdftotext(world, world.other)
    assert not _log(world.log), "the PATH copy ran instead of the override"
