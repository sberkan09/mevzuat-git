"""Faz 4: yürürlük dates from the consolidated text's table, and the git history."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from mevzuat_git import amendments as am
from mevzuat_git.amendment_list import AmendingAct, AmendmentList, EffectiveEntry, RGRef
from mevzuat_git.compare import mark_annulled, strip_editorial
from mevzuat_git.history import (
    Step,
    _differing_articles,
    _step_commit,
    build,
    build_many,
    clause_dates,
    mark_pending,
    op_date,
    render,
    table_articles,
    yururluk_date,
)
from mevzuat_git.model import Amendment, Law, Level, Node, OpType
from mevzuat_git.verify import OpResult, op_results

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
    (("19, Mükerrer 21, İkinci Kısım Sekizinci Bölüm Başlığı, Ek 1, 2, 3, 4, 5 ve 6 ncı "
      "Maddeler, 38, 75, Mükerrer 75, 89, 94, Mükerrer 120, Mükerrer 123, Geçici 61, 62, 63 "
      "ve 64 üncü Maddeler"),
     ["19", "mukerrer-21", "ek-1", "ek-2", "ek-3", "ek-4", "ek-5", "ek-6", "38", "75",
      "mukerrer-75", "89", "94", "mukerrer-120", "mukerrer-123", "gecici-61", "gecici-62",
      "gecici-63", "gecici-64"]),
    # Not a list of Mükerrer articles: no "Maddeler".
    ("40, 42, 44, 68, 89, 92, 94, 98, 119, Mükerrer 120, 121, Geçici 55 ve 59",
     ["40", "42", "44", "68", "89", "92", "94", "98", "119", "mukerrer-120", "121",
      "gecici-55", "gecici-59"]),
    ("(…)[222], Geçici 69 ve 70 inci Maddeler", ["gecici-69", "gecici-70"]),
    # The ordinals are fıkralar of geçici 67, not articles.
    ("Geçici Madde 67’nin 1 inci fıkrasının birinci paragrafı, 7 nci, 14 üncü, 17 nci fıkrası",
     ["gecici-67"]),
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
    (("24/6/2018 tarihinde birlikte yapılan Türkiye Büyük Millet Meclisi ve Cumhurbaşkanlığı "
      "seçimleri sonucunda Cumhurbaşkanının andiçerek göreve başladığı tarihte (9/7/2018)"),
     date(2018, 7, 9)),
    # VUK (213): 7555, 7103 and 5228 rows.
    ("yayımını izleyen ayın başında (1/8/2025)", date(2025, 8, 1)),
    ("Yayım tarihi olan 27/3/2018’i izleyen ikinci aybaşında (1/5/2018)", date(2018, 5, 1)),
    ("Yayımı tarihini takip eden ayın başında (1/11/2021)", date(2021, 11, 1)),
    ("31/7/2004 tarihini izleyen üçüncü günde", date(2004, 8, 3)),
    (("23 üncü maddesi ve 29 uncu maddesi 1/2/2019 tarihinde, Geçici madde 76 1/1/2019 "
      "tarihinde"), None),
])
def test_yururluk_date(text, expected):
    assert yururluk_date(text, RG) == expected


def _act(number, rg, rows):
    return AmendingAct(kind="kanun", number=number,
                       rg=RGRef(date=rg, source="resmigazete.gov.tr"),
                       effective=[EffectiveEntry(articles=a, effective=e) for a, e in rows])


def _r(target, op=OpType.REPLACE_PHRASE, kind=None, new_nodes=()):
    return OpResult(act="", article="", op=am.AmendmentOp(
        op=op, kind=kind, target=target, new_nodes=list(new_nodes), source_sentence=""))


def test_rows_are_told_apart_by_the_parts_they_name():
    act = _act("5527", date(2006, 7, 7), [
        (("Geçici Madde 67’nin 1 inci fıkrasının birinci paragrafı, 7 nci, 14 üncü, 17 nci "
          "fıkrası"), "7/7/2006"),
        ("Geçici Madde 67’nin 1 inci fıkrasının altıncı paragrafı, 8 inci fıkrası", "1/10/2006")])
    rg = date(2006, 7, 7)

    def day(**target):
        return op_date(_r(am.Path(madde="gecici-67", **target)), act, rg).date
    assert day(fikra=1, paragraf=1) == date(2006, 7, 7)
    assert day(fikra=1, paragraf=6) == date(2006, 10, 1)
    assert day(fikra=8) == date(2006, 10, 1)
    assert day(fikra=14, cumle=2) == date(2006, 7, 7)
    # The (17) numaralı fıkra it adds.
    added = Node(level=Level.FIKRA, label="(17)", text="…")
    assert op_date(_r(am.Path(madde="gecici-67", fikra=16), OpType.INSERT_NODE, Level.FIKRA,
                      [added]), act, rg).date == date(2006, 7, 7)

    act = _act("6322", date(2012, 6, 15), [
        ("9, 46, 75, 89, 94, Geçici Madde 67, Geçici Madde 81", "15/6/2012"),
        ("94/10-a, Geçici Madde 80", "1/7/2012")])
    rg = date(2012, 6, 15)
    target = am.Path(madde="94", fikra=1, bent="10", alt_bent="a")
    assert op_date(_r(target), act, rg).date == date(2012, 7, 1)
    assert op_date(_r(am.Path(madde="94", fikra=1, bent="3")), act, rg).date == rg
    whole = op_date(_r(am.Path(madde="94", fikra=4)), act, rg)
    assert (whole.date, whole.assumed) == (rg, False)


def test_table_date_long_after_publication_is_not_taken():
    # 4761 was published on 22/6/2002; the table says "22/6/2012".
    act = _act("4761", date(2002, 6, 22), [("Geçici Madde 60", "22/6/2012")])
    got = op_date(_r(am.Path(madde="gecici-60")), act, date(2002, 6, 22))
    assert (got.date, got.assumed) == (date(2002, 6, 22), True)


def test_annulment_takes_effect_on_its_date():
    # E.2006/119, K.2009/145 (RG 8/1/2010) put off its annulment by nine months; it has no
    # row in the yürürlük table.
    act = AmendingAct(kind="aym", number="E.2006/119, K.2009/145",
                      rg=RGRef(date=date(2010, 1, 8), source="resmigazete.gov.tr"))
    r = _r(am.Path(madde="gecici-67", fikra=1, paragraf=1), OpType.DELETE_PHRASE)
    r.effective = date(2010, 10, 8)
    got = op_date(r, act, date(2010, 1, 8))
    assert (got.date, got.assumed) == (date(2010, 10, 8), False)
    r.effective = date(2010, 1, 8)
    assert "Anayasa md. 153" in op_date(r, act, date(2010, 1, 8)).source


def test_annulment_commit():
    r = _r(am.Path(madde="gecici-72", fikra=2, cumle=3), OpType.DELETE_PHRASE)
    r.act, r.article = "E.2025/219, K.2026/43", "?"
    url = "https://www.resmigazete.gov.tr/eskiler/2026/06/20260603-3.pdf"
    c = _step_commit(Step("E.2025/219, K.2026/43", date(2026, 6, 3), "33269", url, "footnotes",
                          "aym", date(2026, 6, 3), [], [[r]]))
    assert c.subject == "AYM E.2025/219 K.2026/43: md. geçici 72"
    assert not any(line.startswith(("Değiştiren", "Hüküm")) for line in c.body)
    assert c.body[-1] == (f"Kaynak: {url} (PDF; işlemler mevzuat.gov.tr konsolide metninin "
                          "dipnotlarından okundu)")


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


def test_history_of_two_laws(tmp_path):
    # One act on two laws (a torba kanun) is one commit that changes both files.
    current, opsfile, alist = _inputs()
    vuk = current.model_copy(update={"number": 213, "name": "VERGİ USUL KANUNU"}, deep=True)
    vuk_ops = opsfile.model_copy(update={"target_law": 213}, deep=True)
    vuk_list = alist.model_copy(update={"target_law": 213}, deep=True)
    commits = build_many([(current, opsfile, alist), (vuk, vuk_ops, vuk_list)],
                         tmp_path / "a")
    assert [line.split(" ", 2)[1:] for line in _log(tmp_path / "a")] == [
        ["2026-06-04", "193 sayılı GELİR VERGİSİ KANUNU: başlangıç metni"],
        ["2026-06-04", "213 sayılı VERGİ USUL KANUNU: başlangıç metni"],
        ["2026-06-04", "7582 sayılı Kanun: 193 md. 17; 213 md. 17"]]
    assert commits[-1].body[0] == "193 sayılı Kanun:" and "213 sayılı Kanun:" in commits[-1].body
    assert sorted(p.name for p in (tmp_path / "a").iterdir() if p.suffix == ".md") == [
        "193.md", "213.md"]


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
    # geçici 69: an annulment noted with "kararıyla".
    (("indirebilirler. (Ek cümleler: 23/7/2010-6009/5 md.; İptal birinci cümle: Anayasa "
      "Mahkemesinin 9/2/2012 tarihli ve E.2010/93, K.2012/20 sayılı kararıyla) Kalan kazanç"),
     "indirebilirler. Kalan kazanç"),
])
def test_strip_editorial(raw, out):
    assert strip_editorial(raw) == out


def test_marker_of_an_annulled_first_sentence_marks_its_place():
    text = ("indirebilirler. (Ek cümleler: 23/7/2010-6009/5 md.; İptal birinci cümle: Anayasa "
            "Mahkemesinin 9/2/2012 tarihli ve E.2010/93, K.2012/20 sayılı kararıyla) Kalan kazanç")
    assert mark_annulled(text) == "indirebilirler. (…) Kalan kazanç"
    # Other markers stay for ``strip_editorial``.
    plain = "tutarlar (Ek ibare: 25/7/2024-7524/1 md.) hariç"
    assert mark_annulled(plain) == plain


def test_operations_in_force_later_are_pending():
    # 7524 (RG 2/8/2024) adds KDV md. 30 (f) and md. 58's fıkras from 1/1/2030; the
    # consolidated text fetched before then does not have them.
    act = _act("7524", date(2024, 8, 2), [("13, 36", "1/9/2024"), ("30, 58", "1/1/2030")])
    r30, r36 = _r(am.Path(madde="30", fikra=1), OpType.INSERT_NODE), _r(am.Path(madde="36"))
    assert op_date(r30, act, date(2024, 8, 2), as_of=date(2026, 10, 9)).date \
        == date(2030, 1, 1)
    ops = am.OpsFile(target_law=3065, acts=[am.ActOps(
        act="7524", rg_date=date(2024, 8, 2), rg_number="32620", text_url="", sentences=2,
        amendments=[Amendment(amending_law="7524", article=a, target_law=3065, ops=[r.op])
                    for a, r in (("20", r30), ("21", r36))])])
    alist = AmendmentList(target_law=3065, target_title="", target_tertip=5,
                          source_url="", source_sha256="", acts=[act])
    assert mark_pending(ops, alist, date(2026, 10, 9)) == 1
    assert r30.op.pending == date(2030, 1, 1) and r36.op.pending is None
    assert [r.op for r in op_results(ops)] == [r36.op]


def test_ibare_replacements_of_a_sentence_are_one_batch_across_other_parts():
    # 700/90 on KDV md. 38: “Bakanlar Kurulu” in the first and fourth fıkras, then
    # “Bakanlar Kurulunca” in the first; one by one, the first would eat the second.
    from mevzuat_git.verify import batches
    s = "bu maddenin birinci ve dördüncü fıkralarında ..."

    def r(fikra, old, new):
        return OpResult(act="700", article="90", op=am.AmendmentOp(
            op=OpType.REPLACE_PHRASE, target=am.Path(madde="38", fikra=fikra), old=old,
            new=new, source_sentence=s))
    a, b, c = (r(1, "Bakanlar Kurulu", "Cumhurbaşkanı"), r(4, "Bakanlar Kurulu", "Cumhurbaşkanı"),
               r(1, "Bakanlar Kurulunca", "Cumhurbaşkanınca"))
    assert batches([a, b, c]) == [[a, c], [b]]
    # Not across a change to the same fıkra.
    d = r(1, "x", "y")
    d.op = d.op.model_copy(update={"op": OpType.INSERT_PHRASE})
    assert batches([a, d, c]) == [[a], [d], [c]]
    # Nor across an insert in the same article: "mevcut ikinci fıkrası" is counted after it.
    ins = OpResult(act="700", article="90", op=am.AmendmentOp(
        op=OpType.INSERT_NODE, target=am.Path(madde="38", fikra=2), position="after",
        source_sentence=s))
    x, e = r(3, "X", "Y"), r(3, "Z", "W")
    assert batches([x, ins, e]) == [[x], [ins], [e]]
