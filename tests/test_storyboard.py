"""Storyboard planning and the per-host rate limit: which frames are chosen and where they sit,
the cap on sprite images, and request spacing on a fake clock. No network, no image library."""

from gather.pacing import HostLimiter
from gather.storyboard import best_level, plan_frames, storyboard_levels
from gather.video_bundle_cmd import comment_args


def sb(fid, width, height, rows, columns, fragments, *, fps=0.5, last=None):
    """A storyboard format the way yt-dlp lists one: every sprite image full but the last."""
    per = rows * columns
    frags = [{"url": f"https://i.ytimg.com/sb/vid/{fid}/M{i}.jpg?sigh=x", "duration": per / fps} for i in range(fragments)]
    if last is not None:
        frags[-1]["duration"] = str(last / fps)  # yt-dlp's early info carries durations as text
    return {"format_id": fid, "format_note": "storyboard", "ext": "mhtml", "width": width, "height": height,
            "fps": fps, "rows": rows, "columns": columns, "fragments": frags}


def info(*formats, duration=234):
    return {"id": "vid", "duration": duration, "formats": [{"format_id": "18", "url": "https://x/v.mp4"}, *formats]}


def test_the_level_with_the_largest_thumbnails_is_chosen_and_its_frames_are_counted():
    doc = info(sb("sb3", 48, 27, 10, 10, 1), sb("sb1", 160, 90, 5, 5, 5, last=19), sb("sb0", 320, 180, 3, 3, 14, last=2))
    assert [lv.format_id for lv in storyboard_levels(doc)] == ["sb0", "sb1", "sb3"]
    level = best_level(doc)
    assert (level.width, level.height, level.per) == (320, 180, 9)
    assert level.total == 13 * 9 + 2, "thirteen full sprite images and two frames on the last"
    assert level.interval == 2.0
    assert len(level.urls) == 14


def test_a_video_with_no_storyboard_has_no_level():
    assert best_level(info()) is None
    assert best_level({"formats": [{"format_id": "sb0", "format_note": "storyboard", "width": 0, "fragments": []}]}) is None


def test_ninety_six_frames_are_spread_evenly_with_their_times_and_places():
    level = best_level(info(sb("sb0", 320, 180, 3, 3, 14, last=2)))
    plan = plan_frames(level)
    assert len(plan) == 96
    assert [f.index for f in plan] == sorted({f.index for f in plan}), "in time order, no frame twice"
    assert plan[0].index == 0 and plan[-1].index == 118
    gaps = {b.index - a.index for a, b in zip(plan, plan[1:])}
    assert gaps <= {1, 2}, "even: neighbours are one or two thumbnails apart"
    for f in plan:
        assert f.time == f.index * 2.0
        assert f.fragment * 9 + f.row * 3 + f.column == f.index and f.row < 3 and f.column < 3


def test_a_short_storyboard_gives_every_frame_it_has():
    level = best_level(info(sb("sb0", 320, 180, 3, 3, 2, last=4), duration=26))
    assert [f.index for f in plan_frames(level)] == list(range(13))


def test_a_long_video_takes_fewer_frames_so_it_reads_no_more_than_24_sprite_images():
    level = best_level(info(sb("sb0", 320, 180, 3, 3, 120, fps=0.1), duration=10800))
    plan = plan_frames(level)
    assert len(plan) == 24 and len({f.fragment for f in plan}) <= 24
    assert plan[0].time < 450 and plan[-1].time > 10350, "the first and last frames sit near the ends"
    mid = best_level(info(sb("sb0", 320, 180, 3, 3, 21, fps=0.1), duration=1890))
    assert len(plan_frames(mid)) == 96 and len({f.fragment for f in plan_frames(mid)}) == 21


class Clock:
    def __init__(self):
        self.now, self.slept = 100.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 6))
        self.now += seconds


def test_requests_to_one_host_are_spaced_and_another_host_does_not_wait():
    clock = Clock()
    limiter = HostLimiter(1.0, clock=clock, sleep=clock.sleep)
    assert limiter.wait("https://i.ytimg.com/sb/a/M0.jpg") == 0, "the first request starts at once"
    assert limiter.wait("https://i.ytimg.com/sb/a/M1.jpg") == 1.0
    assert limiter.wait("https://www.youtube.com/api/timedtext") == 0, "a different host owes nothing"
    clock.now += 0.4  # the response took 0.4 s: only the rest of the second is owed
    assert round(limiter.wait("https://I.YTIMG.com/sb/a/M2.jpg"), 6) == 0.6
    clock.now += 5
    assert limiter.wait("https://i.ytimg.com/sb/a/M3.jpg") == 0, "a slow caller never sleeps"
    assert clock.slept == [1.0, 0.6]


def test_a_hold_pushes_one_host_out_and_spacing_cannot_be_negative():
    clock = Clock()
    limiter = HostLimiter(1.0, clock=clock, sleep=clock.sleep)
    limiter.hold("https://i.ytimg.com/x", 30)
    assert limiter.wait("https://i.ytimg.com/y") == 30
    assert limiter.wait("https://example.org/") == 0
    try:
        HostLimiter(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("a negative spacing must be refused")


def test_fast_comment_arguments_cap_replies_and_the_default_keeps_every_reply():
    assert comment_args(600, None, fast=False) == "youtube:max_comments=600,all,all,all;comment_sort=top"
    assert comment_args(300, None, fast=True) == "youtube:max_comments=300,all,30,5;comment_sort=top"
    assert comment_args(300, 0, fast=True) == "youtube:max_comments=300,all,0,0;comment_sort=top"
    assert comment_args(300, 40, fast=False) == "youtube:max_comments=300,all,40,5;comment_sort=top"
