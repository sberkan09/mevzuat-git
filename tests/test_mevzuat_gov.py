from datetime import date
from pathlib import Path

import pytest

from mevzuat_git import mevzuat_gov as mg

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def gvk():
    return mg.parse_consolidated((FIX / "gvk_193_excerpt.html").read_text())


def test_urls():
    assert mg.iframe_url(193, tertip=4) == (
        "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?"
        "MevzuatTur=1&MevzuatNo=193&MevzuatTertip=4"
    )
    assert mg.download_url(193, "pdf", tertip=4) == \
        "https://www.mevzuat.gov.tr/MevzuatMetin/1.4.193.pdf"


def test_header_of_gvk(gvk):
    h = gvk.header
    assert h.title == "GELİR VERGİSİ KANUNU (G.V.K.)"
    assert h.number == "193"
    assert h.kabul_date == date(1960, 12, 31)
    assert (h.rg_date, h.rg_number) == (date(1961, 1, 6), "10700")


def test_header_of_amending_law():
    h = mg.parse_header((FIX / "mevzuat_7524_header.html").read_text())
    assert h.number == "7524"
    assert h.title.startswith("VERGİ KANUNLARI İLE BAZI KANUNLARDA")
    assert h.kabul_date == date(2024, 7, 28)
    assert (h.rg_date, h.rg_number) == (date(2024, 8, 2), "32620")


def test_articles_and_appendix_cutoff(gvk):
    # "Geçici Madde 1..7" of the işlenemeyen hükümler appendix are not GVK articles.
    assert gvk.articles == ["1", "2", "3", "7", "mukerrer-20/D", "gecici-94"]


def test_markers_are_attributed_to_articles(gvk):
    got = [(a, e.kind, e.law, e.law_article, e.date) for a, e in gvk.markers]
    assert got[0] == ("1", "degisik", 4783, "1", date(2003, 1, 7))
    assert ("3", "degisik", 202, "1", date(1963, 2, 19)) in got  # mid-paragraph, bent 2
    assert got[-1] == ("gecici-94", "ek", 7587, "6", date(2026, 6, 24))


@pytest.mark.parametrize(
    "marker, expected",
    [
        # Real markers from the GVK consolidated text.
        ("(Değişik: 7/1/2003-4783/1 md.)",
         [("degisik", "Değişik", date(2003, 1, 7), 4783, "1")]),
        ("(Ek:11/11/2020-7256/15 md.)", [("ek", "Ek", date(2020, 11, 11), 7256, "15")]),
        ("(Ek: 24/12/1980-2361/36 md; Değişik: 26/12/1993-3946/12 md.)",
         [("ek", "Ek", date(1980, 12, 24), 2361, "36"),
          ("degisik", "Değişik", date(1993, 12, 26), 3946, "12")]),
        ("(Mülga üçüncü fıkra: 11/8/1999-4444/14 md.; Yeniden düzenleme: 28/3/2007-5615/1 md.)",
         [("mulga", "Mülga üçüncü fıkra", date(1999, 8, 11), 4444, "14"),
          ("yeniden_duzenleme", "Yeniden düzenleme", date(2007, 3, 28), 5615, "1")]),
        ("(Başlığı ile Birlikte Yeniden Düzenleme:28/7/2024-7524/2 md.)",
         [("yeniden_duzenleme", "Başlığı ile Birlikte Yeniden Düzenleme",
           date(2024, 7, 28), 7524, "2")]),
        ("(Ek: 30/12/2004-5281/ 30 md.)", [("ek", "Ek", date(2004, 12, 30), 5281, "30")]),
        ("(Ek: 16/6/2009 – 5904/4 md.)", [("ek", "Ek", date(2009, 6, 16), 5904, "4")]),
        ("(Değişik bentler 2, 3, 4 : 24/12/1980-2361/20 md.)",
         [("degisik", "Değişik bentler 2, 3, 4", date(1980, 12, 24), 2361, "20")]),
        ("(Ek parantez içi hüküm:5/12/2019-7194/11 md.)",
         [("ek", "Ek parantez içi hüküm", date(2019, 12, 5), 7194, "11")]),
    ],
)
def test_parse_marker(marker, expected):
    got = [(e.kind, e.label, e.date, e.law, e.law_article) for e in mg.parse_marker(marker)]
    assert got == expected


def test_parse_marker_aym():
    s = ("(Ek cümle: 27/6/2006-5527/1 md.; İptal: Anayasa Mahkemesi’nin 15/10/2009 tarihli ve "
         "E.: 2006/119, K.: 2009/145 sayılı Kararı ile.; Yeniden düzenleme: 23/7/2010-6009/4 md.)")
    events = mg.parse_marker(s)
    assert [e.kind for e in events] == ["ek", "iptal", "yeniden_duzenleme"]
    assert events[1].law is None and events[1].date == date(2009, 10, 15)
    assert events[1].aym_ref == "E.: 2006/119, K.: 2009/145"


def test_marker_regex_finds_marker_in_sentence():
    s = ("2. (Değişik: 19/2/1963-202/1 md.) Resmi daire ve müesseselere veya merkezi "
         "Türkiye'de bulunan teşekkül ve teşebbüslere bağlı olup")
    assert [m.group(0) for m in mg.MARKER_RE.finditer(s)] == ["(Değişik: 19/2/1963-202/1 md.)"]


def test_footnotes(gvk):
    (fn,) = gvk.footnotes
    assert fn.number == 1 and fn.article == "7"
    assert fn.text.startswith("22/7/1998 tarih ve 4369 sayılı Kanunun 81/C maddesi ile")


def test_yururluk_table_resolves_rowspan(gvk):
    rows = [(r.amending, r.articles, r.effective) for r in gvk.table]
    assert rows[1] == ("39", "Geçici Madde 10", "1/3/1962")
    # 365 spans three rows in the source table.
    assert [r for r in rows if r[0] == "365"] == [
        ("365", "40, 96, Geçici Madde 6", "31/12/1963"),
        ("365", "19", "1/1/1964"),
        ("365", "117", "1/3/1964"),
    ]
    assert ("7582", "17, 23", "4/6/2026") in rows
    assert rows[-1] == ("7587", "113, Geçici Madde 94", "1/7/2026")


def test_article_id():
    assert mg.article_id(None, "23") == "23"
    assert mg.article_id("Mükerrer ", "20/D") == "mukerrer-20/D"
    assert mg.article_id("Mükerer ", "20/B") == "mukerrer-20/B"  # source typo
    assert mg.article_id("Geçici ", "67") == "gecici-67"


def test_yururluk_table_of_vuk():
    # VUK (213) names the first column "Değiştiren Kanunun/KHK’nin veya İptal Eden Kararın
    # Numarası".
    from selectolax.lexbor import LexborHTMLParser
    html = (
        "<table><tr><td>Değiştiren Kanunun/KHK’nin veya İptal Eden Kararın Numarası</td>"
        "<td>213 sayılı Kanunun Değişen veya İptal Edilen Maddeleri</td>"
        "<td>Yürürlüğe Giriş Tarihi</td></tr>"
        "<tr><td rowspan=2>7555</td><td>131</td><td>24/7/2025</td></tr>"
        "<tr><td>Ek Madde 13</td><td>yayımını izleyen ayın başında (1/8/2025)</td></tr>"
        "</table>")
    rows = mg.parse_yururluk_table(LexborHTMLParser(html))
    assert [(r.amending, r.articles, r.effective) for r in rows] == [
        ("7555", "131", "24/7/2025"),
        ("7555", "Ek Madde 13", "yayımını izleyen ayın başında (1/8/2025)")]
