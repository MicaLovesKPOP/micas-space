"""Conservative, inspectable selection of consequential world-news headlines.

This is NOT a semantic/AI reader: Reuters' public sitemap supplies titles only.
A topic word is not enough. A headline must describe a concrete development.
No paid APIs, article scraping, country importance ranking, or daily quota.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

POLICY_VERSION = 2
FEED_HOURS = 72
HISTORY_DAYS = 7


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)
                  .replace("’", "'").replace("–", "-").replace("—", "-")).strip().lower()


def has(pattern: str, value: str) -> bool:
    return re.search(pattern, value) is not None


@dataclass(frozen=True)
class Decision:
    keep: bool
    topic: str
    reason: str
    priority: int = 0


def yes(topic: str, reason: str, priority: int = 70) -> Decision:
    return Decision(True, topic, reason, priority)


def no(reason: str) -> Decision:
    return Decision(False, "", reason)


def tolls(title: str) -> dict[str, int]:
    """Context-bound casualty numbers; never mistake a year or stock price for a toll."""
    result = {"dead": 0, "missing": 0, "displaced": 0}
    kinds = {"dead": r"dead|deaths|killed|die|dies|died|fatalities",
             "missing": r"missing|unaccounted for",
             "displaced": r"displaced|evacuated|homeless"}
    for kind, words in kinds.items():
        patterns = [rf"\b([\d,]+)\s+(?:(?:people|persons|civilians|children|passengers)\s+)?(?:{words})\b",
                    rf"\b(?:{words})\s+(?:(?:at least|more than|over|nearly|about)\s+)?([\d,]+)\b"]
        if kind == "dead":
            patterns += [r"\bkill(?:s|ed|ing)?\s+(?:(?:at least|more than|over)\s+)?([\d,]+)\b",
                         r"\bdeath toll\s+(?:(?:rises|jumps|climbs|soars)\s+to\s+|of\s+|reaches\s+)?([\d,]+)\b"]
        if kind == "missing":
            patterns += [r"\bsearch(?:es|ing)? for\s+([\d,]+)\s+(?:people|passengers)\b"]
        for pattern in patterns:
            for number in re.findall(pattern, normalize(title)):
                result[kind] = max(result[kind], int(number.replace(",", "")))
    return result


# Negative gates describe the ANGLE of the story, not a banned country or subject.
FEATURE = (r"^(?:analysis|explainer|factbox|timeline|profile|column|opinion)\b|"
           r"\b\d+ years? (?:on|after)\b|\banniversary\b|\bthe reporter who\b|"
           r"\bthe reuters reporter\b")
REACTION = (r"\b(?:express(?:es)? relief|welcomes?|hails?|praises?|blasts?|slams?|"
            r"demands? justice|attributes?|condemns?|criticis(?:es|e)|criticiz(?:es|e))\b|"
            r"\b(?:vows? to|calls? for|urges? .{0,45} to|hopes? for)\b|"
            r"\b(?:documentary|insider|privately met|long for loved ones)\b")
MARKETS = (r"^(?:stocks|shares|tech stocks|global .{0,20}stocks|gold|silver|dollar|"
           r"oil prices|bitcoin|sterling|yen|euro|gulf equities|south african rand|"
           r"defensive stocks|european stocks|asian stocks|wall street|ftse|nikkei)\b|"
           r"\b(?:stocks|shares|equities|bond yields|currency)\b.{0,35}\b"
           r"(?:rise|rises|fall|falls|slide|slides|gain|gains|mixed|steady|slump|rally|lift|lifts)\b")
BUSINESS = (r"\b(?:potential bid|takeover bid|earnings|quarterly profit|passenger numbers|"
            r"joint venture|tungsten venture|chipmaking dominance|debt woes|"
            r"local currency debt index|bank loans rise|inflation holds|inflation data|"
            r"oil exports by|fees on .{0,30}payments|investor jitters)\b")
PROCEDURAL = (r"\b(?:extend|extends)\b.{0,50}\bsanctions\b.{0,50}\b(?:days|debate)\b|"
              r"\b(?:sanctions renewal|ambassador to|recommendations are|report.{0,20} due|"
              r"ahead of .{0,30}(?:meeting|election)|runoff polls|opinion poll|opinion polls|"
              r"neck-and-neck|poll shows|polls show|would win)\b")


def classify(title: str) -> Decision:
    t = normalize(title)
    if not t:
        return no("missing_headline")
    if has(FEATURE, t):
        return no("feature_or_retrospective")
    if has(PROCEDURAL, t):
        return no("preview_poll_or_administrative_step")
    if has(r"\b(?:considers?|weighs?|plans? to|threatens? to|expected to|poised to|may launch|could launch)\b", t):
        return no("proposal_or_speculation_not_implementation")
    if has(REACTION, t):
        return no("reaction_commentary_or_promise")

    # Systemic financial events are not the same as daily market coverage.
    if has(r"\b(?:sovereign default|defaults on (?:its )?(?:sovereign |foreign )?debt|"
           r"government debt default|banking crisis|freezes? (?:all |bank )?deposits|capital controls|"
           r"emergency bailout of the banking system|nationwide bank run)\b", t):
        return yes("economy.systemic", "systemic_economic_disruption", 90)
    if has(r"\b(?:global|world|wall street|stock markets|s&p 500|dow jones)\b", t) and has(
            r"\b(?:circuit breakers?|trading halted|worst crash|historic crash)\b", t):
        return yes("economy.systemic", "exceptional_market_disruption", 90)
    if has(MARKETS, t):
        return no("routine_market_angle_even_if_war_or_ai_is_mentioned")
    if has(BUSINESS, t):
        return no("company_deal_or_routine_economic_data")

    # Keep new agreements, implementation and breakdown as DIFFERENT developments.
    if has(r"\b(?:ceasefire|truce|peace (?:deal|agreement|treaty))\b", t):
        if has(r"\b(?:collapses?|breaks? down|ends?|violat(?:es|ed|ion)|breaches?|resumes? attacks)\b", t):
            return yes("peace.breakdown", "ceasefire_breakdown_or_breach", 100)
        if has(r"\b(?:takes? effect|comes? into (?:force|effect)|enters? into force|begins?|starts?)\b", t):
            return yes("peace.implementation", "ceasefire_takes_effect", 95)
        if has(r"\b(?:agree|agrees|agreed|accepts?|accepted|signs?|signed|reached|secured|approved|"
               r"ratif(?:y|ies|ied)|announc(?:e|es|ed))\b", t):
            return yes("peace.agreement", "new_peace_agreement", 95)
    if has(r"\b(?:peace|ceasefire|nuclear) talks\b", t) and has(
            r"\b(?:begin|begins|resume|resumes|collapse|collapses|breakthrough)\b", t):
        return yes("diplomacy.talks", "substantive_negotiation_development")
    if has(r"\b(?:hostages?|prisoners?)\b", t) and has(r"\b(?:released?|freed|exchange|swap)\b", t):
        return yes("peace.release", "hostage_or_prisoner_release", 80)

    if has(r"\b(?:invades?|invasion begins|declares? war|launch(?:es)? .{0,30}invasion|"
           r"launch(?:es)? .{0,35}offensive|ground offensive|martial law|coup|"
           r"mobilisation|mobilization|annex(?:es|ation)|seizes? (?:the )?capital)\b", t):
        return yes("conflict.major", "major_conflict_or_military_power_shift", 100)
    if has(r"\blaunch(?:es|ed)? (?:air |missile |military )?strikes? (?:on|against)\b", t):
        return yes("conflict.attack", "concrete_military_attack", 90)
    if has(r"\b(?:nuclear test|ballistic missile|intercontinental missile|nuclear weapon)\b", t) and has(
            r"\b(?:conducts?|launch(?:es)?|tests?|deploys?|builds?|withdraws?)\b", t):
        return yes("security.nuclear", "concrete_nuclear_or_strategic_missile_development", 90)
    if has(r"\b(?:strikes?|attacks?|missiles?|bombing)\b", t) and has(
            r"\b(?:nuclear (?:plant|site|facility)|cross-border|new front|first time|"
            r"oil terminal|refinery|power grid|escalation|retaliation)\b", t):
        return yes("conflict.escalation", "attack_with_strategic_or_escalation_consequences", 90)

    # Subnational contests and poll fluctuations are not automatic world headlines.
    election = has(r"\b(?:election|elections|presidential vote|parliamentary vote|referendum)\b", t)
    local = has(r"\b(?:state election|regional election|local election|mayoral|municipal|by-election)\b", t)
    if election and not local:
        if has(r"\b(?:annulled|annuls?|overturned|overturns?|invalidates?|invalidated)\b", t):
            return yes("election.annulment", "election_result_invalidated", 100)
        if has(r"\b(?:wins?|won|victory|defeats?|loses?|lost|majority|ahead|takes? power|"
               r"concedes?|conceded|results?|overturned|annulled)\b", t):
            return yes("election.result", "national_election_result_or_material_count", 90)
        if has(r"\b(?:polls open|voting begins|begins voting|goes to the polls)\b", t):
            return yes("election.vote", "national_voting_begins", 65)
    if has(r"\b(?:forms?|agrees? to form) (?:a |the )?(?:new |coalition )?government\b", t):
        return yes("power.formation", "new_national_government", 85)
    if has(r"\b(?:president|prime minister|government|ruling coalition)\b", t) and has(
            r"\b(?:resigns?|resigned|ousted|overthrown|impeached|assassinated|dies|"
            r"collapses?|loses? .{0,20}confidence|no-confidence vote|forms? .{0,20}government)\b", t):
        return yes("power.change", "change_in_national_power", 95)
    if has(r"\b(?:opposition leader|presidential candidate)\b", t) and has(
            r"\b(?:jailed|arrested|assassinated|barred from)\b", t):
        return yes("rights.political", "major_political_repression", 85)

    if has(r"\b(?:sanctions?|embargo|tariffs?|export (?:ban|curbs|controls|restrictions))\b", t) and has(
            r"\b(?:imposes?|introduces?|approves?|lifts?|removes?|bans?|unveils?|agrees?)\b", t):
        phase = "lift" if has(r"\b(?:lifts?|removes?)\b", t) else "impose"
        return yes("policy.trade." + phase, "new_sanctions_or_trade_policy_not_routine_renewal", 80)
    if has(r"\b(?:treaty|defence pact|defense pact|trade agreement|trade deal|"
           r"recognis(?:es|e) .{0,20}state|recogniz(?:es|e) .{0,20}state)\b", t) and has(
            r"\b(?:signs?|ratif(?:ies|y)|withdraws?|agrees?|approves?|recognis(?:es|e)|recogniz(?:es|e))\b", t):
        return yes("diplomacy.agreement", "international_agreement_or_recognition", 80)
    if has(r"\b(?:cuts? diplomatic ties|severs? ties|expels? .{0,25}diplomats|"
           r"closes? .{0,25}embass(?:y|ies)|quits? nato|joins? nato)\b", t):
        return yes("diplomacy.rupture", "material_diplomatic_change", 85)

    toll = tolls(t)
    if toll["dead"] >= 20 or toll["missing"] >= 50 or toll["displaced"] >= 50000:
        return yes("disaster.toll", "large_reported_human_impact", 90)
    if has(r"\b(?:dozens|scores|hundreds|thousands)\b.{0,25}\b(?:dead|killed|missing|die)\b|"
           r"\b(?:kills?|killed)\b.{0,15}\b(?:dozens|scores|hundreds|thousands)\b", t):
        return yes("disaster.toll", "large_reported_human_impact", 90)
    if has(r"\b(?:earthquake|quake|tsunami|hurricane|cyclone|typhoon|floods?|wildfires?|volcano)\b", t) and has(
            r"\b(?:mass evacuations?|evacuates? thousands|category [45]|major tsunami|"
            r"tsunami warning|state of emergency|national emergency)\b|"
            r"\b(?:magnitude[- ]?|magnitude of )?[789]\.\d[- ]magnitude\b|"
            r"\bmagnitude[- ]?[789]\.\d\b", t):
        return yes("disaster.warning", "major_disaster_or_serious_emergency_warning", 90)
    if has(r"\b(?:famine|mass starvation|food crisis)\b", t) and has(
            r"\b(?:declared|declares?|confirmed|spreads?|millions|aid|hunger|starvation|risk)\b", t):
        return yes("humanitarian.food", "major_humanitarian_development", 90)
    if has(r"\b(?:world food programme|wfp|un aid)\b", t) and has(
            r"\b(?:funding .{0,25}(?:plummets|cuts|halts)|halts? aid|suspends? aid|"
            r"millions .{0,25}hungry)\b", t):
        return yes("humanitarian.food", "material_threat_to_humanitarian_relief", 85)
    if has(r"\b(?:who|world health organi[sz]ation)\b", t) and has(
            r"\b(?:declares?|ends?|warns?)\b.{0,60}\b(?:emergency|pandemic|outbreak)\b", t):
        return yes("health.emergency", "international_public_health_development", 95)
    if has(r"\b(?:outbreak|virus|disease)\b", t) and has(
            r"\b(?:spreads? to .{0,25}countries|global emergency|first human transmission|"
            r"human-to-human transmission)\b", t):
        return yes("health.spread", "significant_infectious_disease_development", 85)
    if has(r"\b(?:global|world|un |international)\b", t) and has(
            r"\b(?:hottest year|hottest month|climate tipping point|climate treaty|"
            r"emissions treaty|ozone recovery)\b", t):
        return yes("climate.global", "major_global_climate_finding_or_agreement", 80)
    if has(r"\b(?:nationwide|across the country|national|millions)\b", t) and has(
            r"\b(?:blackout|power outage|internet shutdown|general strike|mass protests|"
            r"protests spread|bans? .{0,25}opposition|suspends? .{0,25}constitution)\b", t):
        return yes("society.national", "national_scale_disruption_or_rights_change", 85)
    if has(r"\b(?:parliament|supreme court|government)\b", t) and has(
            r"\b(?:legalis(?:es|e)|legaliz(?:es|e)|decriminalis(?:es|e)|decriminaliz(?:es|e)|"
            r"abolishes?|bans?|overturns?)\b", t) and has(
            r"\b(?:same-sex marriage|abortion|death penalty|opposition part(?:y|ies)|"
            r"press freedom|women's .{0,20}rights)\b", t):
        return yes("rights.law", "major_national_rights_decision", 80)
    return no("no_clear_major_development_in_headline")


# Used ONLY for conservative duplicate detection, never for editorial admission.
# Unknown countries still qualify; they simply receive stricter text matching.
PLACE_GROUPS = (
    "sweden|swedish", "norway|norwegian", "denmark|danish", "finland|finnish",
    "germany|german", "france|french", "spain|spanish", "portugal|portuguese",
    "italy|italian", "netherlands|dutch", "belgium|belgian", "poland|polish",
    "romania|romanian", "hungary|hungarian", "ukraine|ukrainian", "russia|russian",
    "britain|british|united kingdom|uk", "united states|us|u.s.|american",
    "china|chinese", "japan|japanese", "north korea|north korean", "south korea|south korean",
    "taiwan|taiwanese", "india|indian", "pakistan|pakistani", "bangladesh|bangladeshi",
    "indonesia|indonesian", "philippines|philippine|filipino", "myanmar|burmese",
    "thailand|thai", "vietnam|vietnamese", "australia|australian", "new zealand",
    "brazil|brazilian", "argentina|argentine", "colombia|colombian", "mexico|mexican",
    "canada|canadian", "venezuela|venezuelan", "peru|peruvian", "chile|chilean",
    "israel|israeli", "gaza", "lebanon|lebanese", "iran|iranian", "iraq|iraqi",
    "syria|syrian", "yemen|yemeni", "saudi arabia|saudi", "turkey|turkish",
    "egypt|egyptian", "sudan|sudanese", "south sudan|south sudanese",
    "ethiopia|ethiopian", "kenya|kenyan", "somalia|somali", "nigeria|nigerian",
    "south africa|south african", "congo|congolese", "rwanda|rwandan",
    "afghanistan|afghan", "nepal|nepalese", "sri lanka|sri lankan",
)
ALIASES = {alias: group.split("|")[0] for group in PLACE_GROUPS for alias in group.split("|")}
PLACE_RE = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True)) + r")(?!\w)")
STOP = set("a an the to of in on at for with and or as after before from amid over under by its his her "
           "says say said report reports new more than at least death toll rises rise climbs kills killed "
           "dead people crisis latest government president prime minister".split())


def places(title: str) -> set[str]:
    return {ALIASES[m.group()] for m in PLACE_RE.finditer(normalize(title))}


def tokens(title: str) -> set[str]:
    t = PLACE_RE.sub(lambda m: ALIASES[m.group()], normalize(title))
    return {w for w in re.findall(r"[a-z]+", t) if len(w) > 2 and w not in STOP}


def material_toll_update(old: str, new: str) -> bool:
    a, b = tolls(old), tolls(new)
    return any(b[k] >= a[k] * 1.5 and b[k] - a[k] >= delta
               for k, delta in (("dead", 20), ("missing", 50), ("displaced", 50000)))


def is_duplicate(a: dict, b: dict) -> bool:
    """Same event + phase, not just the same subject, region or politician.

    a is the candidate; b is an already accepted entry. Ambiguous matches are
    retained rather than silently suppressing a possibly different emergency.
    """
    if a["url"] == b["url"]:
        return True
    if a["topic"] != b["topic"]:
        return False
    if abs(a["published_dt"] - b["published_dt"]) > timedelta(hours=48):
        return False
    if material_toll_update(b["title"], a["title"]):
        return False
    ta, tb = normalize(a["title"]), normalize(b["title"])
    if ta == tb:
        return True
    pa, pb = places(ta), places(tb)
    if pa != pb:
        return False
    if not pa:
        # Unknown geography: exact titles only. Similar wording in two different
        # countries must never be mistaken for the same event.
        return False
    if a["topic"] == "election.result":
        def kind(t):
            return next((k for k in ("presidential", "parliamentary", "referendum") if k in t), "")
        if kind(ta) and kind(tb) and kind(ta) != kind(tb):
            return False
        return True
    def extra_names(title):
        generic = {"at", "major", "deadly", "severe", "new", "massive", "death", "floods",
                   "earthquake", "hurricane", "president", "government", "military"}
        return {w.lower() for w in re.findall(r"\b[A-Z][a-z]{2,}\b", title)
                if w.lower() not in ALIASES and w.lower() not in generic}
    if extra_names(a["title"]) != extra_names(b["title"]):
        return False
    aa, bb = tokens(ta), tokens(tb)
    shared = len(aa & bb)
    # Requiring matched places and substantial title overlap avoids grouping all
    # events in a war, all disasters in a country, or different countries together.
    if pa and shared >= 4 and shared / max(1, len(aa | bb)) >= 0.55:
        return True
    return SequenceMatcher(None, ta, tb).ratio() >= 0.9


def select(stories: list[dict], previous: list[dict], now: datetime) -> tuple[list[dict], list[dict], list[dict]]:
    """Return RSS entries, bounded persistent history, and an auditable decision log.

    Existing GUIDs/publication dates survive edits. Historical admissions are not
    replaced by a fresh top-N selection each hour. There is no daily quota to hide
    a major event on a busy day and no minimum to fill with unimportant stories.
    """
    cutoff = now - timedelta(days=HISTORY_DAYS)
    old = {s["url"]: dict(s) for s in previous if cutoff <= s["published_dt"] <= now}
    candidates = {s["url"]: dict(s) for s in stories}
    audit: list[dict] = []
    history: list[dict] = []
    for url, saved in sorted(old.items(), key=lambda pair: pair[1]["published_dt"]):
        fresh = candidates.pop(url, None)
        candidate = dict(fresh or saved)
        candidate["published_dt"] = saved["published_dt"]
        decision = classify(candidate["title"])
        if decision.keep:
            candidate.update(topic=decision.topic, reason=decision.reason, priority=decision.priority)
            duplicate = next((s for s in history if is_duplicate(candidate, s)), None)
            if not duplicate:
                history.append(candidate)
            audit.append({"title": candidate["title"], "url": url, "kept": duplicate is None,
                          "reason": "same_event_and_development" if duplicate else "existing_guid_maintained",
                          "topic": decision.topic,
                          **({"duplicate_of": duplicate["url"]} if duplicate else {})})
        else:
            audit.append({"title": candidate["title"], "url": url, "kept": False,
                          "reason": decision.reason, "topic": ""})

    eligible: list[dict] = []
    for candidate in candidates.values():
        dt = candidate.get("published_dt")
        decision = classify(candidate["title"])
        if not isinstance(dt, datetime):
            decision = no("missing_or_invalid_publication_date")
        elif dt > now + timedelta(minutes=10):
            decision = no("future_publication_date")
        elif dt < now - timedelta(hours=FEED_HOURS):
            decision = no("outside_recency_window")
        if not decision.keep:
            audit.append({"title": candidate["title"], "url": candidate["url"], "kept": False,
                          "reason": decision.reason, "topic": decision.topic})
            continue
        candidate.update(topic=decision.topic, reason=decision.reason, priority=decision.priority)
        eligible.append(candidate)

    # In a new batch prefer the strongest, most recent development. Existing
    # admissions above take precedence so headlines do not churn between polls.
    eligible.sort(key=lambda s: (s["priority"], s["published_dt"], s["url"]), reverse=True)
    for candidate in eligible:
        duplicate = next((s for s in history if is_duplicate(candidate, s)), None)
        audit.append({"title": candidate["title"], "url": candidate["url"],
                      "kept": duplicate is None, "topic": candidate["topic"],
                      "reason": "same_event_and_development" if duplicate else candidate["reason"],
                      **({"duplicate_of": duplicate["url"]} if duplicate else {})})
        if not duplicate:
            history.append(candidate)

    history.sort(key=lambda s: (s["published_dt"], s["url"]), reverse=True)
    current = [s for s in history if s["published_dt"] >= now - timedelta(hours=FEED_HOURS)]
    return current, history, audit
