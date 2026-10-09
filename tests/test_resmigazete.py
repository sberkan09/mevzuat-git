from datetime import date
from pathlib import Path

from mevzuat_git import resmigazete as rg
from mevzuat_git.fetch import decode_html

FIX = Path(__file__).parent / "fixtures"


def load(name, d):
    url = rg.index_url(d)
    return rg.parse_index(decode_html((FIX / name).read_bytes()), url, d)


def test_index_url():
    assert rg.index_url(date(2024, 8, 2)) == \
        "https://www.resmigazete.gov.tr/eskiler/2024/08/20240802.htm"
    assert rg.index_url(date(2021, 12, 31), 6) == \
        "https://www.resmigazete.gov.tr/eskiler/2021/12/20211231M6.htm"


def test_inline_index_2003():
    page = load("rg_index_20030109.htm", date(2003, 1, 9))
    assert page.issue == "24988"
    (entry,) = [e for e in page.entries if rg.entry_matches(e, "4783")]
    assert entry.text.startswith("4783 Gelir Vergisi Kanunu, Vergi Usul Kanunu")
    # Before ~2005 laws are printed inside the day page: the link is an anchor.
    assert entry.href == "https://www.resmigazete.gov.tr/eskiler/2003/01/20030109.htm#1"


def test_file_per_item_index_2024():
    page = load("rg_index_20240802.htm", date(2024, 8, 2))
    matches = [e for e in page.entries if rg.entry_matches(e, "7524")]
    assert [e.href for e in matches] == \
        ["https://www.resmigazete.gov.tr/eskiler/2024/08/20240802-2.htm"]
    assert matches[0].text.startswith("7524 Vergi Kanunları ile Bazı Kanunlarda")
    # 7523 must not match 752 or 75240.
    assert not any(rg.entry_matches(e, "752") for e in page.entries)


def test_mukerrer_links_2021():
    page = load("rg_index_20211231.htm", date(2021, 12, 31))
    assert page.issue == "31706"
    assert page.mukerrer_urls[0] == \
        "https://www.resmigazete.gov.tr/eskiler/2021/12/20211231M1.htm"
    assert len(page.mukerrer_urls) == 7


def test_located_issue_label():
    page = rg.IndexPage(url="u", date=date(2021, 12, 31), mukerrer=6, issue="31706",
                        entries=[], mukerrer_urls=[])
    loc = rg.Located(page, rg.IndexEntry(href="https://x/20211231M6.htm#2", text="..."))
    assert loc.issue == "31706 (6. Mükerrer)"
    assert loc.text_url == "https://x/20211231M6.htm" and loc.anchor == "2"


def test_locate_falls_back_to_scan_when_rg_date_is_wrong(monkeypatch):
    # mevzuat.gov.tr gives 16/5/2012 for 6322; it was published on 15/6/2012.
    asked = []

    def fake_locate_on(fetcher, d, number, probe_mukerrer=False):
        asked.append((d, probe_mukerrer))
        if d == date(2012, 6, 15):
            page = rg.IndexPage(url="u", date=d, mukerrer=0, issue="28324", entries=[],
                                mukerrer_urls=[])
            return rg.Located(page, rg.IndexEntry(href="https://x/20120615-1.htm",
                                                  text="6322 Amme ..."))
        return None

    monkeypatch.setattr(rg, "locate_on", fake_locate_on)
    found = rg.locate(None, "6322", rg_date=date(2012, 5, 16), kabul_date=date(2012, 5, 31))
    assert found.page.date == date(2012, 6, 15)
    assert asked[:2] == [(date(2012, 5, 16), False), (date(2012, 5, 16), True)]
    assert all(not probe for _, probe in asked[2:])  # found before the probing pass


def test_single_item_mukerrer_without_index():
    # 2/1/2004 Mükerrer prints Kanun No. 5035 directly, with no list of links.
    d = date(2004, 1, 2)
    page = rg.parse_index(decode_html((FIX / "rg_20040102M1_excerpt.htm").read_bytes()),
                          rg.index_url(d, 1), d, mukerrer=1)
    assert page.issue == "25334"
    assert page.declared_laws == ["5035"]


def test_decision_matches():
    # Index lines of 26/7/2013 (RG 28719).
    entry = rg.IndexEntry(href="https://x/20130726-32.htm",
                          text="— Anayasa Mahkemesinin E. 2010/93, K: 2012/20 Sayılı Kararı")
    other = rg.IndexEntry(href="https://x/20130726-33.htm",
                          text="— Anayasa Mahkemesinin E. 2012/20, K: 2012/132 Sayılı Kararı")
    assert rg.decision_matches(entry, "2010/93", "2012/20")
    assert not rg.decision_matches(other, "2010/93", "2012/20")
    assert rg.decision_matches(rg.IndexEntry(href="u", text=(
        "–– Anayasa Mahkemesinin 12/2/2026 Tarihli ve E: 2025/219, K: 2026/43 Sayılı Kararı")),
        "2025/219", "2026/43")
