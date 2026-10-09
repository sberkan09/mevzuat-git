"""Faz 3: undo and redo real amendments on the GVK excerpt, and the comparison layer."""

import json
from pathlib import Path

import pytest

from mevzuat_git import amendments as am
from mevzuat_git.compare import node_lines, norm
from mevzuat_git.fetch import decode_html
from mevzuat_git.model import AmendmentOp, Law, Level, Node, OpType
from mevzuat_git.model import Path as Addr
from mevzuat_git.replay import (
    UNKNOWN,
    ReplayError,
    _bump,
    _remove_span,
    _renumber,
    apply,
    apply_batch,
    find_all,
    locate,
    unapply,
    unapply_batch,
)
from mevzuat_git.tree import build_tree, parse_fragment
from mevzuat_git.verify import OpResult, batches, mark_replaced, unwind

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


def test_articles_added_at_the_end_go_in_number_order():
    # 6322 md. 12 and 13 add geçici 80 and 81 at the end of the law; the history applies
    # 81 first, since it takes effect earlier.
    def art(i):
        return Node(level=Level.MADDE, id=i, label=f"Geçici Madde {i[7:]} –", children=[
            Node(level=Level.FIKRA, text=f"text of {i}")])
    law = Law(number=193, name="", body=[art("gecici-79")])
    for new in ("gecici-81", "gecici-80"):
        apply(law, am.AmendmentOp(op=OpType.INSERT_NODE, kind=Level.MADDE, position="end",
                                  target=am.Path(madde=""), new_nodes=[art(new)],
                                  source_sentence=""))
    assert [a.id for a in law.articles()] == ["gecici-79", "gecici-80", "gecici-81"]


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


@pytest.mark.parametrize(("text", "phrase"), [
    # 5035/48 on geçici 55: "1.1.1999 - 31.12.2004"; mevzuat.gov.tr: "1.1.1999-31.12.2005".
    ("1.1.1999-31.12.2004 tarihleri arasında elde edilen",
     "1.1.1999 - 31.12.2004 tarihleri arasında"),
    # 7061/14 on md. 68: "%15’ini"; mevzuat.gov.tr: "% 15'ini".
    ("hasılatlarından % 15'ini götürü olarak", "%15’ini"),
    # 5228/59 on md. 23/b12: “ 3308 sayılı ...” with a space, "tâbi" against "tabi".
    ("3308 sayılı Çıraklık ve Meslekî Eğitim Kanununa tâbi çırakların",
     " 3308 sayılı Çıraklık ve Mesleki Eğitim Kanununa tabi çırakların"),
])
def test_find_all_ignores_spacing_and_circumflex(text, phrase):
    assert find_all(text, phrase)


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
    # The amount may end with a dot or stand before a comma (md. 18, md. 40).
    ("hasılatın 220.000 (1.900.000 TL.) Türk lirasını", "hasılatın 220.000 Türk lirasını"),
    ("135.000 Türk lirasını (1.380.000 TL) , söz konusu", "135.000 Türk lirasını, söz konusu"),
    # 7061/14 writes "%15", mevzuat.gov.tr "% 15"; 5035/48 "1.1.1999 - 31.12.2004".
    ("hasılatlarından % 15'ini", "hasılatlarından %15'ini"),
    ("1.1.1999 - 31.12.2004 tarihleri", "1.1.1999-31.12.2004 tarihleri"),
])
def test_norm(raw, normal):
    assert norm(raw) == normal


def _md89(*fikra1: Node, after: list[Node] = ()) -> Law:
    f1 = Node(level=Level.FIKRA, text="Gelir vergisi matrahının tespitinde ...",
              children=list(fikra1))
    rest = Node(level=Level.FIKRA, text="Bağış ve yardımın nakden yapılmaması halinde ...")
    return Law(number=193, name="", body=[Node(level=Level.MADDE, id="89", label="Madde 89 –",
                                              children=[f1, *after, rest])])


