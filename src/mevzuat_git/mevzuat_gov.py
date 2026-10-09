"""mevzuat.gov.tr: URLs and parsers for consolidated texts.

A law's page (``/mevzuat?MevzuatNo=..``) is only a shell; the text itself is served by an
iframe (``/anasayfa/MevzuatFihristDetayIframe``) as Word-exported HTML. The same content
is downloadable as ``/MevzuatMetin/{tur}.{tertip}.{no}.doc|pdf``. See docs/sources.md.

Parsers here only *read* the text; whitespace is collapsed for pattern matching, but the
legal text itself is never rewritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from selectolax.lexbor import LexborHTMLParser, LexborNode

from mevzuat_git.fetch import Fetcher, NotFound, decode_html

BASE = "https://www.mevzuat.gov.tr"
TUR_KANUN = 1
# Tertip = Düstur series. Laws before 1960-ish are in older tertips (GVK is in 4).
TERTIP_ORDER = (5, 4, 3, 2, 1)


def page_url(no: int, tur: int = TUR_KANUN, tertip: int = 5) -> str:
    return f"{BASE}/mevzuat?MevzuatNo={no}&MevzuatTur={tur}&MevzuatTertip={tertip}"


def iframe_url(no: int, tur: int = TUR_KANUN, tertip: int = 5) -> str:
    return (
        f"{BASE}/anasayfa/MevzuatFihristDetayIframe?"
        f"MevzuatTur={tur}&MevzuatNo={no}&MevzuatTertip={tertip}"
    )


def download_url(no: int, ext: str, tur: int = TUR_KANUN, tertip: int = 5) -> str:
    return f"{BASE}/MevzuatMetin/{tur}.{tertip}.{no}.{ext}"


def find_tertip(fetcher: Fetcher, no: int, tur: int = TUR_KANUN) -> int | None:
    """Return the Düstur tertip under which mevzuat.gov.tr publishes law ``no``."""
    for tertip in TERTIP_ORDER:
        try:
            fetcher.get(page_url(no, tur, tertip))
        except NotFound:
            continue
        return tertip
    return None


def fetch_text_html(fetcher: Fetcher, no: int, tur: int = TUR_KANUN,
                    tertip: int | None = None) -> tuple[int, str] | None:
    """Fetch the iframe HTML of a law. Returns ``(tertip, html)`` or None if not published."""
    if tertip is None:
        tertip = find_tertip(fetcher, no, tur)
        if tertip is None:
            return None
    try:
        r = fetcher.get(iframe_url(no, tur, tertip))
    except NotFound:
        return None
    return tertip, decode_html(r.content)


def text_fetched_on(fetcher: Fetcher, no: int, tur: int = TUR_KANUN) -> date | None:
    """The day the consolidated text was fetched: what it says holds on that day."""
    tertip = find_tertip(fetcher, no, tur)
    if tertip is None:
        return None
    r = fetcher.get(iframe_url(no, tur, tertip))
    return r.fetched_at.date() if r.fetched_at else None


# -- small text helpers -----------------------------------------------------------------

def squash(s: str) -> str:
    """Collapse whitespace (incl. nbsp) for matching. Never used to store legal text."""
    return " ".join(s.split())


DATE_RE = r"\d{1,2}\s*[./]\s*\d{1,2}\s*[./]\s*\d{4}"


def parse_date(s: str) -> date | None:
    m = re.search(r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})", s)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


# -- header -----------------------------------------------------------------------------

@dataclass
class Header:
    title: str
    number: str | None = None
    kabul_date: date | None = None
    rg_date: date | None = None
    rg_number: str | None = None


def parse_header(html: str) -> Header:
    """Read the "Kanun Numarası / Kabul Tarihi / Resmî Gazete" block at the top."""
    tree = LexborHTMLParser(html)
    paras = [squash(p.text()) for p in tree.css("p")[:30]]
    h = Header(title="")
    for t in paras:
        if t.startswith("Kanun") and (m := re.search(r"Numarası\s*:\s*(\S+)", t)):
            h.number = m.group(1)
        if m := re.search(r"Kabul Tarihi\s*:\s*(" + DATE_RE + ")", t):
            h.kabul_date = parse_date(m.group(1))
        if "Resmî Gazete" in t or "Resmi Gazete" in t:
            if m := re.search(r"Tarih\s*:\s*(" + DATE_RE + ")", t):
                h.rg_date = parse_date(m.group(1))
            if m := re.search(r"Sayı\s*:\s*(\d+(?:\s*\(\s*\d*\.?\s*Mükerrer\s*\))?)", t):
                h.rg_number = m.group(1)
    # Older layouts break "Kanun Numarası" over lines; fall back to whole-text search.
    if h.number is None or h.rg_date is None:
        full = squash(tree.body.text()) if tree.body else ""
        if h.number is None and (m := re.search(r"Kanun\s+Numarası\s*:\s*(\d+)", full)):
            h.number = m.group(1)
        if h.kabul_date is None and (m := re.search(r"Kabul\s+Tarihi\s*:\s*(" + DATE_RE + ")",
                                                     full)):
            h.kabul_date = parse_date(m.group(1))
        if h.rg_date is None and (
            m := re.search(r"Resm[îi]\s+Gazete\s*:\s*Tarih\s*:\s*(" + DATE_RE
                           + r")\s*Sayı\s*:\s*(\d+)", full)
        ):
            h.rg_date = parse_date(m.group(1))
            h.rg_number = m.group(2)
    # The title is everything before "Kanun Numarası"; it is not always inside <p>s.
    full = squash(tree.body.text()) if tree.body else ""
    title = re.split(r"Kanun\s+Numarası", full, maxsplit=1)[0]
    h.title = squash(re.sub(r"\[\d+\]", "", title))
    return h


# -- inline amendment markers -------------------------------------------------------------

# One event inside a marker such as "(Ek: 24/12/1980-2361/36 md; Değişik: 26/12/1993-3946/12 md.)"
EVENT_RE = re.compile(
    r"(?P<label>[^:;()]*?)\s*:\s*(?P<date>" + DATE_RE + r")\s*[-–]\s*"
    r"(?P<law>\d+)\s*/\s*(?P<art>[0-9A-Za-zÇĞİÖŞÜçğıöşü/\-]+?)\s*md\b\.?"
)
AYM_EVENT_RE = re.compile(
    r"(?P<label>[^:;()]*?İptal[^:;()]*?)\s*:\s*Anayasa\s+Mahkemesi.{0,4}?\s*n?in\s+"
    r"(?P<date>" + DATE_RE + r")\s+tarihli\s+ve\s+(?P<ref>E\.?\s*:.*?K\.?\s*:\s*[\d/]+)"
)
# A marker is a parenthesised group that contains at least one event.
MARKER_RE = re.compile(r"\((?:[^()]|\([^()]*\))*?(?:md\b\.?|Kararı\s+ile\.?)\s*\)")


@dataclass
class MarkerEvent:
    kind: str  # degisik | ek | mulga | yeniden_duzenleme | iptal | other
    label: str  # as written, e.g. "Ek fıkra", "Mülga ikinci cümle"
    date: date | None  # kabul tarihi of the amending law (or AYM karar tarihi)
    law: int | None  # amending law number (None for AYM)
    law_article: str | None  # article of the amending law, e.g. "36" or "81/C"
    raw: str
    aym_ref: str | None = None


def classify_label(label: str) -> str:
    low = label.casefold()
    if "iptal" in low:
        return "iptal"
    if "yeniden" in low:
        return "yeniden_duzenleme"
    if "mülga" in low:
        return "mulga"
    if "değişik" in low:
        return "degisik"
    if re.search(r"\bek\b", low):
        return "ek"
    return "other"


def parse_marker(text: str) -> list[MarkerEvent]:
    """Split one parenthesised marker into its events, in order of appearance."""
    events: list[tuple[int, MarkerEvent]] = []
    for m in EVENT_RE.finditer(text):
        label = squash(m.group("label")).lstrip("(").strip()
        events.append((m.start(), MarkerEvent(
            kind=classify_label(label),
            label=label,
            date=parse_date(m.group("date")),
            law=int(m.group("law")),
            law_article=m.group("art").strip("/-"),
            raw=squash(m.group(0)),
        )))
    for m in AYM_EVENT_RE.finditer(text):
        label = squash(m.group("label")).lstrip("(").strip()
        events.append((m.start(), MarkerEvent(
            kind="iptal",
            label=label,
            date=parse_date(m.group("date")),
            law=None,
            law_article=None,
            raw=squash(m.group(0)),
            aym_ref=squash(m.group("ref")),
        )))
    return [e for _, e in sorted(events, key=lambda x: x[0])]


# -- articles, footnotes, the yürürlük table --------------------------------------------

# "Madde 12 –", "Mükerrer Madde 20/A-", and in RG texts "Madde 19. —". ``label`` is the
# heading as written, separator included.
ARTICLE_RE = re.compile(
    r"^(?P<label>(?P<prefix>(?:Mükerrer|Mükerer|Geçici|Ek)\s+)?Madde\s+"
    r"(?P<num>\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?)\s*\.?\s*[–—-])\s*",
    re.IGNORECASE,
)


def article_id(prefix: str | None, num: str) -> str:
    """Canonical article id: "23", "mukerrer-20/C", "gecici-67", "ek-1"."""
    num = num.replace(" ", "")
    if not prefix:
        return num
    # By first letter: "GEÇİCİ".casefold() is not "geçici" (dotted İ).
    p = {"m": "mukerrer", "g": "gecici", "e": "ek"}[prefix.strip()[0].lower()]
    return f"{p}-{num}"


END_OF_MAIN_RE = re.compile(r"İŞLENEMEYEN|EK VE DEĞİŞİKLİK GETİREN MEVZUAT")


@dataclass
class Footnote:
    number: int
    text: str
    article: str | None = None  # article in which the reference mark appears


@dataclass
class TableRow:
    """A row of "... YÜRÜRLÜĞE GİRİŞ TARİHLERİNİ GÖSTERİR TABLO"."""

    amending: str  # law number, or an AYM decision description
    articles: str
    effective: str


@dataclass
class ConsolidatedText:
    header: Header
    markers: list[tuple[str | None, MarkerEvent]] = field(default_factory=list)
    footnotes: list[Footnote] = field(default_factory=list)
    table: list[TableRow] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)


def _inside(node: LexborNode, tag: str) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag == tag:
            return True
        parent = parent.parent
    return False


def _is_footnote_area(node: LexborNode) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag == "div" and (parent.attributes.get("id") or "").startswith("ftn"):
            return True
        parent = parent.parent
    return False


def parse_yururluk_table(tree: LexborHTMLParser) -> list[TableRow]:
    """Parse the effective-date table, resolving the rowspan of the law-number column."""
    table = None
    for t in tree.css("table"):
        first = squash(t.css_first("tr").text()) if t.css_first("tr") else ""
        # "Değiştiren Kanunun Numarası" (GVK), "Değiştiren Kanunun/KHK’nin veya İptal Eden
        # Kararın Numarası" (VUK)
        if re.match(r"Değiştiren Kanunun\b.*Numarası", first):
            table = t
            break
    if table is None:
        return []
    rows: list[TableRow] = []
    carry: str | None = None
    carry_left = 0
    for tr in table.css("tr")[1:]:
        cells = tr.css("td")
        texts = [squash(c.text()) for c in cells]
        if carry_left > 0 and len(texts) == 2:
            amending = carry or ""
            articles, effective = texts
            carry_left -= 1
        elif len(texts) >= 3:
            amending, articles, effective = texts[0], texts[1], " ".join(texts[2:])
            span = int(cells[0].attributes.get("rowspan") or 1)
            carry, carry_left = amending, span - 1
        else:
            continue
        rows.append(TableRow(amending=amending, articles=articles, effective=effective))
    return rows


def parse_consolidated(html: str) -> ConsolidatedText:
    tree = LexborHTMLParser(html)
    out = ConsolidatedText(header=parse_header(html))

    footnote_article: dict[int, str | None] = {}
    current: str | None = None
    in_main = True
    for p in tree.css("p"):
        if _is_footnote_area(p) or _inside(p, "table"):
            continue
        text = squash(p.text())
        if not text:
            continue
        if in_main and END_OF_MAIN_RE.search(text):
            # Appendices: provisions of amending laws that could not be merged in
            # ("işlenemeyen hükümler") and the yürürlük table. Not articles of this law.
            in_main = False
            current = None
        if in_main and (m := ARTICLE_RE.match(text)):
            current = article_id(m.group("prefix"), m.group("num"))
            out.articles.append(current)
        if not in_main:
            for a in p.css("a"):
                if m := re.match(r"#_ftn(\d+)$", a.attributes.get("href") or ""):
                    footnote_article.setdefault(int(m.group(1)), None)
            continue
        for mm in MARKER_RE.finditer(text):
            for ev in parse_marker(mm.group(0)):
                out.markers.append((current, ev))
        for a in p.css("a"):
            href = a.attributes.get("href") or ""
            if m := re.match(r"#_ftn(\d+)$", href):
                footnote_article.setdefault(int(m.group(1)), current)

    for div in tree.css("div"):
        div_id = div.attributes.get("id") or ""
        if not (m := re.fullmatch(r"ftn(\d+)", div_id)):
            continue
        n = int(m.group(1))
        text = squash(div.text())
        text = re.sub(r"^\[\d+\]\s*", "", text)
        out.footnotes.append(Footnote(number=n, text=text, article=footnote_article.get(n)))

    out.table = parse_yururluk_table(tree)
    return out
