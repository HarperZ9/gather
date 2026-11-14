"""``gather saves``: exact cells from a fixture tree, byte-identical output across runs and folders,
the out folder skipped on a second run, and the CLI's exit codes."""

import csv
import hashlib
import json
import os

from saves_fixture import ANA, ANA_TEXT, NOTE_TEXT, PAGE_TEXT, make_tree

from gather.cli import main
from gather.saves_tables import (
    ENTITY_COLUMNS,
    ITEM_COLUMNS,
    MEDIA_COLUMNS,
    build_tables,
)

OUTPUTS = ("entities.csv", "entities.jsonl", "items.csv", "items.jsonl", "manifest.json", "media.csv", "media.jsonl")


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hashes(out):
    assert sorted(os.listdir(out)) == list(OUTPUTS)
    return {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in OUTPUTS}


def rows(out, name):
    with open(out / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def built(tmp_path, **kwargs):
    root = make_tree(tmp_path / "saves")
    manifest = build_tables(str(root), str(tmp_path / "out"), **kwargs)
    return manifest, tmp_path / "out"


def test_items_table_has_the_exact_cells_for_each_kind_of_save(tmp_path):
    manifest, out = built(tmp_path)
    items = rows(out, "items.csv")
    assert tuple(items[0]) == ITEM_COLUMNS
    assert [r["sidecar_path"] for r in items] == [
        "web/page.md", "x/note.md", "x/again.md", f"x/{ANA}.md", "youtube/ref.md"]  # by site, id, path
    page, note, again, ana, ref = items
    assert ana["id"] == again["id"] == "x:2121395628576284802"  # two saves of one post stay two rows
    assert (ana["adapter"], ana["kind"], ana["author"], ana["handle"]) == ("legacy:x", "media", "Ana Example", "ana")
    assert (ana["posted_time"], ana["saved_time"]) == ("2026-11-14T00:11:46.000Z", "2026-11-14T00:44:34.189Z")
    assert (ana["text_length"], ana["content_hash"]) == (str(len(ANA_TEXT)), sha_text(ANA_TEXT))
    assert (ana["links"], ana["link_list"]) == ("1", "https://t.co/SO2V0fz6h0")  # the parent's link is not the item's
    assert (ana["media_count"], ana["media_kinds"], ana["media_file"], ana["missing_files"]) == ("1", "image", "saved", "0")
    assert (ana["file_paths"], ana["thread_path"], ana["language"]) == (f"x/{ANA}.jpg", f"x/{ANA}.thread.json", "en")
    assert ana["sidecar_sha256"] == hashlib.sha256((tmp_path / "saves" / "x" / f"{ANA}.md").read_bytes()).hexdigest()
    assert (note["id"], note["kind"], note["media_file"], note["media_count"]) == ("x:2121265316563124432", "text", "", "0")
    assert note["content_hash"] == sha_text(NOTE_TEXT)  # BOM, CRLF and trailing spaces do not change the hash
    assert (ref["id"], ref["adapter"], ref["text_length"]) == ("youtube:dQw4w9WgXcQ", "legacy:youtube", "0")
    assert (ref["media_file"], ref["missing_files"], ref["file_paths"]) == ("not saved (no media file listed)", "1", "")
    assert manifest["input_items"] == 5


def test_json_sidecar_values_win_over_the_front_matter(tmp_path):
    _, out = built(tmp_path)
    page = rows(out, "items.csv")[0]
    digest = hashlib.sha256(b"https://example.org/informe").hexdigest()[:16]
    assert (page["id"], page["adapter"], page["site"]) == (f"example.org:h-{digest}", "generic", "example.org")
    assert (page["title"], page["author"], page["handle"]) == ("Informe económico 2026", "Cy Example", "cy")
    assert (page["page_url"], page["post_url"], page["json_path"]) == ("https://example.org/informe", "", "web/page.json")
    assert (page["text_length"], page["language"]) == (str(len(PAGE_TEXT)), "es")  # the sidecar's es-MX, primary tag
    assert page["link_list"] == "https://doi.org/10.5555/Abc.1 https://example.org/more"  # text first, then the list
    assert (page["media_kinds"], page["media_file"], page["file_paths"]) == ("image", "saved", "web/page.png")
    with open(out / "items.jsonl", encoding="utf-8") as f:
        first = json.loads(f.readline())
    assert tuple(first) == ITEM_COLUMNS and first["text_length"] == len(PAGE_TEXT) and first["links"] == 2


def test_manifest_counts_skipped_markdown_and_records_problems(tmp_path):
    manifest, out = built(tmp_path)
    assert manifest == json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["format"], manifest["skipped_markdown"]) == ("gather.saves-tables/1", 2)
    assert manifest["problems"] == [
        {"path": "web/broken.md", "problem": "sidecar front matter is not closed or names another format"},
        {"path": "youtube/ref.md", "problem": "front matter key engagement: value is not JSON"}]
    assert set(manifest["tables"]) == set(OUTPUTS) - {"manifest.json"}
    assert manifest["tables"]["items.csv"] == {"rows": 5, "sha256": hashes(out)["items.csv"]}
    assert str(tmp_path) not in (out / "manifest.json").read_text(encoding="utf-8")


