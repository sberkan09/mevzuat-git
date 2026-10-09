"""Faz 3: undo and redo real amendments on the GVK excerpt, and the comparison layer."""

import json
from pathlib import Path

import pytest

from mevzuat_git import amendments as am
from mevzuat_git.compare import node_lines, norm
from mevzuat_git.fetch import decode_html
from mevzuat_git.model import Law, Level, Node, OpType
from mevzuat_git.replay import (
    UNKNOWN,
    ReplayError,
    _bump,
    _remove_span,
    _renumber,
    apply,
    apply_batch,
    find_all,
    unapply,
    unapply_batch,
)
from mevzuat_git.tree import build_tree, parse_fragment
from mevzuat_git.verify import OpResult, batches

FIX = Path(__file__).parent / "fixtures"
ARTICLES = json.loads((FIX / "rg_amendment_articles.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gvk() -> Law:
    html = decode_html((FIX / "gvk_193_tree_excerpt.html").read_bytes())
    return build_tree(html, 193)


def ops_of(key: str):
    a = ARTICLES[key]
    return am.parse_instruction(a["instruction"], a["payload"], 193)


def undo_redo(law: Law, ops) -> tuple[list[str], list[str], list[str]]:
    """Article lines before, after undoing ``ops`` (newest first), and after redoing them."""
    art = ops[0].target.madde
    before = node_lines(law.article(art))
    checks = [unapply(law, op).status for op in reversed(ops)]
    assert checks == ["ok"] * len(ops)
    undone = node_lines(law.article(art))
    for op in ops:
        apply(law, op)
    return before, undone, node_lines(law.article(art))


def test_insert_alt_bent_with_teselsul(gvk):
    # 5582/29: (7) numaralı bendinin (e) alt bendinden sonra ... mevcut (f) alt bendi (g)
    law = gvk.model_copy(deep=True)
    ops = ops_of("5582/29")
    before, undone, redone = undo_redo(law, ops)
    b7 = [line for line in undone if line.startswith(("e)", "f)", "g)"))]
    assert [x[:2] for x in b7][:2] == ["e)", "f)"] and not any(x.startswith("g)") for x in b7)
    assert redone == before


def test_insert_and_replace_phrase_in_one_sentence(gvk):
    law = gvk.model_copy(deep=True)
    ops = ops_of("6322/10")[:2]  # the rest address parts of md. 94 not in the excerpt
    assert [o.op for o in ops] == [OpType.INSERT_NODE, OpType.REPLACE_PHRASE]
    before, undone, redone = undo_redo(law, ops)
    assert any("Kamu Ortaklığı İdaresi" in x for x in undone)
    assert redone == before


# GVK md. 94, sekizinci fıkra, as on mevzuat.gov.tr: the "– " lines are its paragraphs.
MD94_F8 = [
    ("MADDE 94 – Cumhurbaşkanı, bu maddede yer alan tevkifat nispetini, her bir ödeme ve "
    "gelir için ayrı ayrı sıfıra kadar indirmeye veya bir katına kadar artırmak suretiyle "
    "yeniden tespit etmeye yetkilidir. Bu yetki;"),
    "– Tam ve dar mükellefler ile gerçek ve tüzel kişiler itibariyle,",
    ("– (Ek paragraf:27/12/2023-7491/11 md.) 3 numaralı bent kapsamında ödenen istihkak "
    "bedellerinden, işin; kamu kurum ve kuruluşları ile bunlara bağlı, ilgili ve ilişkili "
    "kurumlara taahhüt edilip edilmemesine ve bunların genel veya özel bütçeli idare "
    "kapsamında olup olmamasına, süresine, nevine ve yüklenicinin; ana yüklenici, alt "
    "yüklenici ya da tam ve dar mükellef olmasına göre ayrı ayrı veya birlikte,"),
    ("– 6, 7, 8, 9 ve 17 numaralı bentlerde yer alan kazanç ve iratlardan; mevduat veya "
    "menkul kıymetin vadesi, menkul kıymetlerin türleri ile bankalar ve 2499 sayılı Sermaye "
    "Piyasası Kanununa göre kurulan aracı kurumlar arasındaki borsa para piyasasında "
    "değerlendirilen paralara ödenen faizler için,"),
    "Farklı oranlar tespit edilmek suretiyle de kullanılabilir.",
]


def test_dash_lines_stay_in_their_fikra():
    (art,) = parse_fragment(MD94_F8, Level.MADDE)
    (f,) = art.children
    assert [c.level for c in f.children] == [Level.PARAGRAF] * 4
    assert f.children[-1].text.startswith("Farklı oranlar")


def test_paragraph_inserted_after_quoted_anchor():
    # 7491/11: sekizinci fıkrasına “– Tam ve dar ...” paragrafından sonra
    (art,) = parse_fragment(MD94_F8, Level.MADDE)
    art.id = "94"
    art.children = [Node(level=Level.FIKRA, text=f"fıkra {i}") for i in range(1, 8)] \
        + art.children
    law = Law(number=193, name="", body=[art])
    (op,) = ops_of("7491/11")
    before, undone, redone = undo_redo(law, [op])
    assert len(undone) == len(before) - 1
    assert undone[8].startswith("- Tam ve dar") and undone[9].startswith("- 6, 7, 8, 9 ve 17")
    assert redone == before


def test_replaced_node_is_unknown_until_replayed(gvk):
    # 4842/12 replaced alt bent (b) of md. 94/1-6 and its fourth fıkra. Undone, their
    # earlier wording is unknown; the replay must still be able to write over it.
    law = gvk.model_copy(deep=True)
    ops = ops_of("4842/12")
    for op in reversed(ops):
        unapply(law, op)
    assert UNKNOWN in "".join(n.text for n in law.article("94").walk())
    for op in ops:
        apply(law, op)
    assert UNKNOWN not in "".join(n.text for n in law.article("94").walk())


def test_inserted_ibare_is_undone_next_to_its_anchor():
    # 6645/8: “ilk iki çocuk için %7,5” ibaresinden sonra “, üçüncü çocuk için %10,”.
    # The same words earlier in the fıkra are not the inserted ones.
    (op,) = ops_of("6645/8")
    text = ("eşi için %10, üçüncü çocuk için %10, ve ilk iki çocuk için %7,5, üçüncü çocuk "
            "için %10, diğer çocuklar için %5")
    law = _article_law("32", "fıkra 1", text)
    assert unapply(law, op).status == "ok"
    assert law.article("32").children[1].text == (
        "eşi için %10, üçüncü çocuk için %10, ve ilk iki çocuk için %7,5 diğer çocuklar için %5")


def test_inserted_node_is_undone_after_a_later_replacement():
    # 4697/8 added bent (15) to md. 94/1; a later act replaced its alt bent (a), which
    # the unwind left as a placeholder. Undoing 4697/8 still takes the bent out.
    op = ops_of("4697/8")[1]
    assert (op.op, str(op.target)) == (OpType.INSERT_NODE, "md.94/f1")
    bent = op.new_nodes[0].model_copy(deep=True)
    bent.children[0].text = UNKNOWN
    law = Law(number=193, name="", body=[Node(level=Level.MADDE, id="94", label="Madde 94 –",
        children=[Node(level=Level.FIKRA, children=[
            Node(level=Level.BENT, label="14.", text="Bent 14."), bent])])])
    assert unapply(law, op).status == "ok"
    assert [b.label for b in law.article("94").children[0].children] == ["14."]


def test_articles_added_after_the_same_article_keep_their_order():
    # 7338 md. 1, 2 and 3 add mükerrer 20/A, 20/B and 20/C, each one "mükerrer 20 nci
    # maddesinden sonra gelmek üzere".
    def art(i):
        return Node(level=Level.MADDE, id=i, label=f"Madde {i} –", children=[
            Node(level=Level.FIKRA, text=f"text of {i}")])
    law = Law(number=193, name="", body=[art("mukerrer-20"), art("21")])
    for new in ("mukerrer-20/A", "mukerrer-20/B", "mukerrer-20/C"):
        apply(law, am.AmendmentOp(op=OpType.INSERT_NODE, kind=Level.MADDE, position="after",
                                  target=am.Path(madde="mukerrer-20"), new_nodes=[art(new)],
                                  source_sentence=""))
    assert [a.id for a in law.articles()] == [
        "mukerrer-20", "mukerrer-20/A", "mukerrer-20/B", "mukerrer-20/C", "21"]


def test_failed_check_is_reported():
    law = Law(number=193, name="")
    law.body.append(Node(level=Level.MADDE, id="74", label="Madde 74 –", children=[
        Node(level=Level.FIKRA, text="Bu oran %20'sidir.")]))
    op = am.parse_instruction(
        "193 sayılı Kanunun 74 üncü maddesinin birinci fıkrasında yer alan “%25’ini” ibaresi "
        "“%15’ini” şeklinde değiştirilmiştir.", [], 193)[0]
    assert unapply(law, op).status == "fail"
    with pytest.raises(ReplayError):
        apply(law, op)


def _batch_of(key: str, target: str) -> list[OpResult]:
    act, article = key.split("/")[:2]
    return [OpResult(act=act, article=article, op=o) for o in ops_of(key)
            if str(o.target) == target]


def _article_law(art: str, *fikralar: str) -> Law:
    return Law(number=193, name="", body=[Node(
        level=Level.MADDE, id=art, label=f"Madde {art} –",
        children=[Node(level=Level.FIKRA, text=t) for t in fikralar])])


def test_sirasiyla_replacements_happen_at_once():
    # 6462/1: “sakat” ve “sakatlık” ibareleri sırasıyla “engelli” ve “engellilik”. Taken
    # one by one, "sakat" would also take the start of "sakatlık" ("engellilık").
    rs = _batch_of("6462/1/31", "md.31/f1")
    assert [(r.op.old, r.op.new) for r in rs] == [("sakat", "engelli"), ("sakatlık", "engellilik")]
    assert [len(b) for b in batches(rs)] == [2]
    # Two sentences of the same act article are applied one after the other.
    other = OpResult(act="6462", article="1",
                     op=rs[1].op.model_copy(update={"source_sentence": "another sentence"}))
    assert [len(b) for b in batches([rs[0], other])] == [1, 1]
    law = _article_law("31", "… üçüncü derece sakat sayılır ve aşağıda sakatlık dereceleri "
                               "itibariyle belirlenen aylık tutarlar")
    apply_batch(law, [r.op for r in rs])
    assert law.article("31").children[0].text == (
        "… üçüncü derece engelli sayılır ve aşağıda engellilik dereceleri itibariyle "
        "belirlenen aylık tutarlar")


# GVK md. 17/2 on mevzuat.gov.tr, after 7582/3.
MD17_F2 = (
    "Şu kadar ki, hizmet erbabı tarafından bu şekilde iktisap edilen pay senetlerinin; "
    "iktisap tarihinden itibaren iki tam yıl içerisinde elden çıkarılması halinde istisna "
    "edilen verginin tamamı, üç ila dört yıl içerisinde elden çıkarılması halinde istisna "
    "edilen verginin %75’i, beş ila altı yıl içerisinde elden çıkarılması halinde istisna "
    "edilen verginin %25’i, vergi ziyaı cezası uygulanmaksızın gecikme faizi ile birlikte "
    "işverenden tahsil edilir.")


def test_sirasiyla_chain_is_undone_and_redone_in_one_pass():
    # 7582/3: “üç”, “dört”, “altı”, “yedi” ve “on iki” ibareleri sırasıyla “iki”, “üç”,
    # “dört”, “beş” ve “altı”. One by one, "iki" would be undone to "üç" and then "dört".
    rs = _batch_of("7582/3", "md.17/f2")
    assert [r.op.new for r in rs] == ["iki", "üç", "dört", "beş", "altı"]
    law = _article_law("17", "fıkra 1", MD17_F2)
    assert [c.status for c in unapply_batch(law, [r.op for r in rs])] == ["ok"] * 5
    old = law.article("17").children[1].text
    assert "itibaren üç tam yıl" in old and "dört ila altı yıl" in old
    assert "yedi ila on iki yıl" in old
    apply_batch(law, [r.op for r in rs])
    assert law.article("17").children[1].text == MD17_F2


@pytest.mark.parametrize(("label", "delta", "out"), [
    ("(2)", 1, "(3)"), ("9.", -1, "8."), ("c)", 1, "ç)"), ("ç)", -1, "c)"), ("ğ)", 1, "h)"),
    ("aa)", 1, "bb)"), ("çç)", -1, "cc)"),
])
def test_bump_follows_the_turkish_alphabet(label, delta, out):
    assert _bump(label, delta) == out


def test_renumbering_keeps_the_alphabet_of_the_siblings():
    # A list that goes c) d) (no ç) is renumbered the same way.
    def labels(*keys):
        return [Node(level=Level.BENT, label=f"{k})", text=k) for k in keys]
    sibs = labels("a", "b", "c", "d")
    _renumber(sibs, 1, sibs[1:2], 1)
    assert [n.label for n in sibs] == ["a)", "c)", "d)", "e)"]
    sibs = labels("a", "b", "c", "ç")
    _renumber(sibs, 1, sibs[1:2], 1)
    assert [n.label for n in sibs] == ["a)", "c)", "ç)", "d)"]


@pytest.mark.parametrize(("text", "cut", "out"), [
    ("bedelleri ile kira gelirleri ve", "ile kira gelirleri", "bedelleri ve"),
    ("tutarlar, aylık olarak", " aylık olarak", "tutarlar,"),
    ("Ancak bu oran uygulanır.", "Ancak ", "bu oran uygulanır."),
    ("ücretler (yemek dahil), ödenir", " (yemek dahil)", "ücretler, ödenir"),
    # Spacing elsewhere in the text is left as it is.
    ("a  b c d", "c ", "a  b d"),
])
def test_remove_span_tidies_only_the_cut(text, cut, out):
    s = text.index(cut)
    assert _remove_span(text, s, s + len(cut)) == out


def test_find_all_ignores_typography():
    text = "Hizmet erbabına “yemek” verilmek  suretiyle – sağlanan"
    assert find_all(text, '"yemek" verilmek suretiyle - sağlanan')


@pytest.mark.parametrize(("raw", "normal"), [
    # Change markers are editorial: "(Değişik: ...)", "(Ek cümle: ...)".
    ("(Değişik: 9/4/2003-4842/5 md.) Ticari kazanç", "Ticari kazanç"),
    ("tutarlar (Ek ibare: 25/7/2024-7524/1 md.) hariç", "tutarlar hariç"),
    # "(…)" marks a removed ibare.
    ("kurum (…) ve kuruluşlar", "kurum ve kuruluşlar"),
    # mevzuat.gov.tr's current value of an old amount.
    ("600 milyon lirayı (22.000 TL) aşmayan", "600 milyon lirayı aşmayan"),
    ("bedelinin 51 (300 TL) Türk lirasını", "bedelinin 51 Türk lirasını"),
    ("“yemek” – bedeli", '"yemek" - bedeli'),
    # Spelling variants: md. 103 is "tabi" on mevzuat.gov.tr, "tâbi" in the act.
    ("Gelir vergisine tâbi gelirler;", "Gelir vergisine tabi gelirler;"),
    # A footnote number glued to the end, but not a number that ends the text.
    ("ile birlikte işverenden tahsil edilir.10", "ile birlikte işverenden tahsil edilir."),
    ("tutarı 1.000", "tutarı 1.000"),
])
def test_norm(raw, normal):
    assert norm(raw) == normal
