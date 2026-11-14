"""The media probe behind ``gather saves``: each container read from synthetic bytes built with
``struct``, the container named by magic bytes, and damaged files giving empty fields."""

import struct

from saves_fixture import box, gif_bytes, jpeg_bytes, mp4_bytes, png_bytes, wav_bytes

from gather.media_probe import probe

EMPTY = {"width": None, "height": None, "duration_seconds": None, "sample_rate": None, "channels": None}


def probed(tmp_path, name, data, **kwargs):
    path = tmp_path / name
    path.write_bytes(data)
    return probe(str(path), **kwargs)


def fields(row):
    return {k: row[k] for k in EMPTY}


def el(ident, payload):
    """One EBML element with a one-byte or four-byte size."""
    size = bytes([0x80 | len(payload)]) if len(payload) < 127 else struct.pack(">I", 0x10000000 | len(payload))
    return bytes.fromhex(ident) + size + payload


def webm_parts():
    info = el("1549A966", el("2AD7B1", (1000000).to_bytes(3, "big")) + el("4489", struct.pack(">f", 4500.0)))
    video = el("AE", el("83", b"\x01") + el("E0", el("B0", b"\x02\x80") + el("BA", b"\x01\xe0")))
    audio = el("AE", el("83", b"\x02") + el("E1", el("B5", struct.pack(">f", 48000.0)) + el("9F", b"\x02")))
    return el("1A45DFA3", el("4282", b"webm")), info, el("1654AE6B", video + audio)


def test_png_jpeg_and_gif_give_width_and_height_and_the_container_ignores_the_extension(tmp_path):
    row, note = probed(tmp_path, "a.png", png_bytes(7, 5))
    assert (row["container"], row["kind"], row["bytes"], note) == ("png", "image", len(png_bytes()), "")
    assert fields(row) == {**EMPTY, "width": 7, "height": 5}
    row, _ = probed(tmp_path, "really-a-jpeg.mp3", jpeg_bytes(640, 480))
    assert (row["container"], row["kind"], row["width"], row["height"]) == ("jpeg", "image", 640, 480)
    row, _ = probed(tmp_path, "a.gif", gif_bytes(9, 8))
    assert (row["container"], row["width"], row["height"]) == ("gif", 9, 8)


def test_webp_reads_the_extended_lossless_and_lossy_headers(tmp_path):
    riff = lambda chunk: b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk  # noqa: E731
    vp8x = b"VP8X" + struct.pack("<I", 10) + b"\0" * 4 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
    vp8l = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", (30 - 1) | ((20 - 1) << 14))
    vp8 = b"VP8 " + struct.pack("<I", 10) + b"\0\0\0\x9d\x01\x2a" + struct.pack("<HH", 16, 12)
    sizes = [probed(tmp_path, f"{i}.webp", riff(c))[0] for i, c in enumerate((vp8x, vp8l, vp8))]
    assert [(r["container"], r["width"], r["height"]) for r in sizes] == [
        ("webp", 100, 50), ("webp", 30, 20), ("webp", 16, 12)]


def test_wav_gives_rate_channels_and_duration(tmp_path):
    row, note = probed(tmp_path, "a.wav", wav_bytes(rate=8000, channels=2, data_bytes=16000))
    assert (row["container"], row["kind"], note) == ("wav", "audio", "")
    assert fields(row) == {**EMPTY, "sample_rate": 8000, "channels": 2, "duration_seconds": 0.5}
    cut, note = probed(tmp_path, "cut.wav", wav_bytes(data_bytes=16000)[:-9000])  # the data chunk runs past the file
    assert (cut["sample_rate"], cut["duration_seconds"], note) == (8000, None, "")


def test_mp4_with_moov_after_a_64_bit_mdat_gives_every_field(tmp_path):
    row, note = probed(tmp_path, "a.mp4", mp4_bytes(width=320, height=240, rate=44100, channels=2))
    assert (row["container"], row["kind"], note) == ("mp4", "video", "")
    assert fields(row) == {"width": 320, "height": 240, "duration_seconds": 2.5, "sample_rate": 44100, "channels": 2}
    audio_only = box(b"ftyp", b"M4A \0\0\0\0") + mp4_bytes()[24:]
    row, _ = probed(tmp_path, "b.bin", audio_only)
    assert (row["container"], row["kind"]) == ("m4a", "audio")


