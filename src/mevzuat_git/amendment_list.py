"""Faz 0: the list of acts that amended a law, derived from its consolidated text.

Three places in a mevzuat.gov.tr consolidated text name amending acts:

* inline markers after article/paragraph labels: ``(Değişik: 7/1/2003-4783/1 md.)``.
  The date is the amending law's *kabul* (adoption) date;
* footnotes, which carry most ibare-level changes that leave no inline marker;
* the closing table "... YÜRÜRLÜĞE GİRİŞ TARİHLERİNİ GÖSTERİR TABLO" (effective dates).

They are merged per act; Resmî Gazete date/issue are then filled in from the act's own
mevzuat.gov.tr page when it has one, otherwise from the Resmî Gazete daily index.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from mevzuat_git import mevzuat_gov as mg
from mevzuat_git import resmigazete as rg
from mevzuat_git.fetch import Fetcher, NotFound

ActKind = Literal["kanun", "khk", "cbk", "aym"]
SCHEMA_VERSION = 1


class MarkerRef(BaseModel):
    """One event of an inline marker, e.g. ``Ek fıkra: 22/7/1998-4369/26 md.``."""

    article: str | None  # canonical article id of the target law, e.g. "23", "gecici-67"
    kind: str  # degisik | ek | mulga | yeniden_duzenleme | iptal | other
    label: str  # as written: "Ek fıkra", "Mülga ikinci cümle", ...
    law_article: str | None  # article of the amending act, e.g. "26", "81/C"
    raw: str


class FootnoteRef(BaseModel):
    footnote: int
    article: str | None
    law_article: str | None
    text: str  # footnote text, whitespace collapsed


class EffectiveEntry(BaseModel):
    """A row of the yürürlük table, verbatim."""

    articles: str
    effective: str
    effective_date: date | None = None  # first date in ``effective``, if any


class RGRef(BaseModel):
    date: date
    number: str | None  # issue, e.g. "32620" or "31706 (6. Mükerrer)"
    index_url: str | None = None
    text_url: str | None = None  # the act's own page, or the day page for inline items
    anchor: str | None = None  # "#n" item on inline (pre-~2005) day pages
    source: Literal["mevzuat.gov.tr", "resmigazete.gov.tr"]


class AmendingAct(BaseModel):
    kind: ActKind
    number: str  # law/KHK number, or "E.: 2006/95, K.: 2009/144" for AYM decisions
    kabul_date: date | None = None  # adoption date (decision date for AYM)
    title: str | None = None
    rg: RGRef | None = None
    affected_articles: list[str] = Field(default_factory=list)
    markers: list[MarkerRef] = Field(default_factory=list)
    footnotes: list[FootnoteRef] = Field(default_factory=list)
    effective: list[EffectiveEntry] = Field(default_factory=list)
    seen_in: list[Literal["marker", "footnote", "table"]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.number)

    def sort_key(self) -> tuple:
        d = self.kabul_date or (self.rg.date if self.rg else None) or date.max
        n = int(self.number) if self.number.isdigit() else 0
        return (d, n, self.kind, self.number)


class AmendmentList(BaseModel):
    schema_version: int = SCHEMA_VERSION
    target_law: int
    target_title: str
    target_tertip: int
    target_rg_date: date | None
    target_rg_number: str | None
    source_url: str
    source_sha256: str
    acts: list[AmendingAct]


# -- building from the consolidated text --------------------------------------------------

KIND_FROM_WORD = {
    "kanun": "kanun",
    "kanun hükmünde kararname": "khk",
    "khk": "khk",
    "cumhurbaşkanlığı kararnamesi": "cbk",
}

FOOTNOTE_REF_RE = re.compile(
    # "tarih", "tarihli" and, in the GVK text itself, the typo "tairhli".
    r"(?:(?P<date>" + mg.DATE_RE + r")\s+ta[a-zı]{2,5}\s+ve\s+)?(?P<no>\d+)\s+[Ss]ayılı\s+"
    r"(?P<kind>Kanun\s+Hükmünde\s+Kararname|Kanun|KHK|Cumhurbaşkanlığı\s+Kararnamesi)"
    r"(?:\S*\s+(?P<art>(?:[Gg]eçici\s+|[Ee]k\s+)?\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?)"
    r"(?:\s*[’']?\s*[ıiuü]?nc[ıiuü])?\s+madde)?"
)
AYM_RE = re.compile(
    r"Anayasa\s+Mahkemesi\S*\s+(?P<date>" + mg.DATE_RE + r")\s+tarihli\s+ve\s+"
    r"(?P<ref>E\s*\.?\s*:\s*\d{4}/\d+\s*,\s*K\s*\.?\s*:\s*\d{4}/\d+)"
)


def aym_number(ref: str) -> str:
    m = re.search(r"E\s*\.?\s*:\s*(\d{4}/\d+)\s*,\s*K\s*\.?\s*:\s*(\d{4}/\d+)", ref)
    return f"E.{m.group(1)}, K.{m.group(2)}" if m else mg.squash(ref)


def _inside_quotes(text: str, pos: int) -> bool:
    before = text[:pos]
    return before.count("“") > before.count("”") or before.count('"') % 2 == 1


def footnote_refs(text: str) -> list[tuple[ActKind, str, date | None, str | None]]:
    """Amending acts named in a footnote, in order: (kind, number, date, article).

    Laws merely *mentioned* (inside a quoted ibare, or "4077 sayılı Kanuna göre") are
    skipped: a reference counts only outside quotes and when dated or followed by
    "... maddesi ile/maddesiyle".
    """
    out: list[tuple[int, tuple]] = []
    for m in FOOTNOTE_REF_RE.finditer(text):
        if _inside_quotes(text, m.start()):
            continue
        acting = re.match(r"\S*\s+(?:[^\s“”\"]+\s+){0,6}?madde\S*?(?:yle|\s+ile)\b",
                          text[m.end("kind"):])
        if not (m.group("date") or acting):
            continue
        # "193 sayılı Kanunun ..." refers to the target law itself, not an amendment.
        kind = KIND_FROM_WORD[mg.squash(m.group("kind")).casefold()]
        art = mg.squash(m.group("art")).replace(" ", "") if m.group("art") else None
        out.append((m.start(), (kind, m.group("no"),
                                mg.parse_date(m.group("date")) if m.group("date") else None,
                                art)))
    for m in AYM_RE.finditer(text):
        out.append((m.start(), ("aym", aym_number(m.group("ref")),
                                mg.parse_date(m.group("date")), None)))
    return [x for _, x in sorted(out, key=lambda t: t[0])]


def _table_act(amending: str) -> tuple[ActKind, str, str | None] | None:
    """Interpret the first column of the yürürlük table."""
    s = amending.strip()
    if m := re.fullmatch(r"(\d+)(?:\s*\((\d+)\))?", s):
        return "kanun", m.group(1), (f"tablo dipnotu ({m.group(2)})" if m.group(2) else None)
    if m := re.fullmatch(r"KHK\s*/\s*(\d+)", s):
        return "khk", m.group(1), None
    if m := AYM_RE.search(s):
        return "aym", aym_number(m.group("ref")), None
    return None


def build(target_law: int, consolidated: mg.ConsolidatedText) -> list[AmendingAct]:
    acts: dict[tuple[str, str], AmendingAct] = {}
    dates: dict[tuple[str, str], Counter[date]] = {}

    def get(kind: ActKind, number: str) -> AmendingAct:
        k = (kind, number)
        if k not in acts:
            acts[k] = AmendingAct(kind=kind, number=number)
        return acts[k]

    def vote(act: AmendingAct, d: date | None) -> None:
        if d is not None:
            dates.setdefault(act.key, Counter())[d] += 1

    def seen(act: AmendingAct, where: str) -> None:
        if where not in act.seen_in:
            act.seen_in.append(where)

    def affect(act: AmendingAct, article: str | None) -> None:
        if article and article not in act.affected_articles:
            act.affected_articles.append(article)

    for article, ev in consolidated.markers:
        if ev.kind == "iptal" and ev.law is None:
            act = get("aym", aym_number(ev.aym_ref or ""))
        else:
            act = get("kanun", str(ev.law))
        vote(act, ev.date)
        act.markers.append(MarkerRef(article=article, kind=ev.kind, label=ev.label,
                                     law_article=ev.law_article, raw=ev.raw))
        affect(act, article)
        seen(act, "marker")

    for fn in consolidated.footnotes:
        for kind, number, d, art in footnote_refs(fn.text):
            if kind == "kanun" and number == str(target_law):
                continue
            act = get(kind, number)
            vote(act, d)
            act.footnotes.append(FootnoteRef(footnote=fn.number, article=fn.article,
                                             law_article=art, text=fn.text))
            affect(act, fn.article)
            seen(act, "footnote")

    for row in consolidated.table:
        parsed = _table_act(row.amending)
        if parsed is None:
            continue
        kind, number, note = parsed
        act = get(kind, number)
        act.effective.append(EffectiveEntry(articles=row.articles, effective=row.effective,
                                            effective_date=mg.parse_date(row.effective)))
        if note and note not in act.notes:
            act.notes.append(note)
        seen(act, "table")

    # The consolidated text has occasional typos in these dates (e.g. 4842 appears as
    # both 9/4/2003 and 9/4/2004): take the most frequent one and record the rest.
    for key, counter in dates.items():
        act = acts[key]
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        act.kabul_date = ranked[0][0]
        if len(ranked) > 1:
            others = ", ".join(f"{d.isoformat()} ({n}x)" for d, n in ranked[1:])
            act.notes.append(f"other dates in consolidated text: {others}")

    return sorted(acts.values(), key=AmendingAct.sort_key)


# -- Resmî Gazete metadata and texts -----------------------------------------------------

MEVZUAT_TUR = {"kanun": 1, "khk": 4, "cbk": 19}


def enrich_from_mevzuat(fetcher: Fetcher, act: AmendingAct) -> None:
    """Use the act's own mevzuat.gov.tr page header (kabul, RG date and issue)."""
    tur = MEVZUAT_TUR.get(act.kind)
    if tur is None or not act.number.isdigit():
        return
    for tertip in (5, 4):
        got = mg.fetch_text_html(fetcher, int(act.number), tur=tur, tertip=tertip)
        if got is not None:
            break
    else:
        return
    tertip, html = got
    h = mg.parse_header(html)
    if h.number and h.number != act.number:
        act.notes.append(f"mevzuat.gov.tr header number mismatch: {h.number}")
        return
    act.title = act.title or (h.title or None)
    if act.kabul_date is None:
        act.kabul_date = h.kabul_date
    elif h.kabul_date and h.kabul_date != act.kabul_date:
        act.notes.append(
            f"kabul tarihi: consolidated text says {act.kabul_date}, "
            f"mevzuat.gov.tr page says {h.kabul_date} (used)"
        )
        act.kabul_date = h.kabul_date
    if h.rg_date:
        act.rg = RGRef(date=h.rg_date, number=h.rg_number, source="mevzuat.gov.tr")


