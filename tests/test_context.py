import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gather.cli import main
from gather.item import content_hash, make_item
from gather.mcp import handle_request
from gather.store import Corpus


def _item(kind, ident, title, text, source="docs", method="file-read"):
    return make_item(
        kind=kind,
        id=ident,
        title=title,
        text=text,
        source=source,
        ref=ident,
        method=method,
        fetched_at=1.0,
    )


def _corpus(tmp_path):
    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([
        _item(
            "document",
            "alpha-note",
            "Alpha note",
            "0123456789DECISION-FACT-ALPHAzz. Extra text that should stay out by default.",
        ),
        _item(
            "comment",
            "comment-1",
            "Comment on launch",
            "Viewer says the demo was confusing, which is acquisition context only.",
            source="video",
            method="yt-dlp",
        ),
    ])
    return c


def _mcp_call(name, arguments=None):
    return handle_request({
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })


def _view_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _rewrite_catalog(c: Corpus, rows: list[dict]) -> None:
    with open(c._catalog, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _patch_os_open_with_dir_fd_support(monkeypatch, ctx, replacement):
    # POSIX production code must fail closed when os.open lacks openat support.
    # These tests wrap os.open to trigger races, so the wrapper has to preserve
    # that advertised capability for the production guard to admit the path.
    supports_dir_fd = set(ctx.os.supports_dir_fd)
    supports_dir_fd.add(replacement)
    monkeypatch.setattr(ctx.os, "open", replacement)
    monkeypatch.setattr(ctx.os, "supports_dir_fd", supports_dir_fd)


def _posix_descriptor_for_corpus(ctx, c: Corpus):
    from gather.context import CorpusRootDescriptor, CorpusRootIdentity

    flags = (
        os.O_RDONLY
        | ctx._required_os_flag("O_DIRECTORY")
        | ctx._required_os_flag("O_NOFOLLOW")
        | getattr(os, "O_CLOEXEC", 0)
    )
    fd = os.open(c._root, flags)
    st = os.fstat(fd)
    return fd, CorpusRootDescriptor(
        expected_identity=CorpusRootIdentity(platform="posix", device=st.st_dev, inode=st.st_ino),
        fd=fd,
    )


def _windows_descriptor_for_corpus(ctx, c: Corpus):
    from gather.context import CorpusRootDescriptor

    handle = ctx._windows_createfile_root(Path(c._root))
    return handle, CorpusRootDescriptor(
        expected_identity=ctx._windows_handle_identity(handle),
        handle=handle,
    )


def _descriptor_for_corpus(ctx, c: Corpus):
    if os.name == "nt":
        return _windows_descriptor_for_corpus(ctx, c)
    return _posix_descriptor_for_corpus(ctx, c)


def test_inspect_corpus_returns_bounded_verified_excerpts_and_row_refs(tmp_path):
    # Catches: returning catalog hashes only, whole bodies by default, or unverified body status.
    from gather.context import inspect_corpus

    c = _corpus(tmp_path)
    body = inspect_corpus(c, max_rows=1, excerpt_chars=12)

    assert body["schema"] == "gather.readable-corpus/v1"
    assert body["corpus_digest"] == c.digest().seal
    assert body["row_count"] == 2
    assert body["returned_rows"] == 1
    assert body["omissions"] == [{"reason": "row_limit", "omitted_rows": 1}]
    row = body["rows"][0]
    assert row["row_ref"].startswith("row_")
    assert row["kind"] == "document"
    assert row["body_status"] == "MATCH"
    assert row["availability"] == "UNWITNESSED"
    assert row["excerpt"] == "0123456789DE"
    assert row["excerpt_range"] == {"start": 0, "end": 12}
    assert row["text_chars"] == 76
    assert {o["reason"] for o in row["omissions"]} == {"excerpt_truncated"}


def test_select_context_binds_exact_text_range_and_source_identity(tmp_path):
    # Catches: selection digest omitting selected text, ranges, source refs, or full body hash.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    row_ref = inspect_corpus(c)["rows"][0]["row_ref"]
    digest = c.digest().seal

    payload = select_context(
        c,
        [{"row_ref": row_ref, "start": 10, "limit": 19}],
        expected_corpus_digest=digest,
    )

    assert payload["schema"] == "gather.readable-context/v1"
    assert payload["corpus_digest"] == digest
    assert payload["selection_count"] == 1
    selected = payload["selections"][0]
    assert selected["row_ref"] == row_ref
    assert selected["source"] == "docs"
    assert selected["ref"] == "alpha-note"
    assert selected["method"] == "file-read"
    assert selected["sha256"] == content_hash(
        "0123456789DECISION-FACT-ALPHAzz. Extra text that should stay out by default."
    )
    assert selected["range"] == {"start": 10, "end": 29}
    assert selected["text"] == "DECISION-FACT-ALPHA"
    assert selected["omissions"] == []
    assert len(payload["selection_digest"]) == 64
    assert "truth of selected source claims" in payload["does_not_prove"]
    assert "claim_supported" not in payload
    assert "semantic_verdict" not in payload


def test_select_context_rejects_stale_expected_corpus_digest(tmp_path):
    # Catches: accepting a selection against a stale catalog view.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    row_ref = inspect_corpus(c)["rows"][0]["row_ref"]

    with pytest.raises(ValueError, match="expected corpus digest"):
        select_context(
            c,
            [{"row_ref": row_ref, "start": 10, "limit": 19}],
            expected_corpus_digest="a" * 64,
        )


def test_missing_or_corrupt_bodies_are_visible_and_cannot_be_selected(tmp_path):
    # Catches: silently handing downstream agents missing or tampered context.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    rows = list(c.rows())
    os.remove(c._object_path(rows[0]["sha256"]))
    with open(c._object_path(rows[1]["sha256"]), "w", encoding="utf-8") as f:
        f.write("tampered comment")

    inspected = inspect_corpus(c)
    by_id = {row["id"]: row for row in inspected["rows"]}
    assert by_id["alpha-note"]["body_status"] == "MISSING"
    assert by_id["alpha-note"]["excerpt"] == ""
    assert {o["reason"] for o in by_id["alpha-note"]["omissions"]} == {"body_missing"}
    assert by_id["comment-1"]["body_status"] == "CORRUPT"
    assert by_id["comment-1"]["excerpt"] == ""
    assert {o["reason"] for o in by_id["comment-1"]["omissions"]} == {"body_corrupt"}

    with pytest.raises(ValueError, match="cannot select row"):
        select_context(
            c,
            [{"row_ref": by_id["alpha-note"]["row_ref"], "start": 0, "limit": 10}],
            expected_corpus_digest=c.digest().seal,
        )


def test_select_context_enforces_row_and_total_text_budgets(tmp_path):
    # Catches: accidental whole-corpus export or unbounded private text release.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    rows = inspect_corpus(c)["rows"]
    with pytest.raises(ValueError, match="at most 1 row"):
        select_context(
            c,
            [{"row_ref": rows[0]["row_ref"]}, {"row_ref": rows[1]["row_ref"]}],
            expected_corpus_digest=c.digest().seal,
            max_rows=1,
        )

    with pytest.raises(ValueError, match="max_total_chars"):
        select_context(
            c,
            [{"row_ref": rows[0]["row_ref"], "start": 10, "limit": 19}],
            expected_corpus_digest=c.digest().seal,
            max_total_chars=10,
        )


def test_selected_body_is_rehashed_at_read_time_before_export(tmp_path):
    # Catches: stale catalog digest plus changed object body returning verified selected text.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    row = list(c.rows())[0]
    row_ref = inspect_corpus(c)["rows"][0]["row_ref"]
    catalog_digest = c.digest().seal
    with open(c._object_path(row["sha256"]), "w", encoding="utf-8") as f:
        f.write("MUTATED!")

    inspected = inspect_corpus(c)
    assert inspected["verified"] is False
    assert inspected["rows"][0]["body_status"] == "CORRUPT"
    assert inspected["rows"][0]["excerpt"] == ""
    assert {o["reason"] for o in inspected["rows"][0]["omissions"]} == {"body_corrupt"}

    with pytest.raises(ValueError, match="CORRUPT"):
        select_context(
            c,
            [{"row_ref": row_ref, "start": 0, "limit": 8}],
            expected_corpus_digest=catalog_digest,
        )


def test_selection_does_not_verify_unselected_bodies(tmp_path):
    # Catches: max_rows=1 selection doing whole-corpus object reads before selecting one row.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    first_ref = inspect_corpus(c, max_rows=1)["rows"][0]["row_ref"]
    rows = list(c.rows())
    os.remove(c._object_path(rows[1]["sha256"]))

    payload = select_context(
        c,
        [{"row_ref": first_ref, "start": 10, "limit": 19}],
        expected_corpus_digest=c.digest().seal,
        max_rows=1,
    )

    assert payload["verified"] is True
    assert payload["verified_scope"] == "selected_rows"
    assert payload["selections"][0]["text"] == "DECISION-FACT-ALPHA"


def test_context_refuses_ancestor_swap_after_precheck_before_read(tmp_path, monkeypatch):
    # Catches: validating ancestors by path, then opening an outside symlink target by name.
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "original0", source="synthetic")])
    initial = ctx.inspect_corpus(c)
    row = initial["rows"][0]
    target = Path(c._object_path(row["sha256"]))
    shard = target.parent
    backup = shard.with_name(shard.name + "-saved")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / target.name).write_text("original0", encoding="utf-8")
    state = {"attempted": False, "replaced": False, "blocked": False}

    if os.name == "nt":
        real_open_child = ctx._windows_nt_create_child

        def swapped_open_child(parent_handle, component, *, directory, missing_ok=False):
            if component == target.name and not directory and not state["attempted"]:
                state["attempted"] = True
                try:
                    shard.rename(backup)
                    _symlink_or_skip(outside, shard, target_is_directory=True)
                except OSError:
                    state["blocked"] = True
                else:
                    state["replaced"] = True
            return real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)

        monkeypatch.setattr(ctx, "_windows_nt_create_child", swapped_open_child)
    else:
        real_open = ctx.os.open

        def swapped_open(path, *args, **kwargs):
            if path == target.name and not state["attempted"]:
                state["attempted"] = True
                try:
                    shard.rename(backup)
                    _symlink_or_skip(outside, shard, target_is_directory=True)
                except OSError:
                    state["blocked"] = True
                else:
                    state["replaced"] = True
            return real_open(path, *args, **kwargs)

        _patch_os_open_with_dir_fd_support(monkeypatch, ctx, swapped_open)

    try:
        selected = ctx.select_context(
            c,
            [{"row_ref": row["row_ref"]}],
            expected_corpus_digest=initial["corpus_digest"],
        )
        assert state["attempted"] is True
        assert selected["selections"][0]["text"] == "original0"
    finally:
        if state["replaced"] and shard.is_symlink():
            shard.unlink()
        if backup.exists() and not shard.exists():
            backup.rename(shard)


