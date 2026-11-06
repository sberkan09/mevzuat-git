"""Faz 6: the viewer's data, built from a history repository.

The repository is a slice of mevzuat-tarihce (tests/fixtures/site_history.json): commit
messages and article texts verbatim."""

import json
from datetime import date

import pytest
from site_fixture import make_repo

from mevzuat_git.site import (
    article_at,
    article_ids,
    build,
    commit_kind,
    parse_law,
    parse_sections,
    subject_articles,
    unescape,
)

BASIN = "9. Basın yoluyla işlenen fiillerden"  # GVK 41/9, added by 4756 (21/5/2002)
ILISKILI = "ilişkili kişilerle emsallere uygunluk ilkesine aykırı"  # GVK 41/5, 5615


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("site")
    repo = make_repo(tmp / "repo")
    index = build(repo, tmp / "data", "https://github.com/sberkan09/mevzuat-tarihce")
    laws = {n: json.loads((tmp / "data" / f"{n}.json").read_text(encoding="utf-8"))
            for n in (193, 213, 3065)}
    return index, laws


def _text(version) -> str:
    return "\n".join(b for b in version["body"] if isinstance(b, str))


# -- the law file ----------------------------------------------------------------------------

LAW = """# GELİR VERGİSİ KANUNU (G.V.K.)

## BİRİNCİ KISIM

**Mükellefiyet**

### BİRİNCİ BÖLÜM

**Verginin Mevzuu**

#### Madde 1 – Mevzuu:

Gerçek kişilerin gelirleri gelir vergisine tâbidir.

#### Madde 2 – Gelirin unsurları:

Gelire giren kazanç ve iratlar şunlardır:

1\\. Ticarî kazançlar,

\\- Bu tablodaki tutarlar

| Gelir dilimi | Oran |
|---|---|
| 110.000 TL'ye kadar | 15 \\| 20 |

#### Mükerrer Madde 20/A- Basit usulde tespit olunan kazançlarda gelir vergisi istisnası:

#### Geçici Madde 67 –

[Bu tarihteki metin bilinmiyor.]
"""


def test_parse_law():
    law = parse_law(LAW)
    assert law.name == "GELİR VERGİSİ KANUNU (G.V.K.)"
    assert list(law.articles) == ["1", "2", "mukerrer-20/A", "gecici-67"]
    assert law.toc[:2] == [{"l": 2, "t": "BİRİNCİ KISIM", "s": "Mükellefiyet"},
                           {"l": 3, "t": "BİRİNCİ BÖLÜM", "s": "Verginin Mevzuu"}]
    a = law.articles["2"]
    assert (a.label, a.title) == ("Madde 2 –", "Gelirin unsurları:")
    assert a.blocks[1:3] == ["1. Ticarî kazançlar,", "- Bu tablodaki tutarlar"]
    assert a.blocks[3] == [["Gelir dilimi", "Oran"], ["110.000 TL'ye kadar", "15 | 20"]]
    m = law.articles["mukerrer-20/A"]
    assert m.label == "Mükerrer Madde 20/A-" and m.blocks == []
    assert law.articles["gecici-67"].title == ""


def test_unescape_keeps_text():
    assert unescape("1\\. Ticarî kazançlar,") == "1. Ticarî kazançlar,"
    assert unescape("a) Kazanç") == "a) Kazanç"
    assert unescape("Madde 1\\. gibi") == "Madde 1\\. gibi"  # only at the start


def test_duplicate_article_numbers_kept():
    law = parse_law("# K\n\n#### Madde 5 – A\n\nx\n\n#### Madde 5 – B\n\ny\n")
    assert list(law.articles) == ["5", "5~2"]


# -- commit messages (verbatim from mevzuat-tarihce) ---------------------------------------

JOINT = """193 sayılı Kanun:
Resmî Gazete: 2/8/2024, sayı 32620
Yürürlük: 2/8/2024
Yürürlük tablosu: 17: 2/8/2024
Değiştiren maddeler: 7524/2
Kaynak: https://www.resmigazete.gov.tr/eskiler/2024/08/20240802-2.htm

213 sayılı Kanun:
Resmî Gazete: 2/8/2024, sayı 32620
Yürürlük: 2/8/2024
Yürürlük tablosu: 112, 153/A, Mükerrer Madde 257, 263, 274/A, 344, 352, 353, Mükerrer Madde 355, 376, Ek Madde 1, Ek Madde 7, Ek Madde 8, Ek Madde 9, Ek Madde 11, Ek Madde 13, Geçici Madde 35: 2/8/2024
Yürürlük tablosu: yürürlük tablosunda yok; yayım tarihi alındı
Değiştiren maddeler: 7524/5, 7524/6
Kaynak: https://www.resmigazete.gov.tr/eskiler/2024/08/20240802-2.htm

Uygulanamayan işlemler:
- 7524/14 delete_phrase md.112/f3: ibare not found: 'Uzlaşılan vergilerde gecikme faizi'
- 7524/14 delete_phrase md.ek-1/f1/c7: sentence 7 not found (6 present)
- 7524/14 delete_phrase md.ek-8: ibare not found: 'vergi ve' in md.ek-8"""