def enrich_from_rg(fetcher: Fetcher, act: AmendingAct, max_days: int = 45) -> None:
    """Locate the act in the Resmî Gazete daily index; fills URLs (and date if unknown)."""
    if act.kind == "aym":
        return
    # Scan from the kabul date; for acts only the yürürlük table names, or whose kabul
    # date in the consolidated text is off (4710: kabul 10/11/2001 > effective 24/10/2001),
    # also scan the weeks before the earliest effective date: most acts take effect on
    # publication.
    starts = [act.kabul_date]
    eff = earliest_effective(act)
    if eff is not None and (act.kabul_date is None or eff < act.kabul_date):
        starts.append(eff - timedelta(days=max_days))
    found = None
    for i, start in enumerate(s for s in starts if s is not None):
        found = rg.locate(fetcher, act.number,
                          rg_date=act.rg.date if act.rg and i == 0 else None,
                          kabul_date=start, max_days=max_days)
        if found:
            break
    if found is None:
        act.notes.append("not found in Resmî Gazete index")
        return
    if act.rg is not None and act.rg.date != found.page.date:
        act.notes.append(f"mevzuat.gov.tr gives RG {act.rg.date} ({act.rg.number}); "
                         f"found in RG index on {found.page.date} ({found.issue}), used")
        act.rg = None
    if act.rg is None:
        act.rg = RGRef(date=found.page.date, number=found.issue, source="resmigazete.gov.tr")
    elif act.rg.number and found.issue and not act.rg.number.startswith(found.page.issue or ""):
        act.notes.append(f"RG issue mismatch: mevzuat.gov.tr {act.rg.number}, "
                         f"index {found.issue}")
    if act.kabul_date and act.rg.date < act.kabul_date:
        act.notes.append(f"RG date {act.rg.date} is before the kabul date "
                         f"{act.kabul_date} given in the consolidated text")
    act.rg.index_url = found.page.url
    act.rg.text_url = found.text_url
    act.rg.anchor = found.anchor
    if act.title is None:
        act.title = re.sub(rf"^[—–-]*\s*{re.escape(act.number)}\s*", "", found.entry.text) or None