def test_context_charges_growing_failed_read_against_aggregate_budget(tmp_path, monkeypatch):
    # Catches: sizing reads from stale fstat, then charging zero bytes after a failed oversized read.
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([
        _item("document", "x", "x", "original0", source="synthetic"),
        _item("document", "y", "y", "second001", source="synthetic"),
    ])
    first = list(c.rows())[0]
    target = Path(c._object_path(first["sha256"]))
    real_read = ctx.os.read
    real_fstat = ctx.os.fstat
    state = {"body_fd": None, "grown": False, "bytes_read": 0, "next_body_fd": False}

    if os.name == "nt":
        real_open_child = ctx._windows_nt_create_child
        real_handle_to_fd = ctx._windows_handle_to_fd

        def tracking_open_child(parent_handle, component, *, directory, missing_ok=False):
            handle = real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)
            if component == target.name and not directory and handle is not None:
                state["next_body_fd"] = True
            return handle

        def tracking_handle_to_fd(handle):
            fd = real_handle_to_fd(handle)
            if state["next_body_fd"]:
                state["body_fd"] = fd
                state["next_body_fd"] = False
            return fd

        monkeypatch.setattr(ctx, "_windows_nt_create_child", tracking_open_child)
        monkeypatch.setattr(ctx, "_windows_handle_to_fd", tracking_handle_to_fd)
    else:
        real_open = ctx.os.open

        def tracking_open(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if path == target.name:
                state["body_fd"] = fd
            return fd

        _patch_os_open_with_dir_fd_support(monkeypatch, ctx, tracking_open)

    def growing_read(fd, n):
        if fd == state["body_fd"] and not state["grown"]:
            state["grown"] = True
        result = real_read(fd, n)
        if fd == state["body_fd"]:
            state["bytes_read"] += len(result)
        return result

    def grown_fstat(fd):
        result = real_fstat(fd)
        if fd == state["body_fd"] and state["grown"]:
            fields = list(result)
            fields[6] = len(b"original0extra-growth")
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(ctx.os, "read", growing_read)
    monkeypatch.setattr(ctx.os, "fstat", grown_fstat)
    inspected = ctx.inspect_corpus(c, max_read_bytes=9, max_body_bytes=100)

    assert state["bytes_read"] <= 9
    assert inspected["rows"][0]["body_status"] == "READ_BUDGET_EXHAUSTED"
    assert inspected["rows"][0]["body_bytes_read"] == state["bytes_read"] == 9
    assert inspected["rows"][1]["body_status"] == "READ_BUDGET_EXHAUSTED"
    assert inspected["rows"][1]["body_bytes_read"] == 0


def _copy_catalog_only(source: Path, replacement: Path) -> None:
    replacement.mkdir()
    (replacement / "objects").mkdir()
    shutil.copy2(source / "catalog.jsonl", replacement / "catalog.jsonl")


def test_context_retains_original_root_when_root_path_is_replaced(tmp_path, monkeypatch):
    # Catches: reading selected bodies from a replacement directory at the original corpus pathname.
    if os.name != "nt":
        pytest.skip("Windows native root-replacement control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "original-root", source="synthetic")])
    initial = ctx.inspect_corpus(c)
    root = Path(c._root)
    saved = tmp_path / "saved-original-corpus"
    replacement = tmp_path / "replacement-corpus"
    _copy_catalog_only(root, replacement)
    target_name = list(c.rows())[0]["sha256"][2:]
    real_open_child = ctx._windows_nt_create_child
    state = {"attempted": False, "blocked": False, "replaced": False}

    def replacing_open_child(parent_handle, component, *, directory, missing_ok=False):
        if component == target_name and not directory and not state["attempted"]:
            state["attempted"] = True
            try:
                root.rename(saved)
                replacement.rename(root)
            except OSError:
                state["blocked"] = True
            else:
                state["replaced"] = True
        return real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)

    try:
        monkeypatch.setattr(ctx, "_windows_nt_create_child", replacing_open_child)
        selected = ctx.select_context(
            c,
            [{"row_ref": initial["rows"][0]["row_ref"], "start": 0, "limit": 13}],
            expected_corpus_digest=initial["corpus_digest"],
        )
        assert state["attempted"] is True
        assert selected["selections"][0]["text"] == "original-root"
    finally:
        monkeypatch.setattr(ctx, "_windows_nt_create_child", real_open_child, raising=False)
        if state["replaced"]:
            if root.exists():
                shutil.rmtree(root)
            saved.rename(root)
        elif saved.exists() and not root.exists():
            saved.rename(root)
        if replacement.exists():
            shutil.rmtree(replacement)


def test_context_retains_original_root_when_above_root_path_is_replaced(tmp_path, monkeypatch):
    # Catches: re-resolving ancestors above the selected corpus after operation authority acquisition.
    if os.name != "nt":
        pytest.skip("Windows native above-root replacement control")
    import gather.context as ctx

    parent = tmp_path / "selected-parent"
    parent.mkdir()
    c = Corpus(str(parent / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "above-root-original", source="synthetic")])
    initial = ctx.inspect_corpus(c)
    replacement_parent = tmp_path / "replacement-parent"
    replacement_root = replacement_parent / "corpus"
    replacement_parent.mkdir()
    _copy_catalog_only(Path(c._root), replacement_root)
    saved_parent = tmp_path / "saved-selected-parent"
    target_name = list(c.rows())[0]["sha256"][2:]
    real_open_child = ctx._windows_nt_create_child
    state = {"attempted": False, "blocked": False, "replaced": False}

    def replacing_open_child(parent_handle, component, *, directory, missing_ok=False):
        if component == target_name and not directory and not state["attempted"]:
            state["attempted"] = True
            try:
                parent.rename(saved_parent)
                replacement_parent.rename(parent)
            except OSError:
                state["blocked"] = True
            else:
                state["replaced"] = True
        return real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)

    try:
        monkeypatch.setattr(ctx, "_windows_nt_create_child", replacing_open_child)
        selected = ctx.select_context(
            c,
            [{"row_ref": initial["rows"][0]["row_ref"], "start": 0, "limit": 19}],
            expected_corpus_digest=initial["corpus_digest"],
        )
        assert state["attempted"] is True
        assert selected["selections"][0]["text"] == "above-root-original"
    finally:
        monkeypatch.setattr(ctx, "_windows_nt_create_child", real_open_child, raising=False)
        if state["replaced"]:
            if parent.exists():
                shutil.rmtree(parent)
            saved_parent.rename(parent)
        elif saved_parent.exists() and not parent.exists():
            saved_parent.rename(parent)
        if replacement_parent.exists():
            shutil.rmtree(replacement_parent)


