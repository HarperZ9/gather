"""Linux mount metadata parsing without native ABI assumptions."""

import errno
from pathlib import Path

import pytest

from gather.context import _linux_fd_mount_type


def _proc_files(monkeypatch, tmp_path, fdinfo, mountinfo):
    fd_path = tmp_path / "fdinfo"
    mount_path = tmp_path / "mountinfo"
    fd_path.write_bytes(fdinfo)
    mount_path.write_bytes(mountinfo)
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        replacement = {
            "/proc/self/fdinfo/73": fd_path,
            "/proc/self/mountinfo": mount_path,
        }.get(str(path).replace("\\", "/"))
        return original(replacement or path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)


def test_mount_identity_ignores_unrelated_non_utf8_path(monkeypatch, tmp_path):
    # A legal non-UTF8 pathname elsewhere in the namespace must not break reads.
    _proc_files(
        monkeypatch, tmp_path, b"pos:\t0\nmnt_id:\t17\n",
        b"11 1 0:4 / /unrelated-\xff rw - tmpfs tmpfs rw\n"
        b"17 1 8:2 / /safe rw - ext4 /dev/example rw\n",
    )
    assert _linux_fd_mount_type(73) == "ext4"


def test_mount_identity_uses_fd_mount_id_not_first_filesystem(monkeypatch, tmp_path):
    _proc_files(
        monkeypatch, tmp_path, b"mnt_id:\t29\n",
        b"17 1 8:2 / /safe rw - ext4 /dev/example rw\n"
        b"29 1 0:5 / /mounted rw - 9p source rw\n",
    )
    assert _linux_fd_mount_type(73) == "9p"


@pytest.mark.parametrize("fdinfo,mountinfo", [
    (b"pos:\t0\n", b"17 1 8:2 / /safe rw - ext4 source rw\n"),
    (b"mnt_id:\t29\n", b"17 1 8:2 / /safe rw - ext4 source rw\n"),
    (b"mnt_id:\t17\n", b"17 1 8:2 / /safe rw\n"),
    (b"mnt_id:\t17\n", b"17 1 8:2 / /safe rw -\n"),
])
def test_unclassifiable_descriptor_has_typed_failure(monkeypatch, tmp_path, fdinfo, mountinfo):
    _proc_files(monkeypatch, tmp_path, fdinfo, mountinfo)
    with pytest.raises(OSError) as error:
        _linux_fd_mount_type(73)
    assert error.value.errno == getattr(errno, "ENOTSUP", errno.EINVAL)
