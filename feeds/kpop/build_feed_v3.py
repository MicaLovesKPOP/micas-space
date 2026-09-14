#!/usr/bin/env python3
"""Small final overrides for the v2 K-pop changelog builder."""

from __future__ import annotations

import re

import build_feed_v2 as base

# Generic event words must never act as the 'shared entity' when deciding that
# two articles are duplicates. The previous pass correctly merged same-artist
# stories, but could also merge two unrelated artists whose titles both said
# things like "digital single", "solo comeback" or "hiatus".
base.DEDUP_STOPWORDS.update(
    {
        "hiatus", "indefinite", "health", "related", "take", "takes", "taking",
        "drop", "drops", "dropped", "digital", "solo", "mv", "watch", "video",
        "studio", "full", "length", "track", "tracks", "song", "songs", "music",
        "first", "second", "third", "fourth", "fifth", "1st", "2nd", "3rd", "4th",
        "5th", "mini", "latest", "upcoming", "part", "today", "following",
    }
)

_GENERIC_UPPER = {
    "THE", "NEW", "UPDATE", "WATCH", "MV", "EP", "CEO", "KPOP", "K", "POP",
}


def _uppercase_kpop_hint(title: str) -> bool:
    """Group names are often rendered in all caps (THE BOYZ, IVE, TXT, BAE173).

    This is only a supporting signal for the mixed Soompi Celeb feed; it is not
    used for event classification itself.
    """
    tokens = re.findall(r"\b[A-Z][A-Z0-9&'-]{1,}\b", base.normalize(title))
    return any(token not in _GENERIC_UPPER for token in tokens)


def soompi_celeb_is_music(title: str, summary: str) -> bool:
    title_l = base.lower(title)
    lead = f" {base.lower(summary[:240])} "

    if "acting debut" in title_l:
        return False

    actor_signal = any(
        term in lead
        for term in (" actor ", " actress ", " k-drama ", " drama ", " film ", " movie ")
    )
    music_signal = any(
        term in lead
        for term in (
            " k-pop ", " kpop ", " singer ", " idol ", " rapper ", " soloist ",
            " girl group ", " boy group ", " group member ", " member of ", " band ",
        )
    )
    title_group_signal = _uppercase_kpop_hint(title)

    # Obvious actors/actresses stay out unless the same lead clearly establishes
    # that the person is also being covered as a music artist/idol.
    if actor_signal and not (music_signal or title_group_signal):
        return False

    # Contract/agency posts in Soompi Celeb are a common source of actor noise.
    # Require some positive music identity instead of accepting every celebrity
    # who happens to renew a management contract.
    contractish = any(
        term in title_l
        for term in ("contract", "agency", "parts ways", "signs with", "signed with")
    )
    if contractish and not (music_signal or title_group_signal):
        return False

    return True


base.soompi_celeb_is_music = soompi_celeb_is_music


if __name__ == "__main__":
    raise SystemExit(base.main())