def test_context_posix_descriptor_handoff_reads_original_root_after_path_replacement(tmp_path):
    # Catches: accepting a retained root fd but reopening the corpus path and reading a replacement corpus.
    if os.name == "nt":
        pytest.skip("POSIX descriptor handoff control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "descriptor-original", source="synthetic")])
    initial = ctx.inspect_corpus(c)
    root = Path(c._root)
    saved = tmp_path / "saved-original-corpus"
    replacement = Corpus(str(tmp_path / "replacement-corpus"), fsync=False)
    replacement.add([_item("document", "x", "x", "replacement-canary", source="synthetic")])
    replacement_root = Path(replacement._root)
    fd, descriptor = _posix_descriptor_for_corpus(ctx, c)

    try:
        root.rename(saved)
        replacement_root.rename(root)

        inspected = ctx.inspect_corpus(descriptor, max_rows=1, excerpt_chars=40)
        selected = ctx.select_context(
            descriptor,
            [{"row_ref": initial["rows"][0]["row_ref"]}],
            expected_corpus_digest=initial["corpus_digest"],
        )

        assert inspected["rows"][0]["excerpt"] == "descriptor-original"
        assert selected["selections"][0]["text"] == "descriptor-original"
        assert "replacement-canary" not in json.dumps(selected, sort_keys=True)
    finally:
        os.close(fd)
        if root.exists():
            shutil.rmtree(root)
        if saved.exists() and not root.exists():
            saved.rename(root)


def test_context_descriptor_handoff_rejects_identity_mismatch_before_catalog_read(tmp_path, monkeypatch):
    # Catches: treating a caller descriptor as self-authorizing or falling back to a path read.
    import gather.context as ctx

    original = Corpus(str(tmp_path / "original-corpus"), fsync=False)
    original.add([_item("document", "x", "x", "identity-original", source="synthetic")])
    replacement = Corpus(str(tmp_path / "replacement-corpus"), fsync=False)
    replacement.add([_item("document", "x", "x", "identity-replacement-canary", source="synthetic")])
    owner, original_descriptor = _descriptor_for_corpus(ctx, original)
    borrowed, replacement_descriptor = _descriptor_for_corpus(ctx, replacement)
    mismatched = type(replacement_descriptor)(
        expected_identity=original_descriptor.expected_identity,
        fd=replacement_descriptor.fd,
        handle=replacement_descriptor.handle,
    )
    state = {"catalog_read": False}

    def forbidden_catalog(*args, **kwargs):
        state["catalog_read"] = True
        raise AssertionError("catalog read happened after descriptor identity mismatch")

    monkeypatch.setattr(ctx, "_load_catalog_rows", forbidden_catalog)
    try:
        with pytest.raises(ValueError, match="UNSAFE_PATH|corpus root|identity"):
            ctx.inspect_corpus(mismatched)
        assert state["catalog_read"] is False
    finally:
        if os.name == "nt":
            ctx._windows_close_handle(owner)
            ctx._windows_close_handle(borrowed)
        else:
            os.close(owner)
            os.close(borrowed)


def test_context_descriptor_handoff_keeps_caller_authority_open(tmp_path):
    # Catches: Gather closing the borrowed fd/HANDLE instead of only its duplicate.
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "caller-owned", source="synthetic")])
    owner, descriptor = _descriptor_for_corpus(ctx, c)
    try:
        inspected = ctx.inspect_corpus(descriptor)
        assert inspected["rows"][0]["excerpt"] == "caller-owned"
        if os.name == "nt":
            ctx._windows_validate_directory_handle(owner)
        else:
            assert os.fstat(owner).st_ino == descriptor.expected_identity.inode
    finally:
        if os.name == "nt":
            ctx._windows_close_handle(owner)
        else:
            os.close(owner)