def test_truncated_files_give_empty_fields_a_note_and_no_exception(tmp_path):
    for name, data, container in (("cut.png", png_bytes()[:14], "png"), ("cut.jpg", jpeg_bytes()[:24], "jpeg"),
                                  ("cut.mp4", mp4_bytes()[:60], "mp4"), ("cut.webm", webm_parts()[0] + b"\x18\x53", "webm")):
        row, note = probed(tmp_path, name, data)
        assert (row["container"], fields(row), row["bytes"]) == (container, EMPTY, len(data)), name
        assert note == f"{container} headers could not be read in full" and len(row["sha256"]) == 64
    row, note = probed(tmp_path, "half.mp4", mp4_bytes()[:-100])  # the moov box runs past the end of the file
    assert (row["container"], note) == ("mp4", "mp4 headers could not be read in full")
    assert all(v is None for v in fields(row).values())
    row, note = probed(tmp_path, "empty.jpg", b"")
    assert (row["container"], row["kind"], row["bytes"], fields(row), note) == ("unknown", "image", 0, EMPTY, "")
    row, _ = probed(tmp_path, "text.dat", b"hello, not media")
    assert (row["container"], row["kind"]) == ("unknown", "other")


def test_flac_and_ogg_read_their_stream_headers(tmp_path):
    packed = (44100 << 44) | (1 << 41) | (15 << 36) | 88200
    flac = b"fLaC\x80\x00\x00\x22" + b"\0" * 10 + struct.pack(">Q", packed) + b"\0" * 16
    row, _ = probed(tmp_path, "a.flac", flac)
    assert (row["container"], fields(row)) == ("flac", {**EMPTY, "sample_rate": 44100, "channels": 2, "duration_seconds": 2.0})
    page = b"OggS\0\x02" + b"\0" * 20 + b"\x01\x13"
    opus = page + b"OpusHead\x01\x02" + struct.pack("<HI", 312, 48000) + b"\0\0\0"
    vorbis = page + b"\x01vorbis" + struct.pack("<IBI", 0, 1, 22050) + b"\0" * 14
    rows = [probed(tmp_path, n, d)[0] for n, d in (("a.opus", opus), ("a.ogg", vorbis))]
    assert [(r["container"], r["kind"], r["sample_rate"], r["channels"], r["duration_seconds"]) for r in rows] == [
        ("ogg", "audio", 48000, 2, None), ("ogg", "audio", 22050, 1, None)]


def test_mp3_duration_comes_only_from_a_frame_count(tmp_path):
    header = b"\xff\xfb\x90\x64"  # MPEG-1 layer III, 44100 Hz, joint stereo
    xing = b"ID3\x04\0\0\0\0\0\x05tag!!" + header + b"\0" * 32 + b"Xing\0\0\0\x01" + struct.pack(">I", 100) + b"\0" * 400
    row, _ = probed(tmp_path, "a.mp3", xing)
    assert (row["container"], fields(row)) == (
        "mp3", {**EMPTY, "sample_rate": 44100, "channels": 2, "duration_seconds": round(100 * 1152 / 44100, 3)})
    plain, _ = probed(tmp_path, "b.mp3", header + b"\0" * 400)
    assert (plain["container"], plain["sample_rate"], plain["channels"], plain["duration_seconds"]) == ("mp3", 44100, 2, None)


def test_webm_reads_info_and_tracks_and_follows_the_seek_head(tmp_path):
    head, info, tracks = webm_parts()
    cluster = el("1F43B675", b"\0" * 8)
    row, note = probed(tmp_path, "a.webm", head + el("18538067", info + tracks + cluster))
    assert (row["container"], row["kind"], note) == ("webm", "video", "")
    assert fields(row) == {"width": 640, "height": 480, "duration_seconds": 4.5, "sample_rate": 48000, "channels": 2}
    void = el("EC", b"\0" * (1 << 20))  # pushes Info past the first 1 MiB that the probe reads
    seek = el("4DBB", el("53AB", bytes.fromhex("1549A966")) + el("53AC", (0).to_bytes(4, "big")))
    seek_head = el("114D9B74", seek)
    position = len(seek_head) + len(tracks) + len(void)
    seek_head = el("114D9B74", el("4DBB", el("53AB", bytes.fromhex("1549A966")) + el("53AC", position.to_bytes(4, "big"))))
    far, note = probed(tmp_path, "far.mkv", el("1A45DFA3", el("4282", b"matroska"))
                       + el("18538067", seek_head + tracks + void + info), with_hash=False)
    assert (far["container"], far["duration_seconds"], far["width"], far["sha256"], note) == ("matroska", 4.5, 640, None, "")
