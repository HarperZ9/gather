"""The lexical network/device check and the Windows link walk in gather.localpath.

Every case here runs on every platform: Windows rules are forced where a case needs them, and the
link walk runs against a fake tree. The tests at the end that use real junctions and symlinks run
on Windows only, since only Windows links can reach an SMB share by their target text.
"""
import json
import ntpath
import os

import pytest

import gather.localpath as lp
from gather.localpath import (
    DEVICE,
    LINK,
    MISSING,
    NETWORK,
    LinkFs,
    LinkUnreadable,
    NonLocalPath,
    check_entry,
    check_links,
    check_run_paths,
    classify,
    require_local,
)

BS = "\\"


def w(*parts):
    """Join with backslashes, so no case depends on how a test file spells an escape."""
    return BS.join(parts)


@pytest.mark.parametrize(("text", "kind"), [
    (w("", "", "host", "share", "x.md"), NETWORK),
    ("//host/share/x.md", NETWORK),
    ("/" + w("", "host", "share"), NETWORK),
    (BS + "/host/share", NETWORK),
    (" \t" + w("", "", "host", "share"), NETWORK),
    (w("", "", "host@SSL@443", "DavWWWRoot", "x.md"), NETWORK),
    (w("", "", "?", "UNC", "host", "share"), NETWORK),
    (w("", "", "?", "unc", "host", "share"), NETWORK),
    (w("", "", ".", "UNC", "host", "share"), NETWORK),
    ("//?/UNC/host/share", NETWORK),
    (w("", "??", "UNC", "host", "share"), NETWORK),
    (w("", "", "?", "C:", "x.md"), DEVICE),
    (w("", "", ".", "C:", "x.md"), DEVICE),
    (w("", "", "?", "GLOBALROOT", "Device", "Mup", "host", "share"), DEVICE),
    (w("", "", "?", "Volume{0a1b2c3d-0000-0000-0000-000000000000}", "x.md"), DEVICE),
    (w("", "", ".", "PhysicalDrive0"), DEVICE),
    (w("", "??", "C:", "x.md"), DEVICE),
    (w("C:", "Temp", "NUL"), DEVICE),
    ("C:/Temp/con.txt", DEVICE),
    ("C:NUL", DEVICE),
    (w("docs", "Aux.Tar.Gz"), DEVICE),
    (w("docs", "CONOUT$"), DEVICE),
    (w("docs", "COM\u00b2"), DEVICE),
    (w("docs", "lpt\u00b3.md"), DEVICE),
    (w("docs", "LPT0"), DEVICE),
    (w("docs", "prn . ."), DEVICE),
    (w("docs", "NUL:stream"), DEVICE),
    (w("docs", "..", "..", "nul"), DEVICE),
])
def test_windows_style_text_is_classified_on_every_platform(text, kind):
    assert classify(text) == kind


@pytest.mark.parametrize("text", [
    w("C:", "Users", "me", "notes.md"),
    "C:/Users/me/notes.md",
    "C:relative.md",
    w("", "rooted", "notes.md"),
    w("docs", "console.md"),
    w("docs", "nullable.txt"),
    w("docs", "COM10"),
    w("docs", "LPT"),
    w("docs", "auxiliary.md"),
    w("docs", ".con"),
    w("docs", "notes.md."),
    w("a", "..", "b.md"),
    "/home/me/notes.md",
    "notes/readme.md",
    "",
])
def test_local_text_is_not_classified(text):
    assert classify(text) is None


@pytest.mark.parametrize("text", ["CON", "nul.txt", "docs/../NUL", "./COM1.log", "a/b/../../PRN"])
def test_posix_style_device_names_follow_the_host(monkeypatch, text):
    monkeypatch.setattr(lp, "_WINDOWS", False)
    assert classify(text) is None, "an ordinary POSIX file name"
    assert classify(text, windows=True) == DEVICE, "portable artifacts apply Windows rules"
    monkeypatch.setattr(lp, "_WINDOWS", True)
    assert classify(text) == DEVICE


def test_a_leading_double_slash_is_refused_on_posix_too(monkeypatch):
    monkeypatch.setattr(lp, "_WINDOWS", False)
    assert classify("//host/share/x.md") == NETWORK


class FakeTree:
    """A Windows tree held in a dict: link path -> raw target, as os.readlink reports it."""

    def __init__(self, cwd, links=(), missing=(), unreadable=()):
        self.cwd, self.links = cwd, {k.lower(): v for k, v in dict(links).items()}
        self.missing = {m.lower() for m in missing}
        self.unreadable = {u.lower() for u in unreadable}
        self.seen = []

    def abspath(self, path):
        return ntpath.normpath(ntpath.join(self.cwd, path))

    def link_target(self, path):
        self.seen.append(path)
        key = path.lower()
        if key in self.missing:
            return MISSING
        if key in self.unreadable:
            raise LinkUnreadable(path)
        return self.links.get(key)

    @property
    def fs(self):
        return LinkFs(abspath=self.abspath, link_target=self.link_target)