def test_context_descriptor_handoff_rejects_closed_or_reused_authority(tmp_path):
    # Catches: accepting a closed/reused descriptor without re-validating identity before reads.
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "closed-root", source="synthetic")])
    owner, descriptor = _descriptor_for_corpus(ctx, c)
    if os.name == "nt":
        ctx._windows_close_handle(owner)
    else:
        os.close(owner)

    with pytest.raises(ValueError, match="UNSAFE_PATH|corpus root|identity"):
        ctx.inspect_corpus(descriptor)


def test_context_descriptor_handoff_preserves_body_read_budget_semantics(tmp_path):
    # Catches: descriptor-backed reads bypassing max_read_bytes accounting.
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "0123456789abcdef", source="synthetic")])
    owner, descriptor = _descriptor_for_corpus(ctx, c)
    try:
        inspected = ctx.inspect_corpus(descriptor, max_read_bytes=10)
        assert inspected["rows"][0]["body_status"] == "READ_BUDGET_EXHAUSTED"
        assert inspected["rows"][0]["omissions"] == [{"reason": "read_budget_exhausted", "max_read_bytes": 10}]
    finally:
        if os.name == "nt":
            ctx._windows_close_handle(owner)
        else:
            os.close(owner)


def test_context_windows_descriptor_handoff_uses_handle_without_path_fallback(tmp_path, monkeypatch):
    # Catches: accepting a Windows HANDLE argument but still opening the corpus root by path.
    if os.name != "nt":
        pytest.skip("Windows descriptor handoff control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "windows-handle", source="synthetic")])
    owner, descriptor = _windows_descriptor_for_corpus(ctx, c)

    def forbidden_path_open(path):
        raise AssertionError(f"descriptor-backed context reopened path {path}")

    monkeypatch.setattr(ctx, "_windows_createfile_root", forbidden_path_open)
    try:
        inspected = ctx.inspect_corpus(descriptor, max_rows=1, excerpt_chars=40)
        assert inspected["rows"][0]["excerpt"] == "windows-handle"
        ctx._windows_validate_directory_handle(owner)
    finally:
        ctx._windows_close_handle(owner)


def test_context_windows_descriptor_duplicate_failure_keeps_caller_handle_open(tmp_path, monkeypatch):
    # Catches: treating a failed duplicate as ownership transfer and closing the caller HANDLE.
    if os.name != "nt":
        pytest.skip("Windows descriptor handoff control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "windows-duplicate-fault", source="synthetic")])
    owner, descriptor = _windows_descriptor_for_corpus(ctx, c)

    def failing_duplicate(handle):
        assert handle == owner
        raise ValueError("synthetic duplicate failure")

    monkeypatch.setattr(ctx, "_windows_duplicate_handle", failing_duplicate)
    try:
        with pytest.raises(ValueError, match="UNSAFE_PATH"):
            ctx.inspect_corpus(descriptor)
        ctx._windows_validate_directory_handle(owner)
    finally:
        ctx._windows_close_handle(owner)


def test_context_reports_bytes_read_when_post_read_authority_check_fails(tmp_path, monkeypatch):
    # Catches: dropping consumed-byte accounting when a post-read descriptor check fails.
    if os.name != "nt":
        pytest.skip("Windows descriptor post-read accounting control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "original0", source="synthetic")])
    target_name = list(c.rows())[0]["sha256"][2:]
    real_assert = ctx._assert_windows_fd_final_path
    state = {"body_checks": 0}

    def failing_second_check(fd, expected_final_path, *, bytes_read=0):
        if str(expected_final_path).lower().endswith(target_name.lower()):
            state["body_checks"] += 1
            if state["body_checks"] == 2:
                raise ctx._ReadFailure(ctx.UNSAFE_PATH, bytes_read=bytes_read)
        return real_assert(fd, expected_final_path)

    monkeypatch.setattr(ctx, "_assert_windows_fd_final_path", failing_second_check)
    inspected = ctx.inspect_corpus(c)

    assert state["body_checks"] == 2
    assert inspected["rows"][0]["body_status"] == "UNSAFE_PATH"
    assert inspected["rows"][0]["body_bytes_read"] == len("original0")


def test_context_windows_failed_crt_transfer_closes_selected_handle_once(tmp_path, monkeypatch):
    # Catches: both the transfer helper and its caller closing the same native handle on transfer failure.
    if os.name != "nt":
        pytest.skip("Windows native handle ownership control")
    import msvcrt

    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "original0", source="synthetic")])
    initial = ctx.inspect_corpus(c)
    target_name = list(c.rows())[0]["sha256"][2:]
    real_open_child = ctx._windows_nt_create_child
    real_close = ctx._windows_close_handle
    real_open_osfhandle = msvcrt.open_osfhandle
    state = {"target_handle": None, "target_close_count": 0}

    def tracking_open_child(parent_handle, component, *, directory, missing_ok=False):
        handle = real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)
        if component == target_name and not directory and handle is not None:
            state["target_handle"] = handle
        return handle

    def tracking_close(handle):
        if handle == state["target_handle"]:
            state["target_close_count"] += 1
        return real_close(handle)

    def failing_open_osfhandle(handle, flags):
        if handle == state["target_handle"]:
            raise OSError("synthetic CRT transfer failure")
        return real_open_osfhandle(handle, flags)

    monkeypatch.setattr(ctx, "_windows_nt_create_child", tracking_open_child)
    monkeypatch.setattr(ctx, "_windows_close_handle", tracking_close)
    monkeypatch.setattr(msvcrt, "open_osfhandle", failing_open_osfhandle)

    with pytest.raises(OSError, match="synthetic CRT transfer failure"):
        ctx.select_context(
            c,
            [{"row_ref": initial["rows"][0]["row_ref"]}],
            expected_corpus_digest=initial["corpus_digest"],
        )

    assert state["target_handle"] is not None
    assert state["target_close_count"] == 1


