from fake_ytdlp import asr

from gather.captions import (
    NO_MATCHING_LANGUAGE,
    NONE_OFFERED,
    TRANSLATION_ONLY,
    CaptionChoice,
    select_caption_track,
)


def manual(*langs):
    return {lang: [{"ext": "vtt", "url": f"https://x/{lang}"}] for lang in langs}


def test_manual_track_wins_over_auto():
    info = {"subtitles": manual("en"), "automatic_captions": {"en-orig": asr("en")}}
    assert select_caption_track(info).choice == CaptionChoice("en", auto=False)


def test_regional_manual_track_is_used_when_there_is_no_exact_one():
    info = {"subtitles": manual("en-US", "en-GB", "de")}
    assert select_caption_track(info).choice == CaptionChoice("en-GB", auto=False)


def test_original_auto_track_beats_a_plain_one():
    # observed on a real upload: "en" was a translation of an Arabic dub, "en-orig" the English ASR
    info = {"automatic_captions": {"en": asr("ar", tlang="en"), "en-orig": asr("en"), "ar-orig": asr("ar")}}
    assert select_caption_track(info).choice == CaptionChoice("en-orig", auto=True)


def test_regional_original_auto_track_is_found():
    info = {"automatic_captions": {"en-US-orig": asr("en-US"), "en": asr("en-US", tlang="en")}}
    assert select_caption_track(info).choice == CaptionChoice("en-US-orig", auto=True)


def test_plain_auto_track_is_used_when_it_is_not_a_translation():
    info = {"automatic_captions": {"en": asr("en")}}
    assert select_caption_track(info).choice == CaptionChoice("en", auto=True)


def test_translation_only_is_refused_with_the_original_language():
    info = {"automatic_captions": {"sr-orig": asr("sr"), "en": asr("sr", tlang="en")}}
    pick = select_caption_track(info)
    assert pick.choice is None and pick.reason == TRANSLATION_ONLY and "sr" in pick.detail


def test_no_tracks_at_all_is_none_offered():
    pick = select_caption_track({"subtitles": {}, "automatic_captions": {}})
    assert pick.choice is None and pick.reason == NONE_OFFERED


def test_stream_chat_replay_is_not_a_caption_track():
    pick = select_caption_track({"subtitles": {"live_chat": [{"ext": "json", "url": "https://x"}]}})
    assert pick.reason == NONE_OFFERED


def test_other_languages_only_is_no_matching_language():
    pick = select_caption_track({"subtitles": manual("de"), "automatic_captions": {"de-orig": asr("de")}})
    assert pick.reason == NO_MATCHING_LANGUAGE and "de" in pick.detail


def test_language_preference_order_is_honored():
    info = {"subtitles": manual("sr"), "automatic_captions": {"en-orig": asr("en")}}
    assert select_caption_track(info, ("sr", "en")).choice == CaptionChoice("sr", auto=False)
    # the language order comes first; manual-before-auto applies within one language
    assert select_caption_track(info, ("en", "sr")).choice == CaptionChoice("en-orig", auto=True)