def _walk_refuses(tree, path):
    with pytest.raises(NonLocalPath) as exc_info:
        check_links(path, label="target", fs=tree.fs)
    assert exc_info.value.kind == LINK
    return tree.seen


def test_a_symlink_to_a_share_is_refused_before_anything_opens_through_it():
    tree = FakeTree(w("C:", "work"), links={w("C:", "data", "share"): w("", "", "?", "UNC", "host", "share")})
    seen = _walk_refuses(tree, w("C:", "data", "share", "doc.md"))
    assert seen == [w("C:", "data"), w("C:", "data", "share")], "nothing under the link was examined"


@pytest.mark.parametrize("target", [
    w("", "", "host", "share"),
    w("", "??", "UNC", "host", "share"),
    w("", "", "?", "GLOBALROOT", "Device", "Mup", "host", "share"),
    w("", "", "?", "NUL"),
    "NUL",
    w("..", "CON"),
])
def test_link_targets_that_name_a_network_or_device_path_are_refused(target):
    tree = FakeTree(w("C:", "work"), links={w("C:", "work", "link.md"): target})
    _walk_refuses(tree, "link.md")


def test_a_relative_path_follows_a_chain_of_local_links():
    tree = FakeTree(w("C:", "work"), links={
        w("C:", "work", "junc"): w("", "", "?", "D:", "real"),       # a junction, as readlink reports it
        w("D:", "real", "rel"): w("..", "store"),                   # a relative symlink
        w("D:", "store", "bad.md"): w("", "", "?", "UNC", "host", "s"),
    })
    check_links(w("junc", "rel", "ok.md"), fs=tree.fs)
    assert tree.seen[-1] == w("D:", "store", "ok.md")
    _walk_refuses(FakeTree(tree.cwd, links=tree.links), w("junc", "rel", "bad.md"))


def test_a_volume_mount_point_is_local_and_the_walk_continues_inside_it():
    volume = w("", "", "?", "Volume{0a1b2c3d-0000-0000-0000-000000000000}", "")
    tree = FakeTree(w("C:", "work"), links={
        w("C:", "mnt"): volume,
        volume + "sub": w("", "", "host", "share"),
    })
    check_links(w("C:", "mnt", "ok.md"), fs=tree.fs)
    _walk_refuses(FakeTree(tree.cwd, links=tree.links), w("C:", "mnt", "sub", "x.md"))


def test_link_loops_and_unreadable_links_are_refused():
    loop = FakeTree(w("C:", "w"), links={w("C:", "w", "a"): w("C:", "w", "b"), w("C:", "w", "b"): w("C:", "w", "a")})
    _walk_refuses(loop, w("a", "x.md"))
    _walk_refuses(FakeTree(w("C:", "w"), unreadable=[w("C:", "w", "odd")]), w("odd", "x.md"))


def test_the_walk_stops_at_a_missing_component():
    tree = FakeTree(w("C:", "w"), missing=[w("C:", "w", "gone")])
    check_links(w("gone", "deeper", "x.md"), fs=tree.fs)
    assert tree.seen == [w("C:", "w"), w("C:", "w", "gone")]


def test_check_entry_refuses_a_walked_link_to_a_share(monkeypatch):
    tree = FakeTree(w("C:", "w"), links={w("C:", "w", "docs", "evil.md"): w("", "", "?", "UNC", "host", "s", "x")})
    monkeypatch.setattr(lp, "_WINDOWS", True)
    monkeypatch.setattr(lp, "REAL_FS", tree.fs)
    with pytest.raises(NonLocalPath) as exc_info:
        check_entry(w("C:", "w", "docs", "evil.md"), label="target")
    assert exc_info.value.kind == LINK
    check_entry(w("C:", "w", "docs", "fine.md"), label="target")
    with pytest.raises(NonLocalPath):
        check_entry(w("C:", "w", "docs", "aux.md"), label="target")


@pytest.mark.parametrize("cwd", [w("", "", "host", "share", "dir"), w("", "", "?", "UNC", "host", "share")])
def test_a_relative_path_under_a_network_working_folder_is_refused(monkeypatch, cwd):
    monkeypatch.setattr(lp, "_WINDOWS", True)
    monkeypatch.setattr(lp, "_getcwd", lambda: cwd)
    with pytest.raises(NonLocalPath) as exc_info:
        require_local("notes.md")
    assert exc_info.value.kind == NETWORK
    with pytest.raises(NonLocalPath):
        require_local(w("", "rooted.md"))  # root-relative resolves to the share's root


def test_a_long_path_working_folder_is_local(monkeypatch):
    cwd = w("", "", "?", "C:", "work")
    tree = FakeTree(cwd)  # its abspath keeps the prefix, as GetFullPathNameW does
    monkeypatch.setattr(lp, "_WINDOWS", True)
    monkeypatch.setattr(lp, "_getcwd", lambda: cwd)
    monkeypatch.setattr(lp, "REAL_FS", tree.fs)
    assert require_local("notes.md") == "notes.md"
    assert tree.seen == [w("C:", "work"), w("C:", "work", "notes.md")]