def test_bent_added_at_the_end_with_closing_paragraphs():
    # 7256/16 adds bent 16: its alt bents, "şarttır. ..." (a paragraph of the fıkra) and
    # "Cumhurbaşkanı bu bentte ..." (a fıkra of the article, as the consolidated text has
    # it). Undoing it removes those and nothing else: bent 15, repealed, reads as nothing.
    (op,) = ops_of("7256/16")
    assert [n.level for n in op.new_nodes] == [Level.BENT, Level.PARAGRAF, Level.FIKRA]
    b14 = Node(level=Level.BENT, label="14.", text="1/7/2005 tarihli ve 5378 sayılı ...")
    b15 = Node(level=Level.BENT, label="15.", repealed=True)
    head, tail = op.new_nodes[:2], op.new_nodes[2:]
    law = _md89(b14, b15, *[n.model_copy(deep=True) for n in head],
                after=[n.model_copy(deep=True) for n in tail])
    before = node_lines(law.article("89"))
    assert unapply(law, op).status == "ok"
    md89 = law.article("89")
    assert [c.label for c in md89.children[0].children] == ["14.", "15."]
    assert len(md89.children) == 2
    apply(law, op)
    assert node_lines(law.article("89")) == before
    assert len(law.article("89").children) == 3


def test_bent_replaced_by_unnumbered_text_keeps_its_number():
    # 6552/92 gives the new (10) numaralı bent of md. 89 without its number: it serves
    # 5520 sayılı Kanunun (e) bendi too.
    (op,) = [o for o in ops_of("6552/92") if str(o.target) == "md.89/f1/b10"]
    law = _md89(Node(level=Level.BENT, label="9.", text="..."),
                Node(level=Level.BENT, label="10.", text="Bakanlar Kurulunca yardım ..."))
    apply(law, op)
    b10 = law.article("89").children[0].children[1]
    assert (b10.level, b10.label) == (Level.BENT, "10.")
    assert b10.text.startswith("Başbakanlıkça veya Bakanlar Kurulunca")
    assert unapply(law, op).status == "ok"
    assert law.article("89").children[0].children[1].text == UNKNOWN


def test_operations_before_a_whole_article_replacement_are_superseded():
    # 4842/10 added md. 89/f1/b3 in 2003; 5228/28 rewrote md. 89 in 2004. The bent 4842
    # added is gone, so its failed check means nothing.
    def r(act, op, target, check):
        return OpResult(act=act, article="1", check=check, op=AmendmentOp(
            op=op, target=Addr.model_validate(target), source_sentence=""))
    early = r("4842", OpType.INSERT_NODE, {"madde": "89", "fikra": 1, "bent": "3"}, "fail")
    other = r("4842", OpType.INSERT_NODE, {"madde": "90", "fikra": 1}, "fail")
    whole = r("5228", OpType.REPLACE_NODE, {"madde": "89"}, "superseded")
    later = r("6322", OpType.INSERT_NODE, {"madde": "89", "fikra": 1}, "fail")
    mark_replaced([early, other, whole, later])
    assert [x.check for x in (early, other, whole, later)] == [
        "superseded", "fail", "superseded", "fail"]
    assert early.check_message == "article replaced by 5228 md. 1"

    # An article inserted after md. 89 is not part of it; a replacement whose text was
    # not found proves nothing.
    insert = r("4842", OpType.INSERT_NODE, {"madde": "89"}, "fail")
    insert.op.kind = Level.MADDE
    early = r("4842", OpType.INSERT_NODE, {"madde": "89", "fikra": 1, "bent": "3"}, "fail")
    failed = r("5228", OpType.REPLACE_NODE, {"madde": "89"}, "fail")
    mark_replaced([insert, whole])
    mark_replaced([early, failed])
    assert (insert.check, early.check) == ("fail", "fail")


