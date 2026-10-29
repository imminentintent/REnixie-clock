#!/usr/bin/env python3
"""
worldline.py - a transparent, news-driven "worldline" estimator.

Pipeline (every run):
  1. fetch RSS/Atom feeds
  2. drop what we've already counted, merge paraphrases of the same story
  3. score each story: valence v in [-1, 1] and impact I in [0, 1]
  4. fold the scores into two leaky accumulators (fast ~12h, slow ~3d)
  5. compare the resulting "news climate" with its own long-run normal -> z-score
  6. map z onto a worldline value around the baseline 1.048596
  7. write data/divergence.txt (8 chars, for the clock) + data/divergence.json

Zero third-party dependencies. The optional LLM scorer needs `pip install anthropic`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

VERSION = "1.0"

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
BASE = 1.048596            # the worldline we start on and revert to
FIELD_EDGE = 1.0           # below this we call it the alpha field, above it beta
SLOPE = (BASE - FIELD_EDGE) / 2.0   # worldline change per sigma, near baseline
FIELD_CROSS_Z = -2.0       # a 2-sigma bad-news surprise reaches the field edge
TAIL_LENGTH = 2.5          # sigmas over which the alpha field decays toward 0

HL_FAST_DAYS = 0.5         # fast climate half-life (breaking events)
HL_SLOW_DAYS = 3.0         # slow climate half-life (sustained situations)
HL_REF_DAYS = 30.0         # how fast "normal" itself drifts
PRIOR_K = 2.0              # pseudo-evidence pulling the climate toward "normal"
SD_PRIOR = 0.06            # starting guess for the climate's natural spread
SD_FLOOR = 0.03            # never divide by less than this
CALIBRATION_DAYS = 7       # flagged as calibrating until this much history exists
MAX_ITEM_AGE_H = 36        # ignore feed items older than this
RECENT_KEEP_H = 48
HISTORY_KEEP = 3000
MAX_DOWNLOAD_BYTES = 3_000_000
MIN_STORY_I = 0.12         # only stories at least this impactful are logged and plotted
STORY_KEEP_DAYS = 30
MAX_STORIES = 5000

FEEDS = {  # source name -> url. Edit freely; dead feeds are skipped, not fatal.
    # world news
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Guardian": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
    "AlJazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "CBC": "https://www.cbc.ca/webfeed/rss/rss-world",
    "DW": "https://rss.dw.com/rdf/rss-en-world",
    "France24": "https://www.france24.com/en/rss",
    "NYTimes": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "ABC-AU": "https://www.abc.net.au/news/feed/2942460/rss.xml",
    "SkyNews": "https://feeds.skynews.com/feeds/rss/world.xml",
    "TimesOfIndia": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
    "TheHindu": "https://www.thehindu.com/news/international/feeder/default.rss",
    "JapanTimes": "https://www.japantimes.co.jp/feed/",
    "StraitsTimes": "https://www.straitstimes.com/news/world/rss.xml",
    "Euronews": "https://www.euronews.com/rss?level=theme&name=news",
    "CNA": "https://www.channelnewsasia.com/rssfeeds/8395986",
    "UNNews": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
    "GlobalNews": "https://globalnews.ca/world/feed/",
    "RFI": "https://www.rfi.fr/en/rss",
    "CBSNews": "https://www.cbsnews.com/latest/rss/world",
    "ABCNews": "https://abcnews.go.com/abcnews/internationalheadlines",
    # science, space, health, tech
    "NASA": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
    "Nature": "https://www.nature.com/nature.rss",
    "ScienceNews": "https://www.sciencenews.org/feed",
    "TheConversation": "https://theconversation.com/global/articles.atom",
    "ScienceDaily": "https://www.sciencedaily.com/rss/top/science.xml",
    "ScienceMag": "https://www.science.org/rss/news_current.xml",
    "NewScientist": "https://www.newscientist.com/feed/home/",
    "PhysOrg": "https://phys.org/rss-feed/",
    "ScienceAlert": "https://www.sciencealert.com/feed",
    "SpaceCom": "https://www.space.com/feeds/all",
    "ArsTechnica": "https://feeds.arstechnica.com/arstechnica/index",
    "Wired": "https://www.wired.com/feed/rss",
    "MITTechReview": "https://www.technologyreview.com/feed/",
    "TheVerge": "https://www.theverge.com/rss/index.xml",
    "BBCScience": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "GuardianScience": "https://www.theguardian.com/science/rss",
    "WHO": "https://www.who.int/rss-feeds/news-english.xml",
}

# --------------------------------------------------------------------------
# Text helpers and lexicon scorer
# --------------------------------------------------------------------------
STOP = set("""a an the and or but of to in on at for from by with as is are was were be been it its this that
these those after before over under into out up down new says say said amid about than more less not no
will would could can may might has have had do does did his her their our your you he she they we i
us who what when where why how""".split())


def stem(tok: str) -> str:
    t = tok.lower()
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    elif len(t) > 4 and t.endswith("es"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    return t


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


# word -> (valence weight, severity). Negative valence pushes toward the dystopian
# pole, positive toward openness. Severity = how much the word signals "big".
_WORDS = {
    # escalation / harm
    "war": (-1.0, .90), "invasion": (-1.0, .90), "invade": (-1.0, .90), "airstrike": (-1.0, .80),
    "missile": (-.8, .70), "bomb": (-.9, .80), "bombing": (-.9, .80), "massacre": (-1.0, .90),
    "genocide": (-1.0, .95), "coup": (-1.0, .85), "assassination": (-1.0, .85), "assassinate": (-1.0, .85),
    "terror": (-.9, .80), "terrorist": (-.9, .80), "hostage": (-.8, .70), "escalate": (-.8, .70),
    "escalation": (-.8, .70), "attack": (-.8, .70), "explosion": (-.8, .70), "blast": (-.7, .60),
    "shooting": (-.8, .60), "stabbing": (-.8, .50), "killed": (-.9, .70), "dead": (-.8, .60),
    "death": (-.7, .60), "die": (-.7, .50), "died": (-.7, .50), "injured": (-.5, .40),
    "nuclear": (-.4, .60), "riot": (-.7, .60), "unrest": (-.6, .50), "crackdown": (-.7, .50),
    "protest": (-.3, .40), "sanction": (-.5, .50), "tension": (-.4, .40), "threat": (-.4, .40),
    "condemn": (-.4, .40), "arrest": (-.3, .30), "fraud": (-.5, .40), "scandal": (-.5, .40),
    # disaster / systemic stress
    "earthquake": (-.9, .80), "tsunami": (-1.0, .85), "hurricane": (-.7, .70), "typhoon": (-.7, .70),
    "cyclone": (-.7, .70), "wildfire": (-.7, .60), "flood": (-.7, .60), "drought": (-.6, .50),
    "heatwave": (-.6, .50), "famine": (-1.0, .80), "pandemic": (-.8, .80), "epidemic": (-.8, .70),
    "outbreak": (-.7, .60), "collapse": (-.8, .60), "crisis": (-.7, .60), "recession": (-.7, .60),
    "crash": (-.7, .60), "derail": (-.7, .60), "evacuate": (-.7, .60), "blackout": (-.6, .60),
    "shortage": (-.5, .50), "layoff": (-.5, .50), "inflation": (-.3, .40), "tariff": (-.3, .45),
    "cyberattack": (-.8, .70), "ransomware": (-.7, .60), "breach": (-.5, .50), "missing": (-.4, .40),
    # resolution / cooperation / discovery
    "peace": (.8, .70), "ceasefire": (.7, .70), "truce": (.7, .60), "treaty": (.7, .60),
    "accord": (.6, .50), "agreement": (.5, .50), "deal": (.4, .40), "summit": (.3, .40),
    "talk": (.2, .30), "cooperation": (.6, .50), "cooperate": (.6, .50), "breakthrough": (.8, .70),
    "discover": (.5, .50), "discovery": (.5, .50), "cure": (.8, .70), "vaccine": (.4, .50),
    "approved": (.4, .40), "rescue": (.6, .50), "freed": (.6, .50), "recover": (.4, .40),
    "recovery": (.4, .40), "rebuild": (.5, .40), "relief": (.5, .40), "aid": (.4, .40),
    "reform": (.4, .40), "milestone": (.5, .40), "successful": (.4, .40), "launch": (.3, .40),
    "growth": (.3, .30), "renewable": (.3, .30),
}
_PHRASES = {
    "death toll": (-1.0, .80), "state of emergency": (-.8, .70), "mass shooting": (-1.0, .85),
    "peace deal": (1.0, .80), "peace talks": (.5, .50), "ceasefire holds": (.5, .60),
}
LEX = {stem(k): v for k, v in _WORDS.items()}
NEGATORS = {"no", "not", "without", "avert", "averts", "averted", "avoid", "avoids", "avoided",
            "prevent", "prevents", "prevented", "foil", "foils", "foiled", "thwart", "thwarts",
            "thwarted", "denies"}
SKIP_RE = re.compile(r"\b(football|soccer|nfl|nba|nhl|mlb|premier league|cricket|rugby|tennis|golf|"
                     r"oscars?|grammys?|celebrity|box office|movie review|film review|recipe|horoscope)\b", re.I)


def lexicon_score(title: str) -> tuple[float, float]:
    """Return (valence in [-1,1], severity in [0,1]) for one headline."""
    if SKIP_RE.search(title):
        return 0.0, 0.0
    text = " ".join(tokens(title))
    vsum, keep = 0.0, 1.0
    for phrase, (vw, sv) in _PHRASES.items():
        if phrase in text:
            vsum += vw
            keep *= 1 - sv
    toks = tokens(title)
    for i, t in enumerate(toks):
        entry = LEX.get(stem(t))
        if not entry:
            continue
        vw, sv = entry
        if any(p in NEGATORS for p in toks[max(0, i - 2):i]):
            vw = -0.5 * vw
        vsum += vw
        keep *= 1 - sv
    sev = max(0.05, 1 - keep)
    return math.tanh(vsum), sev


# --------------------------------------------------------------------------
# Optional LLM scorer (untested without an API key; falls back silently)
# --------------------------------------------------------------------------
LLM_PROMPT = """You rate news headlines for a world-state index.
For each numbered headline give:
- valence in [-1, 1]: negative = violence, disaster, instability, escalation; positive = resolution,
  cooperation, relief, discovery; 0 = routine or neutral.