def download_text(fetcher: Fetcher, act: AmendingAct) -> bool:
    if not (act.rg and act.rg.text_url):
        return False
    try:
        fetcher.get(act.rg.text_url)
    except NotFound:
        act.notes.append(f"RG text not found: {act.rg.text_url}")
        return False
    return True


def earliest_effective(act: AmendingAct) -> date | None:
    dates = [e.effective_date for e in act.effective if e.effective_date]
    return min(dates) if dates else None


def act_date(act: AmendingAct) -> date | None:
    """Best known date of an act, for deciding whether its RG text is fetched."""
    return act.rg.date if act.rg else (act.kabul_date or earliest_effective(act))


def build_list(fetcher: Fetcher, target_law: int, since: date = date(2000, 1, 1),
               progress=None) -> AmendmentList:
    got = mg.fetch_text_html(fetcher, target_law)
    if got is None:
        raise NotFound(f"law {target_law} not on mevzuat.gov.tr")
    tertip, html = got
    consolidated = mg.parse_consolidated(html)
    acts = build(target_law, consolidated)
    for i, act in enumerate(acts):
        if progress:
            progress(i, len(acts), act)
        enrich_from_mevzuat(fetcher, act)
        d = act_date(act)
        if d is not None and d >= since:
            enrich_from_rg(fetcher, act)
            download_text(fetcher, act)
    acts.sort(key=AmendingAct.sort_key)
    url = mg.iframe_url(target_law, tertip=tertip)
    return AmendmentList(
        target_law=target_law,
        target_title=consolidated.header.title,
        target_tertip=tertip,
        target_rg_date=consolidated.header.rg_date,
        target_rg_number=consolidated.header.rg_number,
        source_url=url,
        source_sha256=hashlib.sha256(html.encode()).hexdigest(),
        acts=acts,
    )