def test_a_missing_working_folder_leaves_the_error_to_the_open(monkeypatch):
    def gone():
        raise FileNotFoundError("the working folder was removed")

    tree = FakeTree(w("C:", "work"))
    monkeypatch.setattr(lp, "_WINDOWS", True)
    monkeypatch.setattr(lp, "_getcwd", gone)
    monkeypatch.setattr(lp, "REAL_FS", tree.fs)
    assert require_local("notes.md") == "notes.md"


def test_run_paths_refuse_file_targets_everywhere_and_a_store_off_the_operator():
    unc = w("", "", "host", "share")
    with pytest.raises(NonLocalPath) as exc_info:
        check_run_paths({"jobs": [{"source": "web", "target": "https://example.org"},
                                  {"source": "pdf", "target": unc}]}, operator=True)
    assert exc_info.value.argument == "jobs[1].target"
    check_run_paths({"jobs": [], "store": unc}, operator=True)  # the operator's own run keeps its store
    with pytest.raises(NonLocalPath) as exc_info:
        check_run_paths({"jobs": [], "store": unc}, operator=False)
    assert exc_info.value.argument == "store"


def test_the_operator_cli_config_keeps_a_network_store():
    from gather.run_config import plan_from_config

    unc = w("", "", "host", "share", "corpus")
    plan = plan_from_config({"jobs": [{"source": "docs", "target": "notes"}], "store": unc})
    assert plan.store is not None and plan.store._root == unc  # Corpus() only records the path


def test_the_refusal_payload_is_structured_and_names_the_argument():
    from gather.mcp import handle_request

    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "gather.docs", "arguments": {"path": "//host/share/x.md"}}}
    result = handle_request(req)["result"]
    body = result["structuredContent"]
    assert body == {"code": "NON_LOCAL_PATH", "retryable": False, "kind": NETWORK, "argument": "path",
                    "detail": lp._DETAIL[NETWORK]}
    assert json.loads(result["content"][0]["text"]) == body


def _manifest(root="fixtures", target="fixtures/a.md"):
    return {
        "schema": "gather.pilot-manifest/1", "pilot_id": "p", "title": "t", "mode": "offline",
        "deployment": {"mode": "workstation", "custodian": "customer"},
        "policy": {"allowed_hosts": [], "trusted_browser_hosts": [], "allowed_local_roots": [root],
                   "enabled_adapters": ["docs"], "credentials": [], "report_private_content": False},
        "missions": [{"id": "m", "title": "m", "sources": [{
            "id": "s", "adapter": "docs", "target": target, "fixture": None, "refresh_fixture": None,
            "visibility": "private", "monitor": False, "required": True, "extraction": None, "options": {}}]}],
    }


def test_a_plain_pilot_manifest_still_validates(tmp_path):
    from gather.pilot_manifest import validate_pilot_manifest

    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "a.md").write_text("a note", encoding="utf-8")
    manifest = validate_pilot_manifest(_manifest(), tmp_path)
    assert manifest.missions[0].sources[0].target == "fixtures/a.md"


@pytest.mark.parametrize(("field", "value"), [
    ("target", "fixtures/aux.md"),
    ("target", w("fixtures", "NUL")),
    ("target", "//host/share/x.md"),
    ("root", "CON"),
])
def test_pilot_manifest_paths_apply_windows_rules_on_every_platform(tmp_path, field, value):
    from gather.pilot_manifest import validate_pilot_manifest

    (tmp_path / "fixtures").mkdir()
    manifest = _manifest(root=value) if field == "root" else _manifest(target=value)
    with pytest.raises(NonLocalPath):
        validate_pilot_manifest(manifest, tmp_path)


# --- real links (Windows only: only a Windows link can reach a share by its target text) --------

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows links and junctions")


@windows_only
def test_docs_reads_through_a_local_junction(tmp_path):
    import _winapi

    from gather.docs import DocsSource

    real = tmp_path / "real"
    real.mkdir()
    (real / "note.md").write_text("through a junction\n", encoding="utf-8")
    _winapi.CreateJunction(str(real), str(tmp_path / "junc"))
    texts = sorted(i.text for i in DocsSource().fetch(str(tmp_path / "junc")))
    assert texts == ["through a junction\n"]
    assert len(DocsSource().fetch(str(tmp_path))) == 2  # the walk descends the junction too


@windows_only
def test_docs_refuses_a_real_symlink_to_a_device(tmp_path):
    from gather.docs import DocsSource

    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "fine.md").write_text("fine\n", encoding="utf-8")
    try:
        os.symlink(w("", "", ".", "NUL"), str(folder / "link.md"))
    except OSError as exc:  # creating a symlink needs Developer Mode or the symlink privilege
        pytest.skip(f"symlink creation is not permitted here: {exc}")
    for target in (folder, folder / "link.md"):
        with pytest.raises(NonLocalPath) as exc_info:
            DocsSource().fetch(str(target))
        assert exc_info.value.kind == LINK