def test_media_and_entity_tables_follow_their_columns_and_order(tmp_path):
    _, out = built(tmp_path)
    media = rows(out, "media.csv")
    assert tuple(media[0]) == MEDIA_COLUMNS
    assert [(r["path"], r["item_id"], r["listed"], r["container"], r["width"], r["height"]) for r in media] == [
        ("web/loose.gif", "", "false", "gif", "9", "8"),
        ("web/page.png", rows(out, "items.csv")[0]["id"], "true", "png", "7", "5"),
        (f"x/{ANA}.jpg", "x:2121395628576284802", "true", "jpeg", "4", "3")]
    assert media[2]["sha256"] == hashlib.sha256((tmp_path / "saves" / "x" / f"{ANA}.jpg").read_bytes()).hexdigest()
    entities = rows(out, "entities.csv")
    assert tuple(entities[0]) == ENTITY_COLUMNS
    assert entities == sorted(entities, key=lambda r: (r["item_id"], r["sidecar_path"], r["type"], r["value"]))
    note = {(r["type"], r["normalized"]) for r in entities if r["sidecar_path"] == "x/note.md"}
    assert note == {("arxiv", "2301.12345"), ("date", "2024-03-05"), ("quantity", "1200 $"), ("hashtag", "#money")}
    assert not any(r["normalized"] == "#notmine" for r in entities)  # a quoted parent's text is not the item's


def test_csv_is_utf8_without_bom_and_with_lf_line_endings(tmp_path):
    _, out = built(tmp_path)
    for name in OUTPUTS:
        data = (out / name).read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data and data.endswith(b"\n")
    assert "Informe económico 2026".encode("utf-8") in (out / "items.csv").read_bytes()
    assert '"title": "Informe económico 2026"' in (out / "items.jsonl").read_text(encoding="utf-8")


def test_same_tree_gives_byte_identical_tables_across_runs_and_folders(tmp_path):
    root = make_tree(tmp_path / "first" / "saves")
    build_tables(str(root), str(tmp_path / "out1"))
    build_tables(str(root), str(tmp_path / "out2"))
    moved = make_tree(tmp_path / "second" / "deeper" / "other-name")  # another absolute path, new file times
    for folder, _, names in os.walk(moved):
        for name in names:
            os.utime(os.path.join(folder, name), (1_000_000_000, 1_000_000_000))
    build_tables(str(moved), str(tmp_path / "out3"))
    first = hashes(tmp_path / "out1")
    assert first == hashes(tmp_path / "out2") == hashes(tmp_path / "out3")
    assert len(set(first.values())) == len(OUTPUTS)  # seven different files, not seven empty ones


def test_no_media_hash_leaves_only_the_media_sha256_empty(tmp_path):
    _, out = built(tmp_path, media_hash=False)
    assert [r["sha256"] for r in rows(out, "media.csv")] == ["", "", ""]
    assert all(len(r["sidecar_sha256"]) == 64 for r in rows(out, "items.csv"))
    with open(out / "media.jsonl", encoding="utf-8") as f:
        assert json.loads(f.readline())["sha256"] is None


def test_listed_file_outside_the_folder_is_a_problem_not_a_read(tmp_path):
    root = tmp_path / "saves"
    (root / "x").mkdir(parents=True)
    (tmp_path / "secret.png").write_bytes(b"not for the tables")
    (root / "x" / "a.md").write_text('---\nformat: "daylight.sidecar/1"\nfiles: ["../../secret.png"]\nkind: "media"\n---\n',
                                     encoding="utf-8")
    manifest = build_tables(str(root), str(tmp_path / "out"))
    assert manifest["problems"] == [{"path": "x/a.md", "problem": "listed file name points outside the folder"}]
    assert manifest["tables"]["media.csv"]["rows"] == 0
    assert rows(tmp_path / "out", "items.csv")[0]["missing_files"] == "1"


def test_cli_writes_tables_and_skips_its_own_out_folder_on_the_next_run(tmp_path, capsys):
    root = make_tree(tmp_path / "saves")
    out = root / "tables"
    assert main(["saves", str(root), "--out", str(out)]) == 0
    assert "5 items" in capsys.readouterr().out
    first = hashes(out)
    assert main(["saves", str(root), "--out", str(out), "--json"]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert first == hashes(out)
    assert manifest["input_items"] == 5 and manifest["tables"]["media.csv"]["rows"] == 3


def test_cli_refuses_bad_options_with_exit_code_2(tmp_path, capsys):
    root = make_tree(tmp_path / "saves")
    assert main(["saves", str(root)]) == 2
    assert main(["saves", str(root), "--out", str(root)]) == 2
    assert main(["saves", str(tmp_path / "missing"), "--out", str(tmp_path / "out")]) == 2
    assert main(["saves", "--probe", str(tmp_path / "missing.png")]) == 2
    assert capsys.readouterr().err.count("saves:") == 4
    assert not (tmp_path / "out").exists() and sorted(os.listdir(root)) == ["notes", "web", "x", "youtube"]


def test_cli_probe_prints_one_media_row_as_json(tmp_path, capsys):
    root = make_tree(tmp_path / "saves")
    assert main(["saves", "--probe", str(root / "web" / "page.png")]) == 0
    row = json.loads(capsys.readouterr().out)
    assert tuple(row) == MEDIA_COLUMNS
    assert (row["container"], row["kind"], row["width"], row["height"], row["listed"]) == ("png", "image", 7, 5, False)
    assert row["sha256"] == hashlib.sha256((root / "web" / "page.png").read_bytes()).hexdigest()
    assert main(["saves", "--probe", str(root / "web" / "page.png"), "--no-media-hash"]) == 0
    assert json.loads(capsys.readouterr().out)["sha256"] is None
