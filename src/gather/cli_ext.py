"""The subcommands that live in their own modules, registered in one place for ``gather.cli``."""

from __future__ import annotations

from collections.abc import Callable


def add_extension_parsers(sub, add_common: Callable) -> None:
    from gather.ledger_cmd import add_ledger_parser
    from gather.reddit_cmd import add_reddit_parser
    from gather.report_cmd import add_report_parsers
    from gather.video_cmd import add_channel_parser
    from gather.youtube_cmd import add_video_parsers

    add_video_parsers(sub, add_common)
    add_channel_parser(sub)
    add_reddit_parser(sub, add_common)
    add_report_parsers(sub, add_common)
    add_ledger_parser(sub)