def test_context_windows_validation_failure_closes_selected_handle_once(tmp_path, monkeypatch):
    # Catches: leaked or double-closed native handles when validation refuses the selected file.
    if os.name != "nt":
        pytest.skip("Windows native handle ownership control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "original0", source="synthetic")])
    target_name = list(c.rows())[0]["sha256"][2:]
    real_open_child = ctx._windows_nt_create_child
    real_close = ctx._windows_close_handle
    real_validate = ctx._windows_validate_file_handle
    state = {"target_handle": None, "target_close_count": 0}

    def tracking_open_child(parent_handle, component, *, directory, missing_ok=False):
        handle = real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)
        if component == target_name and not directory and handle is not None:
            state["target_handle"] = handle
        return handle

    def tracking_close(handle):
        if handle == state["target_handle"]:
            state["target_close_count"] += 1
        return real_close(handle)

    def failing_validate(handle):
        if handle == state["target_handle"]:
            raise ctx._ReadFailure(ctx.UNSAFE_PATH)
        return real_validate(handle)

    monkeypatch.setattr(ctx, "_windows_nt_create_child", tracking_open_child)
    monkeypatch.setattr(ctx, "_windows_close_handle", tracking_close)
    monkeypatch.setattr(ctx, "_windows_validate_file_handle", failing_validate)

    inspected = ctx.inspect_corpus(c)

    assert inspected["rows"][0]["body_status"] == "UNSAFE_PATH"
    assert state["target_handle"] is not None
    assert state["target_close_count"] == 1


def test_context_windows_successful_crt_transfer_leaves_handle_to_fd(tmp_path, monkeypatch):
    # Catches: closing the native file handle after successful transfer to the CRT descriptor.
    if os.name != "nt":
        pytest.skip("Windows native handle ownership control")
    import gather.context as ctx

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "x", "x", "original0", source="synthetic")])
    initial = ctx.inspect_corpus(c)
    target_name = list(c.rows())[0]["sha256"][2:]
    real_open_child = ctx._windows_nt_create_child
    real_close = ctx._windows_close_handle
    state = {"target_handle": None, "target_close_count": 0}

    def tracking_open_child(parent_handle, component, *, directory, missing_ok=False):
        handle = real_open_child(parent_handle, component, directory=directory, missing_ok=missing_ok)
        if component == target_name and not directory and handle is not None:
            state["target_handle"] = handle
        return handle

    def tracking_close(handle):
        if handle == state["target_handle"]:
            state["target_close_count"] += 1
        return real_close(handle)

    monkeypatch.setattr(ctx, "_windows_nt_create_child", tracking_open_child)
    monkeypatch.setattr(ctx, "_windows_close_handle", tracking_close)

    selected = ctx.select_context(
        c,
        [{"row_ref": initial["rows"][0]["row_ref"]}],
        expected_corpus_digest=initial["corpus_digest"],
    )

    assert selected["selections"][0]["text"] == "original0"
    assert state["target_handle"] is not None
    assert state["target_close_count"] == 0