def test_parse_sections_joint_commit():
    s = parse_sections(JOINT)
    assert set(s) == {193, 213}
    assert s[193].rg_date == date(2024, 8, 2) and s[193].rg_number == "32620"
    assert s[193].effective == date(2024, 8, 2) and not s[193].assumed
    assert s[193].by == "Değiştiren maddeler: 7524/2"
    assert len(s[213].table) == 2
    assert list(s[213].failed) == ["112", "ek-1", "ek-8"]
    assert s[193].failed == {}


def test_parse_sections_single_law_and_notes():
    body = ("Resmî Gazete: 27/3/2018, sayı 30373 (2.Mükerrer)\n"
            "Yürürlük: 3/7/2001 (varsayılan)\n"
            "Yürürlük tablosu: yürürlük tablosunda yok; yayım tarihi alındı\n"
            "Hüküm fıkrası: B/2\n"
            "Kaynak: https://www.resmigazete.gov.tr/eskiler/2026/06/20260603-3.pdf (PDF; "
            "işlemler mevzuat.gov.tr konsolide metninin dipnotlarından okundu)")
    s = parse_sections(body)[None]
    assert s.rg_number == "30373 (2.Mükerrer)"
    assert s.assumed and s.effective == date(2001, 7, 3)
    assert s.by == "Hüküm fıkrası: B/2"
    assert s.source.endswith("20260603-3.pdf")
    assert s.source_note.startswith("PDF; işlemler")


def test_parse_sections_sync():
    body = ("Değişikliklerin yeniden oynatılmasıyla elde edilen metin, ...\n\n"
            "193 sayılı Kanun:\n"
            "İçeriği ayrılan maddeler (Resmî Gazete metni okunamayan ya da henüz "
            "ayrıştırılamayan değişiklikler; ayrıntı: mevzuat-git replay raporu):\n"
            "23, 40, 46, 94, geçici 59, geçici 67, (madde sırası)\n\n"
            "Yalnız yazımı ayrılan maddeler (değiştiren kanunun yazımı ile güncel metninki: "
            "tırnak, tire, şapka, madde başlığı biçimi):\n"
            "17, mükerrer 20/A, ek 1")
    s = parse_sections(body)
    assert set(s) == {193}
    assert s[193].content == ["23", "40", "46", "94", "gecici-59", "gecici-67"]
    assert s[193].typography == ["17", "mukerrer-20/A", "ek-1"]
    assert s[193].order_differs


def test_article_ids_and_subjects():
    assert article_ids("23, mükerrer 20/A, geçici 59, ek 1")[0] == \
        ["23", "mukerrer-20/A", "gecici-59", "ek-1"]
    subject = "7524 sayılı Kanun: 193 md. 17; 213 md. 153/A, mükerrer 257, ek 1"
    assert subject_articles(subject, 193) == ["17"]
    assert subject_articles(subject, 213) == ["153/A", "mukerrer-257", "ek-1"]
    assert subject_articles(subject, 3065) == []
    assert subject_articles("4756 sayılı Kanun: md. 41", None) == ["41"]


@pytest.mark.parametrize(("subject", "kind"), [
    ("193 sayılı GELİR VERGİSİ KANUNU (G.V.K.): başlangıç metni", "start"),
    ("AYM E.2025/219 K.2026/43: 193 md. geçici 72", "aym"),
    ("700 sayılı KHK: 193 md. 23, 33", "khk"),
    ("4684 sayılı Kanun: 193 md. 38; 3065 md. 17", "kanun"),
])
def test_commit_kind(subject, kind):
    assert commit_kind(subject, "") == kind


def test_commit_kind_sync():
    assert commit_kind("Güncel konsolide metinlerle eşitleme: 193, 213",
                       "Değişikliklerin yeniden oynatılmasıyla elde edilen metin") == "sync"


# -- the built data --------------------------------------------------------------------------

