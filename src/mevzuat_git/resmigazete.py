"""resmigazete.gov.tr: daily index pages and locating a law's text.

The HTML archive lives at ``/eskiler/YYYY/MM/YYYYMMDD.htm``; mükerrer (extra) issues of
the same day are ``YYYYMMDDM1.htm``, ``M2`` ... and are linked from the main index. Until
about 2005 the laws are inline in the index page (links are ``#1``, ``#2`` anchors);
later each item is its own file (``YYYYMMDD-1.htm``, sometimes ``.pdf``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from mevzuat_git.fetch import Fetcher, NotFound, decode_html
from mevzuat_git.mevzuat_gov import squash

BASE = "https://www.resmigazete.gov.tr"


def index_url(d: date, mukerrer: int = 0) -> str:
    suffix = f"M{mukerrer}" if mukerrer else ""
    return f"{BASE}/eskiler/{d:%Y}/{d:%m}/{d:%Y%m%d}{suffix}.htm"


@dataclass
class IndexEntry:
    href: str  # absolute URL; may carry a "#n" fragment for inline items
    text: str


@dataclass
class IndexPage:
    url: str
    date: date
    mukerrer: int
    issue: str | None  # Resmî Gazete sayısı
    entries: list[IndexEntry]
    mukerrer_urls: list[str]
    declared_laws: list[str] = field(default_factory=list)  # "Kanun No. 5035" in the body


def _https(url: str) -> str:
    return re.sub(r"^http://", "https://", url)


def parse_index(html: str, url: str, d: date, mukerrer: int = 0) -> IndexPage:
    tree = LexborHTMLParser(html)
    body = squash(tree.body.text()) if tree.body else ""
    issue = None
    head = body[:1000]  # the masthead; inline law texts below may cite other issues
    # Newer pages: "31706 Sayılı Resmî Gazete"; older: "Sayı : 24988". Issue numbers are
    # five digits, which keeps "Sayı: 2021/..." of individual items from matching.
    m = re.search(r"\b(\d{5})\s+Sayılı\s+Resm[îi]\s+Gazete", head, re.IGNORECASE) \
        or re.search(r"Sayı\s*:\s*(\d{5})\b", head)
    if m:
        issue = m.group(1)
    entries: list[IndexEntry] = []
    muk: list[str] = []
    seen_muk: set[str] = set()
    for a in tree.css("a"):
        href = a.attributes.get("href")
        if not href:
            continue
        text = squash(a.text())
        absolute = _https(urljoin(url, href))
        if re.search(r"/\d{8}M\d+\.htm$", absolute):
            if absolute not in seen_muk:
                seen_muk.add(absolute)
                muk.append(absolute)
            continue
        if not text:
            continue
        entries.append(IndexEntry(href=absolute, text=text))
    # Single-item mükerrer issues (e.g. 2/1/2004 M1) print the law with no index at all.
    declared = re.findall(r"Kanun\s+No\s*\.?\s*:?\s*(\d+)", body)
    return IndexPage(url=url, date=d, mukerrer=mukerrer, issue=issue, entries=entries,
                     mukerrer_urls=muk, declared_laws=declared)


def fetch_index(fetcher: Fetcher, d: date, mukerrer: int = 0) -> IndexPage | None:
    url = index_url(d, mukerrer)
    try:
        r = fetcher.get(url)
    except NotFound:
        return None
    return parse_index(decode_html(r.content), url, d, mukerrer)


def fetch_issue(fetcher: Fetcher, d: date, probe_mukerrer: bool = False) -> list[IndexPage]:
    """The main index of a day plus every mükerrer index it links to.

    Older main indexes (e.g. 2/1/2004) do not link their mükerrer issues; with
    ``probe_mukerrer`` M1, M2, ... are requested until one is missing.
    """
    main = fetch_index(fetcher, d)
    if main is None:
        return []
    pages = [main]
    for u in main.mukerrer_urls:
        n = int(re.search(r"M(\d+)\.htm$", u).group(1))
        if p := fetch_index(fetcher, d, n):
            pages.append(p)
    if probe_mukerrer and not main.mukerrer_urls:
        n = 1
        while (p := fetch_index(fetcher, d, n)) is not None:
            pages.append(p)
            n += 1
    return pages


def entry_matches(entry: IndexEntry, number: str) -> bool:
    """Does an index line announce act ``number``? Lines start with the number:
    "7524   Vergi Kanunları ile ..." (sometimes after a dash or a "KHK-" prefix)."""
    return re.match(rf"^[—–-]*\s*(?:KHK\s*[-/]?\s*)?{re.escape(number)}(?!\d|/)", entry.text) \
        is not None


@dataclass
class Located:
    page: IndexPage
    entry: IndexEntry

    @property
    def text_url(self) -> str:
        return self.entry.href.split("#", 1)[0]

    @property
    def anchor(self) -> str | None:
        return self.entry.href.split("#", 1)[1] if "#" in self.entry.href else None

    @property
    def issue(self) -> str | None:
        if self.page.issue and self.page.mukerrer:
            return f"{self.page.issue} ({self.page.mukerrer}. Mükerrer)" \
                if self.page.mukerrer > 1 else f"{self.page.issue} (Mükerrer)"
        return self.page.issue


def locate_on(fetcher: Fetcher, d: date, number: str,
              probe_mukerrer: bool = False) -> Located | None:
    for page in fetch_issue(fetcher, d, probe_mukerrer):
        for e in page.entries:
            if entry_matches(e, number):
                return Located(page, e)
        index_less = all(e.text == "Sayfa Başı" for e in page.entries)
        if index_less and number in page.declared_laws:
            return Located(page, IndexEntry(href=page.url, text=number))
    return None


def locate(fetcher: Fetcher, number: str, rg_date: date | None = None,
           kabul_date: date | None = None, max_days: int = 45) -> Located | None:
    """Find the index entry for act ``number``.

    With a known RG date that issue is checked first (mükerrers included). Otherwise, or
    if the date turns out wrong (mevzuat.gov.tr gives 16/5/2012 for 6322, published
    15/6/2012), days are scanned forward from the kabul (adoption) date, since
    publication follows adoption within weeks. Unlinked mükerrer issues are probed only
    in a second pass, as that doubles the number of requests.
    """
    if rg_date is not None:
        for probe in (False, True):
            if found := locate_on(fetcher, rg_date, number, probe):
                return found
    if kabul_date is None:
        return None
    days = [kabul_date + timedelta(days=i) for i in range(max_days + 1)]
    for probe in (False, True):
        for d in days:
            if found := locate_on(fetcher, d, number, probe):
                return found
    return None


# "— Anayasa Mahkemesinin E: 2025/219, K: 2026/43 Sayılı Kararı", "E. 2010/93, K: 2012/20"
_DECISION_RE = re.compile(r"\bE\s*[.:]*\s*(\d{4}/\d+)\s*[,;]?\s*K\s*[.:]*\s*(\d{4}/\d+)")


def decision_matches(entry: IndexEntry, esas: str, karar: str) -> bool:
    """Does an index line announce the Anayasa Mahkemesi decision E.``esas``, K.``karar``?"""
    m = _DECISION_RE.search(entry.text)
    return bool(m and "Anayasa" in entry.text and m.groups() == (esas, karar))


def locate_decision(fetcher: Fetcher, esas: str, karar: str,
                    days: list[date]) -> Located | None:
    """Find an Anayasa Mahkemesi decision in the indexes of ``days``, in that order. A
    decision is published months after it is made (E.2010/93, K.2012/20 of 9/2/2012 in
    the RG of 26/7/2013)."""
    for d in days:
        for page in fetch_issue(fetcher, d):
            for e in page.entries:
                if decision_matches(e, esas, karar):
                    return Located(page, e)
    return None
