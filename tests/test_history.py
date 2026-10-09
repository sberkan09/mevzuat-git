"""Faz 4: yürürlük dates from the consolidated text's table, and the git history."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from mevzuat_git import amendments as am
from mevzuat_git.amendment_list import AmendingAct, AmendmentList, EffectiveEntry, RGRef
from mevzuat_git.compare import strip_editorial
from mevzuat_git.history import (
    _differing_articles,
    build,
    clause_dates,
    render,
    table_articles,
    yururluk_date,
)
from mevzuat_git.model import Amendment, Law, Level, Node

FIX = Path(__file__).parent / "fixtures"
ARTICLES = json.loads((FIX / "rg_amendment_articles.json").read_text(encoding="utf-8"))

# Rows of GVK's yürürlük table on mevzuat.gov.tr, verbatim.


@pytest.mark.parametrize(("text", "ids"), [
    ("Mükerrer 21, 25, 40, 75, 86, 89, 94 üncü maddenin (15) numaralı bendi",
     ["mukerrer-21", "25", "40", "75", "86", "89", "94"]),
    ("Geçici 73 ve 74 Maddeler", ["gecici-73", "gecici-74"]),
    ("40, 48, 76, 89, 104, Geçici 55 ve 59 uncu Maddeler",
     ["40", "48", "76", "89", "104", "gecici-55", "gecici-59"]),
    ("Mükerrer Madde 20/D", ["mukerrer-20/D"]),
    ("Mükerer Madde 20/B, 40", ["mukerrer-20/B", "40"]),
    ("94/10-a, Geçici Madde 80", ["94", "gecici-80"]),
    ("19, Mükerrer 21, İkinci Kısım Sekizinci Bölüm Başlığı, Ek 1, 2, 3, 4",
     ["19", "mukerrer-21", "ek-1", "ek-2", "ek-3", "ek-4"]),
])
def test_table_articles(text, ids):
    assert [a for a, _ in table_articles(text)] == ids


RG = date(2004, 12, 31)


@pytest.mark.parametrize(("text", "expected"), [
    ("1/7/2026", date(2026, 7, 1)),
    ("1 1/1/2007 tarihinden geçerli olmak üzere 4/4/2007", date(2007, 4, 4)),
    ("1/1/2005 tarihinden itibaren elde edilen gelirlere uygulanmak üzere 31/12/2004 tarihinde",
     date(2004, 12, 31)),
    ("31/12/2004 tarihini izleyen aybaşında", date(2005, 1, 1)),
    ("9/4/2003 tarihini izleyen ikinci aybaşında", date(2003, 6, 1)),
    ("31/12/2023 tarihine kadar uygulanmak üzere 12/3/2008 tarihini takip eden aybaşında",
     date(2008, 4, 1)),
    ("1/1/2024 tarihinden itibaren elde edilen kazançlara uygulanmak üzere yayımı tarihinde",
     RG),
    (("1/1/2022 tarihinden itibaren elde edilen kazançlara uygulanmak üzere yayımı tarihinde "
      "(26/10/2021)"), date(2021, 10, 26)),
    ("(…)[223] 1/8/2010", date(2010, 8, 1)),
    (("23 üncü maddesi ve 29 uncu maddesi 1/2/2019 tarihinde, Geçici madde 76 1/1/2019 "
      "tarihinde"), None),
])
def test_yururluk_date(text, expected):
    assert yururluk_date(text, RG) == expected


def test_clause_dates():
    assert clause_dates("23 üncü maddesi ve 29 uncu maddesi 1/2/2019 tarihinde, Geçici madde "
                        "76 1/1/2019 tarihinde", date(2019, 1, 18)) == {
        "23": date(2019, 2, 1), "29": date(2019, 2, 1), "gecici-76": date(2019, 1, 1)}
    got = clause_dates(
        "103 üncü maddesinde yapılan değişiklik 1/1/2019 tarihinden itibaren elde edilen "
        "gelirlere uygulanmak üzere yayımı tarihinde, 23 üncü ve 29 uncu maddelerinde yapılan "
        "değişiklik Kanunun yayım tarihini izleyen ay başında, diğer hükümleri yayımı "
        "tarihinde (7/12/2019)", date(2019, 12, 7))
    assert got == {"103": date(2019, 12, 7), "23": date(2020, 1, 1), "29": date(2020, 1, 1),
                   None: date(2019, 12, 7)}


# -- the history ------------------------------------------------------------------------------

# GVK md. 17 on mevzuat.gov.tr, after 7582/3.
MD17 = [
    ("Sanayi ve Teknoloji Bakanlığınca belirlenen kriterlere göre teknogirişim şirketi niteliğini "
     "haiz işverenlerce hizmet erbabına bedelsiz veya indirimli olarak verilen ve ücret "
     "niteliğinde kabul edilen pay senetlerinin, verildiği tarihteki rayiç değerinin o yıldaki "
     "bir yıllık brüt ücret tutarının iki katını aşmayan kısmı gelir vergisinden istisnadır."),
    ("Şu kadar ki, hizmet erbabı tarafından bu şekilde iktisap edilen pay senetlerinin; "
     "iktisap tarihinden itibaren iki tam yıl içerisinde elden çıkarılması halinde istisna "
     "edilen verginin tamamı, üç ila dört yıl içerisinde elden çıkarılması halinde istisna "
     "edilen verginin %75’i, beş ila altı yıl içerisinde elden çıkarılması halinde istisna "
     "edilen verginin %25’i, vergi ziyaı cezası uygulanmaksızın gecikme faizi ile birlikte "
     "işverenden tahsil edilir.10"),
]


def _inputs():
    current = Law(number=193, name="GELİR VERGİSİ KANUNU", body=[Node(
        level=Level.MADDE, id="17", label="Madde 17 –",
        title="Hizmet erbabına pay senedi verilmek suretiyle sağlanan menfaatlerde ücret "
              "istisnası:",
        children=[Node(level=Level.FIKRA, text=t) for t in MD17])])
    a = ARTICLES["7582/3"]
    ops = am.parse_instruction(a["instruction"], a["payload"], 193)
    opsfile = am.OpsFile(target_law=193, acts=[am.ActOps(
        act="7582", rg_date=date(2026, 6, 4), rg_number="33270", text_url=a["source"],
        sentences=1, amendments=[Amendment(amending_law="7582", article="3", target_law=193,
                                           ops=ops)])])
    alist = AmendmentList(
        target_law=193, target_title="GELİR VERGİSİ KANUNU", target_tertip=4,
        source_url="", source_sha256="", acts=[AmendingAct(
            kind="kanun", number="7582",
            rg=RGRef(date=date(2026, 6, 4), number="33270", source="resmigazete.gov.tr"),
            effective=[EffectiveEntry(articles="17, 23", effective="4/6/2026",
                                      effective_date=date(2026, 6, 4))])])
    return current, opsfile, alist


def _log(repo: Path) -> list[str]:
    return subprocess.run(["git", "-C", str(repo), "log", "--reverse", "--format=%H %ad %s",
                           "--date=short"], check=True, capture_output=True,
                          text=True).stdout.splitlines()


def _show(repo: Path, rev: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "show", f"{rev}:193.md"], check=True,
                          capture_output=True, text=True).stdout


def test_history_of_one_act(tmp_path):
    current, opsfile, alist = _inputs()
    commits = build(current, opsfile, alist, tmp_path / "a")
    log = _log(tmp_path / "a")
    assert [line.split(" ", 2)[1:] for line in log] == [
        ["2026-06-04", "193 sayılı GELİR VERGİSİ KANUNU: başlangıç metni"],
        ["2026-06-04", "7582 sayılı Kanun: md. 17"]]
    assert len(commits) == 2
    before = _show(tmp_path / "a", "HEAD~1")
    assert "tutarını aşmayan" in before and "itibaren üç tam yıl" in before
    assert "yedi ila on iki yıl" in before
    after = _show(tmp_path / "a", "HEAD")
    assert after == render(current)
    # The footnote number is mevzuat.gov.tr's, not the law's.
    assert "tahsil edilir.\n" in after


def test_history_is_deterministic(tmp_path):
    current, opsfile, alist = _inputs()
    build(current, opsfile, alist, tmp_path / "a")
    build(current, opsfile, alist, tmp_path / "b")
    assert _log(tmp_path / "a") == _log(tmp_path / "b")


def test_differences_left_after_the_replay():
    # What the last commit brings to the consolidated text: content the replay did not
    # reproduce, and typography of text that came from an act ("MADDE 17-").
    current, _, _ = _inputs()
    replayed = current.model_copy(deep=True)
    assert _differing_articles(replayed, current) == ([], [])
    replayed.body[0].label = "MADDE 17-"
    assert _differing_articles(replayed, current) == ([], ["17"])
    replayed.body[0].children[0].text = "Başka bir metin."
    assert _differing_articles(replayed, current) == (["17"], [])


@pytest.mark.parametrize(("raw", "out"), [
    ("(Değişik: 9/4/2003-4842/5 md.) Ticari kazanç", "Ticari kazanç"),
    ("tutarlar (Ek ibare: 25/7/2024-7524/1 md.) hariç", "tutarlar hariç"),
    ("600 milyon lirayı (22.000 TL) aşmayan", "600 milyon lirayı aşmayan"),
    ("işverenden tahsil edilir.10", "işverenden tahsil edilir."),
    # Not mevzuat.gov.tr's: the mark of a removed ibare and the law's own typography.
    ("kurum (…) ve kuruluşlar", "kurum (…) ve kuruluşlar"),
    ("“yemek”  – bedeli", "“yemek”  – bedeli"),
])
def test_strip_editorial(raw, out):
    assert strip_editorial(raw) == out