def test_context_root_symlink_refusal_is_public_value_error(tmp_path, capsys):
    # Catches: leaking the internal _ReadFailure exception for an unsafe corpus root.
    import gather.context as ctx

    real_root = tmp_path / "real-corpus"
    c = Corpus(str(real_root), fsync=False)
    c.add([_item("document", "x", "x", "original0", source="synthetic")])
    link_root = tmp_path / "linked-corpus"
    _symlink_or_skip(real_root, link_root, target_is_directory=True)
    linked = Corpus(str(link_root), fsync=False)
    row = list(c.rows())[0]
    expected = c.digest().seal

    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        ctx.inspect_corpus(linked)
    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        ctx.select_context(linked, [{"row_ref": ctx.row_ref(row)}], expected_corpus_digest=expected)

    resp = _mcp_call("gather.context", {"corpus": str(link_root)})
    assert resp["result"]["isError"] is True
    assert "UNSAFE_PATH" in resp["result"]["content"][0]["text"]

    assert main(["corpus", "context", str(link_root), "--json"]) == 1
    captured = capsys.readouterr()
    assert "UNSAFE_PATH" in captured.err


def test_context_posix_fifo_body_and_catalog_refuse_without_blocking(tmp_path):
    # Catches: opening a FIFO read-only before fstat, which blocks with no writer on POSIX.
    if os.name != "posix":
        pytest.skip("POSIX FIFO nonblocking control")
    probe = r'''
import json
import os
import sys
import tempfile
from pathlib import Path

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "src"))

from gather.context import inspect_corpus
from gather.item import make_item
from gather.store import Corpus

def item(text):
    return make_item(kind="document", id="x", title="x", text=text, source="synthetic", ref="x", method="file-read", fetched_at=1.0)

out = {}
with tempfile.TemporaryDirectory(prefix="gather-fifo-body-") as d:
    c = Corpus(str(Path(d) / "corpus"), fsync=False)
    c.add([item("original0")])
    row = next(c.rows())
    target = Path(c._object_path(row["sha256"]))
    target.unlink()
    os.mkfifo(target)
    inspected = inspect_corpus(c, max_body_bytes=1, max_read_bytes=1)
    out["body"] = {
        "verified": inspected["verified"],
        "status": inspected["rows"][0]["body_status"],
        "omissions": inspected["rows"][0]["omissions"],
    }
with tempfile.TemporaryDirectory(prefix="gather-fifo-catalog-") as d:
    c = Corpus(str(Path(d) / "corpus"), fsync=False)
    c.add([item("original0")])
    catalog = Path(c._catalog)
    catalog.unlink()
    os.mkfifo(catalog)
    try:
        inspect_corpus(c, max_catalog_bytes=1)
    except Exception as exc:
        out["catalog"] = {"exception": type(exc).__name__, "message": str(exc)}
print(json.dumps(out, sort_keys=True))
'''
    proc = subprocess.run(
        [sys.executable, "-c", probe, str(Path(__file__).resolve().parents[1])],
        text=True,
        capture_output=True,
        timeout=2,
    )
    assert proc.returncode == 0, proc.stderr
    observed = json.loads(proc.stdout)
    assert observed["body"] == {
        "verified": False,
        "status": "UNSAFE_PATH",
        "omissions": [{"reason": "unsafe_body_path"}],
    }
    assert observed["catalog"]["exception"] == "ValueError"
    assert "UNSAFE_PATH" in observed["catalog"]["message"]


def test_context_refuses_oversized_body_and_read_budget(tmp_path):
    # Catches: full body reads that ignore explicit selected-object and aggregate read caps.
    from gather.context import inspect_corpus, row_ref, select_context

    c = _corpus(tmp_path)
    first = list(c.rows())[0]
    inspected = inspect_corpus(c, max_body_bytes=10)
    assert inspected["rows"][0]["body_status"] == "BODY_OVERSIZE"
    assert inspected["rows"][0]["omissions"] == [
        {"reason": "body_oversize", "max_body_bytes": 10}
    ]

    budgeted = inspect_corpus(c, max_read_bytes=10)
    assert budgeted["rows"][0]["body_status"] == "READ_BUDGET_EXHAUSTED"
    assert budgeted["rows"][0]["omissions"] == [
        {"reason": "read_budget_exhausted", "max_read_bytes": 10}
    ]

    with pytest.raises(ValueError, match="BODY_OVERSIZE"):
        select_context(
            c,
            [{"row_ref": row_ref(first), "start": 0, "limit": 5}],
            expected_corpus_digest=c.digest().seal,
            max_body_bytes=10,
        )


def test_context_refuses_oversized_catalog_before_parsing(tmp_path):
    # Catches: unbounded catalog allocation in the readable context path.
    from gather.context import inspect_corpus

    c = _corpus(tmp_path)
    with pytest.raises(ValueError, match="max_catalog_bytes"):
        inspect_corpus(c, max_catalog_bytes=10)


