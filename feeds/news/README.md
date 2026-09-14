# Reuters World — Mica: consequential developments

The existing subscription URL and original Reuters article GUIDs are unchanged:

```
https://raw.githubusercontent.com/MicaLovesKPOP/micas-space/main/feeds/news/reuters-world.xml
```

## Editorial policy

This is a selective supplement, not every Reuters article filed under `/world/`.
The question is **what materially changed**, not whether a headline contains a
country, a politician, "war", "AI", or "sanctions".

Keep concrete, major developments in conflict/peace, national elections and power,
international agreements/trade restrictions, large disasters, humanitarian aid,
public health, global climate findings, national rights decisions and systemic
economic disruption. Ordinary company deals, stock-market reactions, routine
monthly figures, political comments/promises, polls, administrative extensions,
local incidents without clear wider impact, and retrospectives do not qualify.
No country is assigned an importance score or excluded by geography.

A sanctions regime imposed or lifted is different from a seven-day procedural
extension. A national election result is different from another poll. "Stocks fall
because of a war" is still a market-angle story. Conversely, `says` or `sources
say` is NOT banned: a reported fact can be important regardless of attribution.

There is **no daily quota and no filler minimum**. Quiet days may bring no new
stories; major events are not blocked because a numerical daily budget is full.
All candidates from up to 24 official child sitemaps are considered, rather than
truncating to the latest 30 before applying relevance selection.

## Duplicates and updates

- Maintain seven days of selected-story metadata in `reuters-world-state.json`;
  the RSS contains a rolling 72-hour window. Do not rebuild an unrelated top-N
  selection every hour.
- Keep each original URL as its GUID and preserve its first admitted publication
  date across later sitemap edits. Existing accepted articles are re-evaluated
  against the policy, not grandfathered in regardless of relevance.
- Suppress confidently matched repeats of the same event and development across
  runs. Matching considers event type, phase, geography, title overlap and named
  places. Ambiguous matches are kept rather than conflated.
- Different countries/events remain distinct. An election result and its later
  annulment, a ceasefire agreement and its collapse, and sanctions imposed versus
  lifted are separate developments. A sufficiently large increase in reported
  casualties can also warrant a new article.
- A change at the **same article URL** updates that existing RSS item rather than
  generating a new unread alert. A fresh URL for a material new development can
  create a new item. Reader-specific update behavior is outside this publisher.

The numerical disaster/toll thresholds and conservative text matching are
editorial heuristics, not universal measures of a tragedy's importance.

## Scope and limitations

**This is a transparent, rule-based headline filter, not an AI reading complete
articles.** Reuters' official sitemap supplies only headline, date and URL. No
article bodies are scraped, summarized or copied. No paid service, API key,
Google News hop, Reddit hop or proxy reader is introduced. Ambiguous headlines
without a clear major-development signal can be missed, and unfamiliar wording
can require new tests/rules. It also cannot recover stories absent from the
upstream `/world/` sitemap scope. It is not a guarantee of complete world coverage.

`reuters-world-debug.json` records the policy version, source errors, every keep /
reject decision, duplicate target, rejection totals and selected articles, so
mistakes can be diagnosed rather than hidden behind a score.

On a source failure, the workflow fails without publishing a replacement feed or
resetting state. A successful fetch with zero relevant stories is different:
recent accepted items remain until they age out, and noise is never used as filler.

## Reader migration

The first v2 run re-filters the previous RSS while preserving valid article IDs
and dates. Existing subscriptions need no change. **Removing an item from the
server's XML does not necessarily remove a copy already downloaded by an RSS
reader.** Old unread clutter may need to be marked read once; future updates use
the curated feed. Do not change feed URLs or manufacture new GUIDs to clear it.

## Tests and scheduling

```sh
python -m unittest discover -s feeds/news/tests -v
python feeds/news/build_reuters_world.py
```

The hourly GitHub Actions workflow runs offline regression tests before publishing
RSS, debug output and state together. Tests cover supplied example headlines,
synthetic important/noise cases, cross-run deduplication, distinct developments,
persistent timestamps, migration, corrupt state and source failure. Example
headlines are test inputs, **not independent verification of the news claims**.
The car and K-pop feeds are unaffected. Publication rebases concurrent commits
from those jobs and never force-pushes.