def test_fikras_of_a_repealed_article_are_not_known():
    # 5479/2 repealed md. 19. Once that is undone, the article's text is not known, so
    # 5228/59 on its "(4) numaralı fıkrasının üçüncü bendi" cannot be checked.
    law = Law(number=193, name="", body=[Node(
        level=Level.MADDE, id="19", label="Madde 19 –", repealed=True,
        text="(Mülga: 30/3/2006-5479/2 md.)")])
    (repeal,) = am.parse_instruction(
        "193 sayılı Kanunun 19 uncu maddesi yürürlükten kaldırılmıştır.", [], 193)
    assert unapply(law, repeal).status == "ok"
    assert law.article("19").text == UNKNOWN
    (op,) = am.parse_instruction(
        "193 sayılı Kanunun 19 uncu maddesinin (4) numaralı fıkrasının üçüncü bendinde yer "
        "alan \"Gayri maddi haklar\" ibaresi \"Gayri maddi haklar ile ekonomik ömrü 5 yıldan "
        "daha kısa olan özel maliyet bedelleri\" şeklinde değiştirilmiştir", [], 193)
    assert unapply(law, op).status == "superseded"


def test_fikra_ordinal_skips_repealed_fikras():
    # Md. 38 in 2001: "(Mülga üçüncü fıkra: 4/12/1985-3239/138 md.)", then the fıkra
    # 3946/8 added, which 4684/17 calls "üçüncü fıkrası".
    law = _article_law("38", "Bilanço esasına göre ticari kazanç, ...",
                       "Ticari kazancın bu suretle tesbit edilmesi sırasında, ...",
                       "(Mülga üçüncü fıkra: 4/12/1985-3239/138 md.)",
                       "Mükelleflerin iktisap tarihinden itibaren ...")
    fikras = law.article("38").children
    fikras[2].repealed = True
    at = Addr(madde="38", fikra=3)
    assert locate(law, at).node is fikras[3]
    # Undoing a repeal ("Mülga üçüncü fıkra") means the repealed one.
    assert locate(law, at, live=False).node is fikras[2]


def test_replacement_does_not_run_into_the_next_word():
    # 6663/3: “, 86 ve mükerrer 121 inci maddelerinde” ibaresi “ve 86 ncı maddeleri ile 89
    # uncu maddesinin birinci fıkrasının (15) numaralı bendinde” (mükerrer 123).
    law = _article_law("123", "Bu Kanunun 19, 21, 23/8, 31, 47, 48, mükerrer 80, 82, 86 ve "
                              "mükerrer 121 inci maddelerinde yer alan maktu had ve tutarlar")
    op = AmendmentOp(op=OpType.REPLACE_PHRASE, target=Addr(madde="123", fikra=1),
                     old=", 86 ve mükerrer 121 inci maddelerinde",
                     new="ve 86 ncı maddeleri ile 89 uncu maddesinin birinci fıkrasının "
                         "(15) numaralı bendinde", source_sentence="")
    apply(law, op)
    assert law.article("123").children[0].text == (
        "Bu Kanunun 19, 21, 23/8, 31, 47, 48, mükerrer 80, 82 ve 86 ncı maddeleri ile 89 uncu "
        "maddesinin birinci fıkrasının (15) numaralı bendinde yer alan maktu had ve tutarlar")