def _symlink_or_skip(target: Path, link: Path, *, target_is_directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable on this host: {exc}")


def test_context_refuses_object_symlink_outside_corpus(tmp_path):
    # Catches: object paths that are hash-shaped but resolve outside the selected corpus root.
    from gather.context import inspect_corpus, row_ref, select_context

    c = _corpus(tmp_path)
    first = list(c.rows())[0]
    object_path = Path(c._object_path(first["sha256"]))
    object_path.unlink()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("outside body that must not be read", encoding="utf-8")
    _symlink_or_skip(outside, object_path)

    inspected = inspect_corpus(c)
    assert inspected["verified"] is False
    assert inspected["rows"][0]["body_status"] == "UNSAFE_PATH"
    assert inspected["rows"][0]["excerpt"] == ""
    assert inspected["rows"][0]["omissions"] == [{"reason": "unsafe_body_path"}]

    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        select_context(
            c,
            [{"row_ref": row_ref(first), "start": 0, "limit": 5}],
            expected_corpus_digest=c.digest().seal,
        )


def test_context_refuses_object_shard_symlink_outside_corpus(tmp_path):
    # Catches: safe-looking object paths whose ancestor shard is replaced with a link.
    from gather.context import inspect_corpus, row_ref, select_context

    c = _corpus(tmp_path)
    first = list(c.rows())[0]
    object_path = Path(c._object_path(first["sha256"]))
    shard_dir = object_path.parent
    shutil.rmtree(shard_dir)
    outside_dir = tmp_path / "outside-shard"
    outside_dir.mkdir()
    (outside_dir / object_path.name).write_text("outside body that must not be read", encoding="utf-8")
    _symlink_or_skip(outside_dir, shard_dir, target_is_directory=True)

    inspected = inspect_corpus(c)
    assert inspected["verified"] is False
    assert inspected["rows"][0]["body_status"] == "UNSAFE_PATH"
    assert inspected["rows"][0]["omissions"] == [{"reason": "unsafe_body_path"}]

    with pytest.raises(ValueError, match="UNSAFE_PATH"):
        select_context(
            c,
            [{"row_ref": row_ref(first), "start": 0, "limit": 5}],
            expected_corpus_digest=c.digest().seal,
        )


def test_context_rejects_invalid_cap_and_selection_types(tmp_path):
    # Catches: Python accepting bools, strings, floats, or unexpected selection keys as limits.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    row = inspect_corpus(c)["rows"][0]
    for value in (True, 1.5, "1"):
        with pytest.raises(ValueError, match="max_rows must be an integer"):
            inspect_corpus(c, max_rows=value)

    with pytest.raises(ValueError, match="unexpected field"):
        select_context(
            c,
            [{"row_ref": row["row_ref"], "start": 0, "limit": 1, "extra": "nope"}],
            expected_corpus_digest=c.digest().seal,
        )
    with pytest.raises(ValueError, match="selection start must be an integer"):
        select_context(
            c,
            [{"row_ref": row["row_ref"], "start": True, "limit": 1}],
            expected_corpus_digest=c.digest().seal,
        )
    with pytest.raises(ValueError, match="max_rows must be <="):
        select_context(
            c,
            [{"row_ref": row["row_ref"], "start": 0, "limit": 1}],
            expected_corpus_digest=c.digest().seal,
            max_rows=51,
        )


def test_context_mcp_rejects_bool_string_and_extra_selection_fields(tmp_path):
    # Catches: MCP coercing JSON values before the shared strict Python validation runs.
    from gather.context import inspect_corpus

    c = _corpus(tmp_path)
    corpus_dir = str(tmp_path / "corpus")
    row_ref = inspect_corpus(c)["rows"][0]["row_ref"]

    for value in (True, 1.5, "1"):
        resp = _mcp_call("gather.context", {"corpus": corpus_dir, "max_rows": value})
        assert resp["result"]["isError"] is True
        assert "max_rows must be an integer" in resp["result"]["content"][0]["text"]

    resp = _mcp_call("gather.context", {"corpus": corpus_dir, "max_rows": None})
    assert resp["result"].get("isError") is not True

    resp = _mcp_call("gather.context", {
        "corpus": corpus_dir,
        "select": [{"row_ref": row_ref, "start": 0, "limit": 1, "extra": "nope"}],
        "expected_corpus_digest": c.digest().seal,
    })
    assert resp["result"]["isError"] is True
    assert "unexpected field" in resp["result"]["content"][0]["text"]


def test_non_supporting_source_remains_acquired_context_not_a_claim_verdict(tmp_path):
    # Catches: false success where a provenance receipt is misreported as semantic support.
    from gather.context import inspect_corpus, select_context

    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item(
        "document",
        "negative-source",
        "Negative source",
        "This source explicitly does not support launching Alpha.",
    )])
    row_ref = inspect_corpus(c)["rows"][0]["row_ref"]
    payload = select_context(
        c,
        [{"row_ref": row_ref, "start": 0, "limit": 56}],
        expected_corpus_digest=c.digest().seal,
    )

    assert payload["selections"][0]["text"] == "This source explicitly does not support launching Alpha."
    assert payload["verified"] is True
    assert payload["does_not_prove"] == [
        "truth of selected source claims",
        "claim support or contradiction",
        "completeness of gathered coverage",
        "that a downstream model used this context correctly",
    ]
    assert "supports" not in set(payload)
    assert "verdict" not in set(payload)


