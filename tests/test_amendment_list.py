from datetime import date
from pathlib import Path

from mevzuat_git import amendment_list as al
from mevzuat_git import mevzuat_gov as mg

FIX = Path(__file__).parent / "fixtures"


def acts():
    c = mg.parse_consolidated((FIX / "gvk_193_excerpt.html").read_text())
    return {a.key: a for a in al.build(193, c)}


def test_merges_markers_footnotes_and_table():
    a = acts()
    k4783 = a[("kanun", "4783")]
    assert k4783.kabul_date == date(2003, 1, 7)
    assert k4783.affected_articles == ["1", "2"]
    assert [m.law_article for m in k4783.markers] == ["1", "2"]

    k4369 = a[("kanun", "4369")]  # only in a footnote
    assert k4369.seen_in == ["footnote"]
    assert k4369.kabul_date == date(1998, 7, 22)
    assert k4369.footnotes[0].law_article == "81/C"
    assert k4369.affected_articles == ["7"]

    k365 = a[("kanun", "365")]  # only in the table
    assert [e.effective_date for e in k365.effective] == \
        [date(1963, 12, 31), date(1964, 1, 1), date(1964, 3, 1)]

    k7582 = a[("kanun", "7582")]
    assert k7582.seen_in == ["marker", "table"]
    assert k7582.effective[1].effective.startswith("1/1/2026 tarihinden itibaren")


def test_aym_decision_from_table():
    a = acts()
    assert ("aym", "E.2025/219, K.2026/43") in a


def test_sorted_by_date():
    c = mg.parse_consolidated((FIX / "gvk_193_excerpt.html").read_text())
    dated = [x.kabul_date for x in al.build(193, c) if x.kabul_date]
    assert dated == sorted(dated)


def test_footnote_refs_real_sentences():
    # GVK footnotes, verbatim.
    assert al.footnote_refs(
        "22/7/1998 tarih ve 4369 sayılı Kanunun 81/C maddesi ile bu bentte geçen "
        "\"Sair kazanç ve iratlarda\" ibaresi, “Diğer kazanç ve iratlarda” şeklinde "
        "değiştirilmiştir."
    ) == [("kanun", "4369", date(1998, 7, 22), "81/C")]
    assert al.footnote_refs(
        "2/7/2018 tarihli ve 700 sayılı KHK’nin 45 inci maddesiyle, bu bentte yer alan "
        "“Bakanlar Kurulu” ibaresi “Cumhurbaşkanı” şeklinde değiştirilmiştir."
    ) == [("khk", "700", date(2018, 7, 2), "45")]
    # Source typo "tairhli" is still a dated reference.
    assert al.footnote_refs(
        "6/12/2017 tairhli ve 7063 sayılı Kanunun 1 inci maddesi ile bu maddenin birinci "
        "fıkrasında yer alan “31/12/2017” ibaresi “31/12/2019” şeklinde değiştirilmiştir."
    ) == [("kanun", "7063", date(2017, 12, 6), "1")]
    # Capital "Sayılı".
    assert al.footnote_refs(
        "Parantez içinde yer alan \"(69 uncu madde hükmü mahfuzdur)\" ibaresi, 22/7/1998 "
        "tarih ve 4369 Sayılı Kanunun 82 nci maddesi ile yürürlükten kaldırılmıştır."
    ) == [("kanun", "4369", date(1998, 7, 22), "82")]


def test_footnote_refs_skip_laws_only_mentioned():
    # 4749 appears inside the new ibare, not as the amending act.
    assert al.footnote_refs(
        "31/5/2012 tarihli ve 6322 sayılı Kanunun 11 inci maddesiyle bu paragrafda yer alan "
        "“Hazine” ibaresi “Hazine ve 4749 sayılı Kanuna göre kurulan varlık kiralama "
        "şirketleri” şeklinde değiştirilmiştir."
    ) == [("kanun", "6322", date(2012, 5, 31), "11")]
    assert al.footnote_refs(
        "b) 4077 sayılı Kanuna göre gerçek ve tüzel kişilerin mallarını iş akti ile bağlı "
        "olmaksızın"
    ) == []


def test_footnote_refs_aym():
    assert al.footnote_refs(
        "Bu arada yer alan “gelir” ibaresi, Anayasa Mahkemesinin 16/1/2003 tarihli ve "
        "E.:2001/36, K.:2003/3 sayılı Kararı ile iptal edilmiştir."
    ) == [("aym", "E.2001/36, K.2003/3", date(2003, 1, 16), None)]


def test_majority_kabul_date_with_note():
    c = mg.ConsolidatedText(header=mg.Header(title="x"))
    for d in ("9/4/2003", "9/4/2003", "9/4/2004"):  # real typo in GVK markers for 4842
        (ev,) = mg.parse_marker(f"(Ek: {d}-4842/17 md.)")
        c.markers.append(("1", ev))
    (act,) = al.build(193, c)
    assert act.kabul_date == date(2003, 4, 9)
    assert act.notes == ["other dates in consolidated text: 2004-04-09 (1x)"]


def test_schema_roundtrip():
    c = mg.parse_consolidated((FIX / "gvk_193_excerpt.html").read_text())
    lst = al.AmendmentList(target_law=193, target_title="t", target_tertip=4,
                           target_rg_date=date(1961, 1, 6), target_rg_number="10700",
                           source_url="u", source_sha256="0", acts=al.build(193, c))
    assert al.AmendmentList.model_validate_json(lst.model_dump_json()) == lst
    # The CLI writes with exclude_none; the file must still load.
    assert al.AmendmentList.model_validate_json(lst.model_dump_json(exclude_none=True)) == lst


def test_committed_list_loads():
    p = Path(__file__).parent.parent / "data" / "processed" / "193_amendments.json"
    lst = al.AmendmentList.model_validate_json(p.read_text())
    assert lst.target_law == 193 and len(lst.acts) > 100
