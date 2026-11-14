"""``gather decompose`` and ``gather rebuild``: every handler round-trips byte for byte, a planted
fault is reported, the tree is the same on a second run, and archive limits hold."""

import hashlib
import io
import json
import os
import struct
import zipfile
import zlib

import pytest
from saves_fixture import ANA_MD, PAGE_JSON

from gather.cli import main
from gather.decompose_rebuild import rebuild
from gather.decompose_run import decompose_file
from gather.decompose_tree import Limits


def sha(data):
    return hashlib.sha256(data).hexdigest()


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def real_png(width=3, height=2):
    rows = b"".join(b"\0" + bytes([40 * y, 80, 200] * width) for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + png_chunk(b"tEXt", b"Comment\0" + b"made for a test, long enough to be a blob")
            + png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b""))


def zip_bytes(extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("notes/a.txt"), "first line\nsecond line\n" * 20, zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo("img/p.png"), real_png(), zipfile.ZIP_STORED)
        z.writestr(zipfile.ZipInfo("../evil.txt"), "an entry name that climbs out of the folder " * 3, zipfile.ZIP_DEFLATED)
        for name, data in (extra or {}).items():
            z.writestr(zipfile.ZipInfo(name), data, zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def odd_wav():
    """A WAV whose data chunk ends 3 bytes short of a frame, with pad bytes, a LIST chunk and trailing bytes."""
    fmt = struct.pack("<HHIIHH", 1, 2, 8000, 32000, 4, 16)
    data = (bytes(range(256)) * 2)[:403]
    body = (b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", 403) + data + b"\0"
            + b"LIST" + struct.pack("<I", 5) + b"INFOx" + b"\0")
    return b"RIFF" + struct.pack("<I", len(body)) + body + b"junk"


SAMPLES = {
    "raw": ("raw/1", bytes(range(256)) * 3 + b"\0tail"),
    "png": ("png/1", real_png() + b"bytes after IEND that no chunk claims, kept as raw"),
    "wav": ("wav/1", odd_wav()),
    "zip": ("zip/1", zip_bytes({"inner.zip": zip_bytes()})),
    "json": ("json/1", b'\xef\xbb\xbf{\r\n  "name": "a value long enough to be stored as a blob, not inline",\t"n": [1, -2.5e3, true, null]\r\n}\n'),
    "text": ("text/1", "first line, long enough to go to a blob rather than inline\r\nsecond\nthird\rno final newline é".encode()),
    "sidecar": ("cmmns-sidecar/1", ANA_MD.encode("utf-8")),
}


def write_sample(tmp_path, name):
    path = tmp_path / f"sample-{name}.bin"  # the extension never names the handler
    path.write_bytes(SAMPLES[name][1])
    return path


def nodes(node):
    yield node
    for child in node.get("children", []):
        yield from nodes(child)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_decompose_then_rebuild_gives_the_same_bytes(tmp_path, name):
    handler, data = SAMPLES[name]
    doc = decompose_file(str(write_sample(tmp_path, name)), str(tmp_path / "tree"))
    assert (doc["handler"], doc["rebuild"], doc["source"]["sha256"], doc["source"]["bytes"]) == (
        handler, "exact", sha(data), len(data))
    report = rebuild(str(tmp_path / "tree"), str(tmp_path / "rebuilt.bin"))
    assert report == {"ok": True, "bytes": len(data), "sha256": sha(data), "expected_sha256": sha(data), "problems": []}
    assert (tmp_path / "rebuilt.bin").read_bytes() == data
    assert sorted(os.listdir(tmp_path / "tree")) == ["parts", "tree.json"]
    assert all(n["produced_by"] == handler for n in nodes(doc["root"]))


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_one_flipped_byte_in_the_tree_is_reported_and_changes_the_rebuild(tmp_path, name):
    data = SAMPLES[name][1]
    decompose_file(str(write_sample(tmp_path, name)), str(tmp_path / "tree"))
    blob = sorted((tmp_path / "tree" / "parts").iterdir())[0]
    damaged = bytearray(blob.read_bytes())
    damaged[0] ^= 0x01
    blob.write_bytes(bytes(damaged))
    report = rebuild(str(tmp_path / "tree"), str(tmp_path / "rebuilt.bin"))
    assert report["ok"] is False and report["sha256"] != sha(data) and report["expected_sha256"] == sha(data)
    assert sha((tmp_path / "rebuilt.bin").read_bytes()) == report["sha256"]
    flagged = [p for p in report["problems"] if p["problem"] == "sha256 differs"]
    assert flagged and flagged[0]["node"].startswith("root")
    assert report["problems"][-1] == {"node": "root", "kind": "file", "problem": "rebuilt bytes differ from the original sha256"}
    assert rebuild(str(tmp_path / "tree"), None)["ok"] is False  # verify alone reports it too


def test_a_fault_in_an_inline_leaf_or_a_missing_blob_is_reported(tmp_path):
    decompose_file(str(write_sample(tmp_path, "png")), str(tmp_path / "tree"))
    tree = tmp_path / "tree" / "tree.json"
    doc = json.loads(tree.read_text(encoding="utf-8"))
    signature = doc["root"]["children"][0]
    signature["hex"] = "88" + signature["hex"][2:]
    tree.write_text(json.dumps(doc), encoding="utf-8")
    problems = rebuild(str(tmp_path / "tree"), None)["problems"]
    assert {"node": "root/0", "kind": "png-signature", "problem": "sha256 differs"} in problems
    sorted((tmp_path / "tree" / "parts").iterdir())[0].unlink()
    assert "blob is missing" in {p["problem"] for p in rebuild(str(tmp_path / "tree"), None)["problems"]}


def test_same_file_gives_the_same_tree_and_parts_on_a_second_run(tmp_path):
    for name in sorted(SAMPLES):
        path = write_sample(tmp_path, name)
        listings = []
        for run in ("a", "b"):
            out = tmp_path / f"{name}-{run}"
            decompose_file(str(path), str(out))
            listings.append({p.name: sha(p.read_bytes()) for p in [out / "tree.json", *sorted((out / "parts").iterdir())]})
        assert listings[0] == listings[1] and len(listings[0]) >= 2, name
        assert all(blob == digest for blob, digest in listings[0].items() if blob != "tree.json")


def test_handler_comes_from_the_bytes_and_structure_is_recorded(tmp_path):
    (tmp_path / "picture.txt").write_bytes(SAMPLES["png"][1])
    png = decompose_file(str(tmp_path / "picture.txt"), str(tmp_path / "png"))
    chunks = [n for n in png["root"]["children"] if n["kind"] == "png-chunk"]
    assert [c["params"]["type"] for c in chunks] == ["IHDR", "tEXt", "IDAT", "IEND"]
    assert chunks[0]["params"] == {"type": "IHDR", "crc_ok": True, "width": 3, "height": 2, "bit_depth": 8,
                                   "colour_type": 2, "interlace": 0}
    assert [f["kind"] for f in chunks[0]["children"]] == ["length", "type", "data", "crc"]
    assert png["unparsed"] == [{"offset": len(real_png()), "length": 50}]
    wav = decompose_file(str(write_sample(tmp_path, "wav")), str(tmp_path / "wav"))
    frames = next(n for n in nodes(wav["root"]) if n["kind"] == "pcm-frames")
    assert frames["params"] == {"unit": "sample frame", "unit_size": 4, "unit_count": 100, "channels": 2, "bits_per_sample": 16}
    assert [n["kind"] for n in nodes(wav["root"]) if n["kind"] in ("pad", "raw")] == ["raw", "pad", "pad", "raw"]
    (tmp_path / "words.png").write_bytes(SAMPLES["text"][1])
    text = decompose_file(str(tmp_path / "words.png"), str(tmp_path / "text"))
    assert [n["params"]["ending"] for n in text["root"]["children"]] == ["crlf", "lf", "cr", "none"]
    tokens = decompose_file(str(write_sample(tmp_path, "json")), str(tmp_path / "json"))["root"]
    assert (tokens["params"], tokens["children"][0]["kind"]) == ({"tokens": 26, "valid": True}, "byte-order-mark")
    assert {n["kind"] for n in tokens["children"]} == {
        "byte-order-mark", "json-whitespace", "json-punctuation", "json-string", "json-number", "json-literal"}
    assert max(n["params"]["depth"] for n in tokens["children"][1:]) == 2


def test_sidecar_pair_keeps_front_matter_lines_body_blocks_and_the_json_companion(tmp_path):
    (tmp_path / "save.md").write_bytes(ANA_MD.encode("utf-8"))
    companion = json.dumps(PAGE_JSON, ensure_ascii=False, indent=2).encode("utf-8")
    (tmp_path / "save.json").write_bytes(companion)
    doc = decompose_file(str(tmp_path / "save.md"), str(tmp_path / "tree"))
    front, body = doc["root"]["children"]
    keys = [n["params"]["key"] for n in front["children"] if n["kind"] == "front-matter-line"]
    assert keys[:4] == ["format", "files", "kind", "site"] and front["params"] == {"lines": 13}
    assert all(n["params"]["value_is_json"] for n in front["children"] if n["kind"] == "front-matter-line")
    assert [b["kind"] for b in body["children"]][:5] == [
        "block-blank", "block-heading", "block-blank", "block-quote", "block-blank"]
    assert [(c["name"], c["handler"], c["sha256"]) for c in doc["companions"]] == [("save.json", "json/1", sha(companion))]
    report = rebuild(str(tmp_path / "tree"), str(tmp_path / "back.json"), companion="save.json")
    assert report["ok"] and (tmp_path / "back.json").read_bytes() == companion
    with pytest.raises(ValueError, match="no companion"):
        rebuild(str(tmp_path / "tree"), None, companion="other.json")


def test_zip_entries_nest_and_an_entry_name_never_becomes_a_path(tmp_path):
    doc = decompose_file(str(write_sample(tmp_path, "zip")), str(tmp_path / "out" / "tree"))
    entries = [n for n in doc["root"]["children"] if n["kind"] == "zip-entry"]
    assert [e["params"]["name"] for e in entries] == ["notes/a.txt", "img/p.png", "../evil.txt", "inner.zip"]
    assert [(e["derived"]["method"], e["derived"]["status"], e["derived"]["handler"]) for e in entries] == [
        ("deflate", "ok", "text/1"), ("stored", "ok", "png/1"), ("deflate", "ok", "text/1"), ("deflate", "ok", "zip/1")]
    inner = [n for n in entries[3]["derived"]["root"]["children"] if n["kind"] == "zip-entry"]
    assert inner[1]["derived"]["root"]["children"][1]["params"]["width"] == 3  # a PNG, two archives down
    assert entries[1]["derived"]["sha256"] == sha(real_png())
    assert [n["kind"] for n in doc["root"]["children"][-2:]] == ["zip-central-directory", "zip-end-record"]
    assert doc["unparsed"] == []
    assert sorted(os.listdir(tmp_path)) == ["out", "sample-zip.bin"] and os.listdir(tmp_path / "out") == ["tree"]
    assert not any("evil" in name for _, _, names in os.walk(tmp_path / "out") for name in names)


def test_zip_expansion_stops_at_the_recorded_limits_and_still_round_trips(tmp_path):
    bomb = zip_bytes({"zeros.bin": b"\0" * 200000, "deep.zip": zip_bytes({"deeper.zip": zip_bytes()})})
    (tmp_path / "bomb.zip").write_bytes(bomb)

    def statuses(root):
        return {n["params"]["name"]: n["derived"]["status"] for n in root["children"] if n["kind"] == "zip-entry"}

    tight = decompose_file(str(tmp_path / "bomb.zip"), str(tmp_path / "tight"), Limits(max_entry_bytes=5000, max_total_bytes=500))
    assert statuses(tight["root"]) == {
        "notes/a.txt": "ok", "img/p.png": "not expanded (total expansion limit reached)",
        "../evil.txt": "not expanded (total expansion limit reached)",
        "zeros.bin": "not expanded (larger than the per-entry limit)",
        "deep.zip": "not expanded (total expansion limit reached)"}
    assert (tight["limits"]["max_entry_bytes"], tight["limits"]["max_total_bytes"]) == (5000, 500)
    shallow = decompose_file(str(tmp_path / "bomb.zip"), str(tmp_path / "shallow"), Limits(max_depth=1))
    top = statuses(shallow["root"])
    assert top["zeros.bin"] == "ok" and top["deep.zip"] == "ok" and shallow["limits"]["max_depth"] == 1
    deep = next(n for n in shallow["root"]["children"] if n["params"].get("name") == "deep.zip")["derived"]["root"]
    assert set(statuses(deep).values()) == {"not expanded (nesting depth limit)"} and len(statuses(deep)) == 4
    for tree in ("tight", "shallow"):
        assert rebuild(str(tmp_path / tree), str(tmp_path / f"{tree}.zip"))["ok"]
        assert (tmp_path / f"{tree}.zip").read_bytes() == bomb


def test_a_damaged_container_falls_back_to_raw_and_says_which_handler_declined(tmp_path):
    (tmp_path / "cut.zip").write_bytes(SAMPLES["zip"][1][:-30])
    doc = decompose_file(str(tmp_path / "cut.zip"), str(tmp_path / "tree"))
    assert (doc["handler"], doc["declined"]) == ("raw/1", [{"handler": "zip/1", "reason": "no end-of-central-directory record"}])
    assert doc["unparsed"] == [{"offset": 0, "length": len(SAMPLES["zip"][1]) - 30}]
    assert os.listdir(tmp_path / "tree" / "parts") == [doc["source"]["sha256"]]  # no blob from the failed attempt
    assert rebuild(str(tmp_path / "tree"), None)["ok"]
    (tmp_path / "empty").write_bytes(b"")
    empty = decompose_file(str(tmp_path / "empty"), str(tmp_path / "empty-tree"))
    assert (empty["handler"], empty["root"]["hex"], rebuild(str(tmp_path / "empty-tree"), None)["ok"]) == ("raw/1", "", True)


def test_a_hostile_tree_cannot_name_a_file_outside_parts(tmp_path):
    decompose_file(str(write_sample(tmp_path, "raw")), str(tmp_path / "tree"))
    (tmp_path / "secret").write_bytes(b"outside the tree")
    tree = tmp_path / "tree" / "tree.json"
    doc = json.loads(tree.read_text(encoding="utf-8"))
    doc["root"]["blob"] = "../../secret"
    tree.write_text(json.dumps(doc), encoding="utf-8")
    report = rebuild(str(tmp_path / "tree"), str(tmp_path / "out.bin"))
    assert report["bytes"] == 0 and (tmp_path / "out.bin").read_bytes() == b""
    assert report["problems"][0] == {"node": "root", "kind": "raw", "problem": "leaf has no bytes"}
    tree.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a gather.decompose-tree/1 record"):
        rebuild(str(tmp_path / "tree"), None)


def test_cli_decompose_and_rebuild_exit_codes(tmp_path, capsys):
    path = write_sample(tmp_path, "wav")
    assert main(["decompose", str(path), "--out", str(tmp_path / "tree"), "--json"]) == 0
    facts = json.loads(capsys.readouterr().out)
    assert (facts["handler"], facts["rebuild"], facts["unparsed_bytes"]) == ("wav/1", "exact", 7)
    assert main(["decompose", str(path), "--out", str(tmp_path / "tree")]) == 2  # the folder already holds a tree
    assert main(["decompose", str(tmp_path / "missing"), "--out", str(tmp_path / "t2")]) == 2
    assert main(["rebuild", str(tmp_path / "tree"), "--out", str(tmp_path / "back.wav"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert (tmp_path / "back.wav").read_bytes() == SAMPLES["wav"][1]
    assert main(["rebuild", str(tmp_path / "tree"), "--verify"]) == 0
    assert main(["rebuild", str(tmp_path / "tree")]) == 2
    assert main(["rebuild", str(tmp_path / "nowhere"), "--verify"]) == 2
    blob = sorted((tmp_path / "tree" / "parts").iterdir())[0]
    blob.write_bytes(b"X" + blob.read_bytes()[1:])
    capsys.readouterr()
    assert main(["rebuild", str(tmp_path / "tree"), "--verify"]) == 1
    assert "sha256 differs" in capsys.readouterr().err