def test_context_newline_source_identity_and_readable_view_reach_python_cli_mcp(tmp_path, capsys):
    # Catches: conflating exact source identity with the LF-normalized readable view at API boundaries.
    from gather.context import inspect_corpus, select_context

    source = "head\r\nDECISION\rpart\nµ-tail"
    view = _view_text(source)
    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("comment", "newline-comment", "Newline comment", source, source="video", method="yt-dlp")])
    corpus_dir = str(tmp_path / "corpus")

    inspected = inspect_corpus(c, excerpt_chars=40)
    row = inspected["rows"][0]
    start = view.index("DECISION")
    limit = len("DECISION\npart")

    assert inspected["schema"] == "gather.readable-corpus/v1"
    assert inspected["corpus_digest_version"] == "storage-witnessed/v1"
    assert row["body_status"] == "MATCH"
    assert row["sha256"] == content_hash(source)
    assert row["verified_sha256"] == content_hash(source)
    assert row["source_sha256"] == content_hash(source)
    assert row["view_sha256"] == content_hash(view)
    assert row["view_codec"] == "utf8-crlf-cr-to-lf/v1"
    assert row["storage"]["codec"] == "utf8-exact/v1"
    assert row["storage_status"] == "MATCH"
    assert row["storage_witnessed"] is True
    assert row["excerpt"] == view

    selected = select_context(
        c,
        [{"row_ref": row["row_ref"], "start": start, "limit": limit}],
        expected_corpus_digest=inspected["corpus_digest"],
    )
    picked = selected["selections"][0]
    assert picked["text"] == "DECISION\npart"
    assert picked["range"] == {"start": start, "end": start + limit}
    assert picked["full_text_chars"] == len(view)
    assert picked["full_source_chars"] == len(source)
    assert picked["source_sha256"] == content_hash(source)
    assert picked["view_sha256"] == content_hash(view)
    assert picked["view_codec"] == "utf8-crlf-cr-to-lf/v1"
    assert picked["storage_status"] == "MATCH"
    assert picked["storage_witnessed"] is True

    assert main([
        "corpus",
        "context",
        corpus_dir,
        "--json",
        "--select",
        f"{row['row_ref']}:{start}:{limit}",
        "--expect-digest",
        inspected["corpus_digest"],
    ]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["selections"][0]["text"] == "DECISION\npart"
    assert cli_payload["selections"][0]["source_sha256"] == content_hash(source)
    assert cli_payload["selections"][0]["view_sha256"] == content_hash(view)

    resp = _mcp_call("gather.context", {
        "corpus": corpus_dir,
        "select": [{"row_ref": row["row_ref"], "start": start, "limit": limit}],
        "expected_corpus_digest": inspected["corpus_digest"],
    })
    mcp_payload = json.loads(resp["result"]["content"][0]["text"])
    assert resp["result"].get("isError") is not True
    assert mcp_payload == selected


def test_context_expected_digest_rejects_storage_witness_stripping(tmp_path):
    # Catches: caller-pinned corpus digests failing to notice catalog downgrade by witness stripping.
    from gather.context import inspect_corpus, select_context

    source = "line one\nline two"
    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "storage-row", "Storage row", source)])
    before = inspect_corpus(c)
    row_ref = before["rows"][0]["row_ref"]
    rows = list(c.rows())
    stripped = [{k: v for k, v in row.items() if k != "storage"} for row in rows]
    _rewrite_catalog(c, stripped)

    assert inspect_corpus(c)["corpus_digest"] != before["corpus_digest"]
    with pytest.raises(ValueError, match="expected corpus digest"):
        select_context(
            c,
            [{"row_ref": row_ref, "start": 0, "limit": 4}],
            expected_corpus_digest=before["corpus_digest"],
        )

    # Recomputing after mutation is an explicit downgrade acceptance, not an external trust anchor.
    after = inspect_corpus(c)
    payload = select_context(
        c,
        [{"row_ref": row_ref, "start": 0, "limit": 4}],
        expected_corpus_digest=after["corpus_digest"],
    )
    assert payload["corpus_digest_version"] == "legacy-compatible/v1"
    assert payload["selections"][0]["storage_witnessed"] is False
    assert payload["selections"][0]["storage_status"] == "LEGACY_COMPATIBLE"


def test_context_cli_and_mcp_reject_new_storage_row_when_newlines_are_tampered(tmp_path, capsys):
    # Catches: readable context exporting a new exact-UTF8 row after its object bytes changed.
    from gather.context import inspect_corpus, row_ref, select_context

    source = "line one\nline two"
    c = Corpus(str(tmp_path / "corpus"), fsync=False)
    c.add([_item("document", "tampered-newline", "Tampered newline", source)])
    row = next(c.rows())
    ref = row_ref(row)
    digest = c.digest().seal
    with open(c._object_path(row["sha256"]), "wb") as f:
        f.write(b"line one\rline two")

    inspected = inspect_corpus(c)
    assert inspected["verified"] is False
    assert inspected["rows"][0]["body_status"] == "CORRUPT"
    assert inspected["rows"][0]["storage_status"] == "CORRUPT"
    with pytest.raises(ValueError, match="body status CORRUPT"):
        select_context(c, [{"row_ref": ref}], expected_corpus_digest=digest)

    assert main([
        "corpus",
        "context",
        str(tmp_path / "corpus"),
        "--json",
        "--select",
        ref,
        "--expect-digest",
        digest,
    ]) == 1
    assert "body status CORRUPT" in capsys.readouterr().err

    resp = _mcp_call("gather.context", {
        "corpus": str(tmp_path / "corpus"),
        "select": [{"row_ref": ref}],
        "expected_corpus_digest": digest,
    })
    assert resp["result"]["isError"] is True
    assert "body status CORRUPT" in resp["result"]["content"][0]["text"]


def test_corpus_context_cli_inspects_and_selects_private_context(tmp_path, capsys):
    # Catches: CLI diverging from the Python API contract.
    c = _corpus(tmp_path)
    corpus_dir = str(tmp_path / "corpus")

    assert main(["corpus", "context", corpus_dir, "--json", "--excerpt-chars", "12"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    row_ref = inspected["rows"][0]["row_ref"]

    assert inspected["schema"] == "gather.readable-corpus/v1"
    assert inspected["rows"][0]["excerpt"] == "0123456789DE"

    assert main([
        "corpus",
        "context",
        corpus_dir,
        "--json",
        "--select",
        f"{row_ref}:10:19",
        "--expect-digest",
        c.digest().seal,
    ]) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["schema"] == "gather.readable-context/v1"
    assert selected["selections"][0]["text"] == "DECISION-FACT-ALPHA"


def test_context_mcp_tool_matches_python_selection_payload(tmp_path):
    # Catches: MCP exposing only status/catalog while Python can select readable context.
    from gather.context import inspect_corpus, select_context

    c = _corpus(tmp_path)
    corpus_dir = str(tmp_path / "corpus")
    row_ref = inspect_corpus(c)["rows"][0]["row_ref"]
    expected = select_context(
        c,
        [{"row_ref": row_ref, "start": 10, "limit": 19}],
        expected_corpus_digest=c.digest().seal,
    )

    tools = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert "gather.context" in names

    resp = _mcp_call("gather.context", {
        "corpus": corpus_dir,
        "select": [{"row_ref": row_ref, "start": 10, "limit": 19}],
        "expected_corpus_digest": c.digest().seal,
    })
    body = json.loads(resp["result"]["content"][0]["text"])

    assert resp["result"].get("isError") is not True
    assert body == expected