- severity in [0, 1]: global significance. 0.05 routine/local, 0.3 notable regional,
  0.6 major international, 0.9+ world-historic. Sports, entertainment and lifestyle = 0.0.
Reply with ONLY a JSON array of [index, valence, severity] triples, one per headline.

"""


def llm_scores(titles: list[str]) -> list[tuple[float, float] | None]:
    out: list[tuple[float, float] | None] = [None] * len(titles)
    try:
        import anthropic  # type: ignore
        client = anthropic.Anthropic()
        model = os.environ.get("WORLDLINE_MODEL", "claude-haiku-5-5")
        for start in range(0, len(titles), 40):
            chunk = titles[start:start + 40]
            body = "\n".join(f"{i}. {t}" for i, t in enumerate(chunk))
            msg = client.messages.create(model=model, max_tokens=3000,
                                         messages=[{"role": "user", "content": LLM_PROMPT + body}])
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            m = re.search(r"\[.*\]", raw, re.S)
            if not m:
                continue
            for idx, v, s in json.loads(m.group(0)):
                if 0 <= int(idx) < len(chunk):
                    out[start + int(idx)] = (max(-1.0, min(1.0, float(v))), max(0.0, min(1.0, float(s))))
    except Exception as exc:  # network, key, parse - never fatal
        print(f"[llm scorer unavailable: {exc!r}] using lexicon", file=sys.stderr)
    return out


def score_titles(titles: list[str], mode: str) -> list[tuple[float, float]]:
    lex = [lexicon_score(t) for t in titles]
    if mode == "lexicon" or not titles:
        return lex
    llm = llm_scores(titles)
    res = []
    for a, b in zip(lex, llm):
        if b is None:
            res.append(a)
        elif mode == "llm":
            res.append(b)
        else:  # blend
            res.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return res


# --------------------------------------------------------------------------
# Feeds
# --------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(xml_bytes: bytes, source: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f = {_local(c.tag): c for c in el}
        title = (f["title"].text or "").strip() if "title" in f else ""
        if not title:
            continue
        link = ""
        if "link" in f:
            link = (f["link"].get("href") or f["link"].text or "").strip()
        when = None
        for k in ("pubDate", "published", "updated", "date"):
            if k in f:
                when = _parse_time(f[k].text)
                if when:
                    break
        items.append({"source": source, "title": re.sub(r"\s+", " ", title), "link": link,
                      "ts": (when or datetime.now(timezone.utc)).timestamp()})
    return items


def _fetch_one(pair):
    name, url = pair
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "worldline-estimator/" + VERSION})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = r.read(MAX_DOWNLOAD_BYTES)
        return parse_feed(data, name), None
    except Exception as exc:
        return [], f"{name}: {exc!r}"


def fetch_all(feeds: dict[str, str]) -> tuple[list[dict], list[str]]:
    from concurrent.futures import ThreadPoolExecutor
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for got, err in ex.map(_fetch_one, feeds.items()):
            items.extend(got)
            if err:
                errors.append(err)
    return items, errors


def item_id(it: dict) -> str:
    key = it["source"] + "|" + " ".join(tokens(it["title"]))
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# Story clustering (same story from several outlets counts once, with a boost)
# --------------------------------------------------------------------------
def _key_tokens(title: str) -> set[str]:
    return {stem(t) for t in tokens(title) if t not in STOP and len(t) > 2}


def cluster(items: list[dict]) -> list[list[int]]:
    sets = [_key_tokens(i["title"]) for i in items]
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]["source"] == items[j]["source"]:
                continue
            inter = len(sets[i] & sets[j])
            if inter >= 3 and inter / len(sets[i] | sets[j]) >= 0.3:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def impact(severity: float, n_sources: int) -> float:
    return min(1.0, severity * (1 + 0.5 * (min(n_sources, 4) - 1)))


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------
def z_to_worldline(z: float) -> float:
    """Map a z-score ("how surprising is today's news climate") to a worldline.

    z = 0           -> BASE (1.048596)
    z in [-2, +inf) -> roughly linear, saturating below 2.0 on the upside
    z < -2          -> crosses into the alpha field and decays toward 0
    """
    if z >= 0:
        cap = 2.0 - BASE
        return BASE + cap * math.tanh(SLOPE * z / cap)
    if z >= FIELD_CROSS_Z:
        return BASE + SLOPE * z
    return FIELD_EDGE * math.exp(-(abs(z) - abs(FIELD_CROSS_Z)) / TAIL_LENGTH)


def story_d(v: float, impact_: float) -> float:
    """Worldline a single story would imply if it were the whole news climate (for the plot)."""
    return z_to_worldline(3.0 * v * impact_)


def field_name(w: float) -> str:
    return "alpha" if w < FIELD_EDGE else "beta"


def fresh_state() -> dict:
    return {"t": None, "t0": None, "runs": 0, "scorer": None,
            "sw_f": 0.0, "sv_f": 0.0, "sw_s": 0.0, "sv_s": 0.0,
            "mu": -0.15, "var": SD_PRIOR ** 2, "worldline": BASE, "z": 0.0,
            "seen": {}, "recent": []}


def ingest(state: dict, scored: list[dict], now: float) -> dict:
    """Fold scored stories ({'v','I'}) into the state; returns the summary of this step."""
    dt = 0.0 if state["t"] is None else max(0.0, min(2.0, (now - state["t"]) / 86400))
    for k, hl in (("f", HL_FAST_DAYS), ("s", HL_SLOW_DAYS)):
        d = 2 ** (-dt / hl)
        state[f"sw_{k}"] *= d
        state[f"sv_{k}"] *= d
    for it in scored:
        w = it["I"] ** 2
        for k in ("f", "s"):
            state[f"sw_{k}"] += w
            state[f"sv_{k}"] += w * it["v"]
    if state["runs"] == 0:  # the first reading defines "normal": we start on the baseline
        if state["sw_s"] > 0:
            state["mu"] = state["sv_s"] / state["sw_s"]
        state["var"] = SD_PRIOR ** 2
    mu = state["mu"]
    cf = (state["sv_f"] + PRIOR_K * mu) / (state["sw_f"] + PRIOR_K)
    cs = (state["sv_s"] + PRIOR_K * mu) / (state["sw_s"] + PRIOR_K)
    c = 0.5 * (cf + cs)
    if state["t0"] is None:
        state["t0"] = now
    age_frac = min(1.0, (now - state["t0"]) / (CALIBRATION_DAYS * 86400))
    sd = max(SD_FLOOR, math.sqrt(state["var"])) * (2.0 - age_frac)  # extra caution while calibrating
    dev = c - state["mu"]
    z = dev / sd
    z_fast = (cf - state["mu"]) / sd
    # early on, "normal" is a plain running average; later it becomes a slow moving average
    beta = max(1 - 2 ** (-dt / HL_REF_DAYS), 1.0 / (state["runs"] + 1))
    state["mu"] += beta * dev
    state["var"] += beta * (dev ** 2 - state["var"])
    state["t"] = now
    state["runs"] += 1
    state["z"] = z
    state["worldline"] = z_to_worldline(z)
    return {"z_fast": z_fast, "climate_fast": cf, "climate_slow": cs, "climate": c, "z": z,
            "worldline": state["worldline"], "sd": sd}


def process(state: dict, fetched: list[dict], now: float, mode: str = "lexicon") -> dict:
    """One full update from already-fetched items. Pure except for mutating `state`."""
    if state["scorer"] not in (None, mode) and state["runs"] > 0:  # scorer changed -> new normal
        state["runs"], state["t0"] = 0, None
    state["scorer"] = mode
    fresh = [i for i in fetched if now - i["ts"] <= MAX_ITEM_AGE_H * 3600]
    seen = state["seen"]
    groups = cluster(fresh)
    to_score = []
    for g in groups:
        ids = [item_id(fresh[i]) for i in g]
        already = any(x in seen for x in ids)
        for x in ids:
            seen.setdefault(x, now)
        if already:
            continue
        n_src = len({fresh[i]["source"] for i in g})
        rep = max(g, key=lambda i: len(fresh[i]["title"]))
        to_score.append((fresh[rep], n_src))
    results = score_titles([it["title"] for it, _ in to_score], mode)
    scored = []
    for (it, n_src), (v, sev) in zip(to_score, results):
        scored.append({"title": it["title"], "source": it["source"], "link": it["link"], "ts": it["ts"],
                       "n_sources": n_src, "v": round(v, 3), "I": round(impact(sev, n_src), 3),
                       "d": round(story_d(v, impact(sev, n_src)), 6)})
    step = ingest(state, [s for s in scored if s["I"] > 0], now)
    state["recent"] = [r for r in state["recent"] + scored if now - r["ts"] <= RECENT_KEEP_H * 3600
                       and r["I"] >= MIN_STORY_I][-800:]
    state["seen"] = {k: t for k, t in seen.items() if now - t <= 7 * 86400}
    step["new_stories"] = len(scored)
    step["scored"] = scored
    return step


def story_row(r: dict) -> dict:
    d = r["d"] if "d" in r else round(story_d(r["v"], r["I"]), 6)
    return {"ts": int(r["ts"]), "title": r["title"], "source": r["source"], "link": r.get("link", ""),
            "v": r["v"], "I": r["I"], "d": d, "n_sources": r.get("n_sources", 1)}


def merge_stories(existing: list[dict], extra: list[dict], now: float) -> list[dict]:
    rows = {(x["ts"], x["title"], x["source"]): x for x in existing}
    for r in extra:
        if r["I"] >= MIN_STORY_I:
            rows.setdefault((int(r["ts"]), r["title"], r["source"]), story_row(r))
    keep = [x for x in rows.values() if now - x["ts"] <= STORY_KEEP_DAYS * 86400]
    keep.sort(key=lambda x: x["ts"])
    if len(keep) > MAX_STORIES:  # keep the whole last week, then the most important older stories
        cut = now - 7 * 86400
        recent = [x for x in keep if x["ts"] >= cut]
        older = sorted((x for x in keep if x["ts"] < cut), key=lambda x: -x["I"])
        keep = sorted(older[:max(0, MAX_STORIES - len(recent))] + recent, key=lambda x: x["ts"])
    return keep[-MAX_STORIES:]


def backfill(data_dir: Path, limit: int = 500) -> int:
    """One-off: rebuild stories.json from the `recent` lists stored in older state.json commits."""
    import subprocess
    def git(*a):
        return subprocess.run(["git", "-C", str(data_dir), *a], capture_output=True, text=True, check=True).stdout
    found = []
    for h in git("log", "--format=%H", "-n", str(limit), "--", "state.json").split():
        try:
            found += json.loads(git("show", f"{h}:state.json")).get("recent", [])
        except Exception:
            continue
    stp = data_dir / "stories.json"
    old = json.loads(stp.read_text()) if stp.exists() else []
    rows = merge_stories(old, found, datetime.now(timezone.utc).timestamp())
    _atomic_write(stp, json.dumps(rows, separators=(",", ":"), ensure_ascii=False))
    print(f"backfill: {len(rows)} stories now logged")
    return 0


def build_output(state: dict, step: dict, now: float) -> dict:
    w = state["worldline"]
    top = sorted((r for r in state["recent"] if now - r["ts"] <= 24 * 3600),
                 key=lambda r: abs(r["v"]) * r["I"] ** 2, reverse=True)[:10]
    return {
        "divergence": f"{w:.6f}",
        "field": field_name(w),
        "updated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "z": round(state["z"], 3),
        "calibrating": (now - (state["t0"] or now)) < CALIBRATION_DAYS * 86400,
        "scorer": state["scorer"],
        "new_stories": step["new_stories"],
        "climate": {"fast": round(step["climate_fast"], 4), "slow": round(step["climate_slow"], 4),
                    "normal": round(state["mu"], 4), "spread": round(step["sd"], 4)},
        "top_stories_24h": [{"title": r["title"], "source": r["source"], "link": r["link"],
                             "valence": r["v"], "impact": r["I"], "outlets": r["n_sources"]} for r in top],
        "version": VERSION,
    }


# --------------------------------------------------------------------------
# I/O and CLI
# --------------------------------------------------------------------------
def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def run(data_dir: Path, mode: str, feeds: dict[str, str]) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    sp, hp = data_dir / "state.json", data_dir / "history.json"
    state = json.loads(sp.read_text()) if sp.exists() else fresh_state()
    fetched, errors = fetch_all(feeds)
    for e in errors:
        print("feed error:", e, file=sys.stderr)
    if not fetched:
        print("no feed returned items; leaving the meter untouched", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc).timestamp()
    step = process(state, fetched, now, mode)
    out = build_output(state, step, now)
    out["sources"] = {"live": len(feeds) - len(errors), "total": len(feeds)}
    hist = json.loads(hp.read_text()) if hp.exists() else []
    hist.append({"t": out["updated_at"], "w": out["divergence"], "z": out["z"],
                 "wf": f"{z_to_worldline(step['z_fast']):.6f}"})
    stp = data_dir / "stories.json"
    stories = merge_stories(json.loads(stp.read_text()) if stp.exists() else [], state["recent"], now)
    _atomic_write(stp, json.dumps(stories, separators=(",", ":"), ensure_ascii=False))
    _atomic_write(hp, json.dumps(hist[-HISTORY_KEEP:], separators=(",", ":")))
    _atomic_write(sp, json.dumps(state, separators=(",", ":")))
    _atomic_write(data_dir / "divergence.json", json.dumps(out, indent=2, ensure_ascii=False))
    badge = {"schemaVersion": 1, "label": "worldline", "message": out["divergence"],
             "color": "orange" if out["field"] == "beta" else "red"}
    _atomic_write(data_dir / "badge.json", json.dumps(badge))
    _atomic_write(data_dir / "divergence.txt", out["divergence"])  # last: the clock reads this
    print(f"{out['divergence']}  field={out['field']}  z={out['z']}  new={out['new_stories']}"
          f"  feeds_ok={len(feeds) - len(errors)}/{len(feeds)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch feeds, update the worldline, write data/")
    r.add_argument("--data", default=os.environ.get("WORLDLINE_DATA", "data"))
    r.add_argument("--scorer", default=os.environ.get("WORLDLINE_SCORER", "lexicon"),
                   choices=["lexicon", "llm", "blend"])
    bf = sub.add_parser("backfill", help="rebuild stories.json from older state.json commits")
    bf.add_argument("--data", default=os.environ.get("WORLDLINE_DATA", "data"))
    s = sub.add_parser("score", help="score a headline with the lexicon, for debugging")
    s.add_argument("headline")
    args = ap.parse_args(argv)
    if args.cmd == "backfill":
        return backfill(Path(args.data))
    if args.cmd == "score":
        v, sev = lexicon_score(args.headline)
        print(f"valence={v:+.3f} severity={sev:.3f}")
        return 0
    return run(Path(args.data), args.scorer, FEEDS)


if __name__ == "__main__":
    sys.exit(main())