def test_deleted_ibare_goes_back_into_its_mark():
    # 7338/6 removed “, gelirin sadece basit usulde ... akşamına kadar,” from md. 92/1.
    law = _article_law("92", "Bir takvim yılına ait beyanname izleyen yılın Mart ayının "
                             "başından yirmibeşinci günü akşamına kadar (…) tam mükellefiyette")
    old = ("[, gelirin sadece basit usulde tespit edilen ticarî kazançlardan ibaret olması "
           "halinde izleyen yılın Şubat ayının başından yirmibeşinci günü akşamına kadar,]")[1:-1]
    op = AmendmentOp(op=OpType.DELETE_PHRASE, target=Addr(madde="92", fikra=1), old=old,
                     source_sentence="")
    assert unapply(law, op).status == "ok"
    assert law.article("92").children[0].text == (
        "Bir takvim yılına ait beyanname izleyen yılın Mart ayının başından yirmibeşinci günü "
        "akşamına kadar" + old + " tam mükellefiyette")
    # A footnote number may stick to the mark: md. 106/1/b2 after 6728 removed "ücret ve".
    law = _article_law("106", "Gezici olarak çalışanların ticaret ve serbest meslek "
                              "kazançlarının vergileri bu (…)134 kazanç sahiplerinin")
    op = AmendmentOp(op=OpType.DELETE_PHRASE, target=Addr(madde="106", fikra=1),
                     old="ücret ve", source_sentence="")
    assert unapply(law, op).status == "ok"
    assert law.article("106").children[0].text.endswith(
        "vergileri bu ücret ve kazanç sahiplerinin")


def test_bent_added_before_the_words_that_close_the_list():
    # 7394/2 adds bent 6 to md. 66/2, whose bents end in "Bu işleri dolayısiyle serbest
    # meslek erbabı sayılırlar."
    f2 = Node(level=Level.FIKRA, text="Bu maddenin uygulanmasında:", children=[
        Node(level=Level.BENT, label="5.", text="Vergi Usul Kanununun 155 inci maddesinde ..."),
        Node(level=Level.PARAGRAF, text="Bu işleri dolayısiyle serbest meslek erbabı sayılırlar.")])
    law = Law(number=193, name="", body=[Node(
        level=Level.MADDE, id="66", label="Madde 66 –",
        children=[Node(level=Level.FIKRA, text="Serbest meslek faaliyetini ..."), f2])])
    op = AmendmentOp(op=OpType.INSERT_NODE, target=Addr(madde="66", fikra=2), position="end",
                     kind=Level.BENT, source_sentence="", new_nodes=[Node(
                         level=Level.BENT, label="6.",
                         text="5510 sayılı Kanunun ek 10 uncu maddesi uyarınca ...")])
    apply(law, op)
    assert [(c.level, c.label) for c in law.article("66").children[1].children] == [
        (Level.BENT, "5."), (Level.BENT, "6."), (Level.PARAGRAF, "")]
    assert unapply(law, op).status == "ok"
    assert len(law.article("66").children[1].children) == 2


def test_unwind_ignores_the_current_amounts():
    # 7194/11 inserted “(İşverenlerce ... 10 Türk lirasını aşmaması ...)” into md. 23/1/b10;
    # mevzuat.gov.tr writes "10 Türk lirasını (158 TL) aşmaması".
    added = ("(İşverenlerce taşıma hizmeti verilmeyen durumlarda, çalışılan günlere ait bir "
             "günlük ulaşım bedelinin 10 Türk lirasını aşmaması ve buna ilişkin ödemenin toplu "
             "taşıma kartı, bileti veya bu amaçla kullanılan ödeme araçlarının temini şeklinde "
             "yapılması şarttır.)")
    head = ("Hizmet erbabının toplu olarak işyerlerine gidip gelmelerini sağlamak maksadıyla "
            "işverenler tarafından yapılan taşıma giderleri")
    shown = (head + " (Ek parantez içi hüküm:5/12/2019-7194/11 md.) "
             + added.replace("lirasını aşmaması", "lirasını (158 TL) aşmaması") + ";")
    law = Law(number=193, name="", body=[Node(
        level=Level.MADDE, id="23", label="Madde 23 –", children=[Node(
            level=Level.FIKRA, children=[Node(level=Level.BENT, label="10.", text=shown)])])])
    r = OpResult(act="7194", article="11", op=AmendmentOp(
        op=OpType.INSERT_PHRASE, target=Addr(madde="23", fikra=1, bent="10"), new=added,
        anchor="taşıma giderleri", position="after", source_sentence=""))
    old = unwind(law, [[r]])
    assert r.check == "ok"
    assert old.article("23").children[0].children[0].text == head + ";"