def test_index(data):
    index, _ = data
    assert index["source"]["url"] == "https://github.com/sberkan09/mevzuat-tarihce"
    gvk = next(law for law in index["laws"] if law["number"] == 193)
    assert gvk["name"] == "GELİR VERGİSİ KANUNU (G.V.K.)"
    assert (gvk["first"], gvk["last"]) == ("2001-07-03", "2026-08-01")
    assert (gvk["articles"], gvk["unverified"], gvk["typography"]) == (5, 1, 1)
    assert [law["number"] for law in index["laws"]] == [193, 213, 3065]


def test_commits_of_a_law(data):
    _, laws = data
    commits = laws[193]["commits"]
    assert commits[0]["kind"] == "start" and commits[-1]["kind"] == "sync"
    c = next(c for c in commits if c["act"] == "4756 sayılı Kanun")
    assert c["rg_date"] == "2002-05-21" and c["effective"] == "2002-05-21"
    assert c["changed"] == ["41"]
    # 4684 names md. 38 but leaves the text as it was.
    c = next(c for c in commits if c["act"] == "4684 sayılı Kanun")
    assert c["changed"] == [] and c["named"] == ["38"]
    # A joint commit is in every law it touches, with that law's section.
    c = next(c for c in laws[213]["commits"] if c["act"] == "7394 sayılı Kanun")
    assert c["changed"] == ["359"] and c["named"][:2] == ["4", "359"]


def test_versions_only_when_text_changes(data):
    _, laws = data
    arts = laws[193]["articles"]
    assert len(arts["1"]["versions"]) == 1
    v41 = arts["41"]["versions"]
    dates = [laws[193]["commits"][v["c"]]["date"] for v in v41]
    assert dates == ["2001-07-03", "2002-05-21", "2007-04-04", "2013-01-01", "2018-07-09",
                     "2022-04-15", "2026-04-17"]
    assert BASIN not in _text(v41[0]) and BASIN in _text(v41[1])
    assert arts["41"]["label"] == "Madde 41 –"
    assert arts["41"]["title"] == "Gider kabul edilmiyen ödemeler:"


def test_verification_status(data):
    _, laws = data
    arts = laws[193]["articles"]
    assert arts["40"]["status"] == "unverified"
    assert arts["17"]["status"] == "typography"
    assert arts["41"]["status"] == "verified"
    # The sync commit brings md. 40 to the official text.
    last = arts["40"]["versions"][-1]
    assert laws[193]["commits"][last["c"]]["kind"] == "sync"


def test_article_at(data):
    _, laws = data
    gvk = laws[193]
    assert article_at(gvk, "41", date(2001, 1, 1)) == (None, [])  # before the history
    v, pending = article_at(gvk, "41", date(2002, 5, 20))
    assert BASIN not in _text(v) and pending == []
    v, _ = article_at(gvk, "41", date(2002, 5, 21))  # the day 4756 took effect
    assert BASIN in _text(v) and ILISKILI not in _text(v)
    v, _ = article_at(gvk, "41", date(2019, 3, 15))
    assert ILISKILI in _text(v)


def test_article_at_out_of_order(data):
    """VUK md. 359: 7423 (in force 1/1/2024) was published before the AYM decision (in
    force 29/11/2023). On 15/12/2023 the decision's version applies, but it already
    carries 7423's change."""
    _, laws = data
    vuk = laws[213]
    v, pending = article_at(vuk, "359", date(2023, 12, 15))
    assert vuk["commits"][v["c"]]["kind"] == "aym"
    assert [vuk["commits"][c]["act"] for c in pending] == ["7423 sayılı Kanun"]
    _, pending = article_at(vuk, "359", date(2024, 1, 1))
    assert pending == []


def test_build_is_deterministic(data, tmp_path):
    index, laws = data
    again = build(make_repo(tmp_path / "repo"), tmp_path / "data")
    assert again["laws"] == index["laws"]
    assert json.loads((tmp_path / "data" / "193.json").read_text(encoding="utf-8")) == laws[193]


def test_cli_site(tmp_path):
    from typer.testing import CliRunner

    from mevzuat_git.cli import app

    repo = make_repo(tmp_path / "repo")
    r = CliRunner().invoke(app, ["site", "--repo", str(repo), "--out", str(tmp_path / "out")])
    assert r.exit_code == 0, r.output
    assert "193: 23 commits, 5 articles, 1 unverified" in r.output
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == \
        ["193.json", "213.json", "3065.json", "index.json"]
