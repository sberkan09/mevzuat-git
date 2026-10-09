"""Faz 2: amendment sentences taken verbatim from Resmî Gazete texts."""

import json
from datetime import date
from pathlib import Path

import pytest

from mevzuat_git import amendments as am
from mevzuat_git.amendment_list import AmendingAct, FootnoteRef, RGRef
from mevzuat_git.fetch import decode_html
from mevzuat_git.model import Law, Level, Node, OpType
from mevzuat_git.model import Path as Addr
from mevzuat_git.replay import apply, resolve, unapply
from mevzuat_git.tree import TABLE_MARK

FIX = Path(__file__).parent / "fixtures"
ARTICLES = json.loads((FIX / "rg_amendment_articles.json").read_text(encoding="utf-8"))


def ops_of(key: str):
    a = ARTICLES[key]
    return am.parse_instruction(a["instruction"], a["payload"], 193)


def targets(ops) -> list[str]:
    return [str(o.target) for o in ops]


# -- addresses ---------------------------------------------------------------------------

@pytest.mark.parametrize(("seg", "expected"), [
    ("193 sayılı Kanunun 25 inci maddesinin değişik (3) numaralı bendi",
     Addr(madde="25", bent="3")),
    (("193 sayılı Kanunun 86 ncı maddesinin birinci fıkrasının (1) numaralı bendinin (c) alt "
     "bendi"), Addr(madde="86", fikra=1, bent="1", alt_bent="c")),
    ("193 sayılı Kanunun mükerrer 81 inci maddesinin yedinci fıkrasına",
     Addr(madde="mukerrer-81", fikra=7)),
    (("193 sayılı Kanunun geçici 67 nci maddesinin (1) numaralı fıkrasının yedinci "
     "paragrafındaki"), Addr(madde="gecici-67", fikra=1, paragraf=7)),
    ("31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 20 nci maddesinin başlığı",
     Addr(madde="20", baslik=True)),
    # 5615/1: the old third fıkra, described by its place after the repealed second one.
    ("mülga ikinci fıkrasından sonra gelen üçüncü fıkrası", Addr(madde="9", fikra=3)),
])
def test_parse_address(seg, expected):
    ctx = Addr(madde="9", fikra=1, bent="6")
    assert am.parse_address(seg, ctx) == expected


def test_address_refers_back():
    ctx = Addr(madde="94", fikra=1, bent="11")
    # 4697/8: "... (11) numaralı bendine aşağıdaki (d) alt bendi ve fıkraya ..."
    assert am.parse_address(" ve fıkraya", ctx) == Addr(madde="94", fikra=1)
    assert am.parse_address("aynı maddenin birinci fıkrasının birinci cümlesinde geçen",
                            ctx) == Addr(madde="94", fikra=1, cumle=1)


def test_expand_targets_lists():
    seg = "193 sayılı Kanunun 19 uncu maddesinin (2) ve (3) numaralı fıkraları"
    path = am.parse_address(seg, None)
    assert [p.fikra for p in am.expand_targets(seg, path)] == [2, 3]
    seg = "193 sayılı Kanunun 94 üncü maddesinin birinci fıkrasının (7), (8), (9) ve (14) " \
          "numaralı bentlerinde"
    path = am.parse_address(seg, None)
    assert [p.bent for p in am.expand_targets(seg, path)] == ["7", "8", "9", "14"]


def test_split_addresses_ignores_quoted_text():
    seg = ("193 sayılı Kanunun 94 üncü maddesinin sekizinci fıkrasına “– Tam ve dar "
           "mükellefler ile gerçek ve tüzel kişiler itibariyle,” paragrafından sonra gelmek "
           "üzere ")
    assert am.split_addresses(seg) == [seg]


# -- operations --------------------------------------------------------------------------

def test_replace_phrase_series_across_articles():
    ops = ops_of("5615/10")
    assert all(o.op is OpType.REPLACE_PHRASE for o in ops)
    assert targets(ops) == ["md.92", "md.92", "md.98", "md.98", "md.mukerrer-120/f2",
                            "md.mukerrer-120/f3", "md.gecici-67/f1/p7", "md.gecici-67/f14"]
    # "...ayın onuncu," ve üçüncü fıkrasında: the pair ends at "ve", not at "olarak".
    assert ops[4].old.endswith("ikinci ayın onuncu,")
    assert ops[4].new.endswith("ikinci ayın ondördüncü,")
    assert ops[5].old == "dönemi izleyen ikinci ayın onuncu günü akşamına kadar"
    # The KDV Kanunu change at the end of the sentence is not ours.
    assert not any(o.old == "yirminci günü" for o in ops)


def test_phrase_ops_with_two_addresses():
    ops = ops_of("6322/11")
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.REPLACE_PHRASE, "md.gecici-67/f1/p6"),
        (OpType.REPLACE_PHRASE, "md.gecici-67/f2"),
        (OpType.REPLACE_PHRASE, "md.gecici-67/f7"),
        (OpType.INSERT_PHRASE, "md.gecici-67/f17"),
        (OpType.INSERT_PHRASE, "md.gecici-67/f17"),
    ]
    assert ops[0].all and ops[0].old == "Hazine"
    assert (ops[3].anchor, ops[3].position, ops[3].new) == (
        "bunları elde edenler", "before", "bunların vadesi ve")


def test_insert_phrase_after():
    (op,) = ops_of("6645/8")
    assert (op.op, str(op.target)) == (OpType.INSERT_PHRASE, "md.32/f2")
    assert (op.anchor, op.position, op.new) == (
        "ilk iki çocuk için %7,5", "after", ", üçüncü çocuk için %10,")


def test_delete_phrase_and_repeal():
    ops = ops_of("7338/5")
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.DELETE_PHRASE, "md.89/f1/b3"), (OpType.REPEAL_NODE, "md.89/f1/b15")]
    assert ops[0].old == "veya basit usulde vergilendirilen"


def test_insert_paragraph_after_quoted_anchor():
    (op,) = ops_of("7491/11")
    assert (op.op, op.kind, op.position, str(op.target)) == (
        OpType.INSERT_NODE, Level.PARAGRAF, "after", "md.94/f8")
    assert op.new.startswith("– 3 numaralı bent kapsamında")
    assert op.anchor == "– Tam ve dar mükellefler ile gerçek ve tüzel kişiler itibariyle,"


def test_two_inserts_split_by_restarting_labels():
    # Unquoted: "d)" belongs to the first insertion, "15. a) ... b) ... c)" to the second.
    ops = ops_of("4697/8")
    assert [(o.kind, str(o.target)) for o in ops] == [
        (Level.ALT_BENT, "md.94/f1/b11"), (Level.BENT, "md.94/f1")]
    assert [n.label for n in ops[0].new_nodes] == ["d)"]
    (b15,) = ops[1].new_nodes
    assert b15.label == "15." and [c.label for c in b15.children] == ["a)", "b)", "c)"]


def test_insert_then_replace_with_unquoted_text():
    ops = ops_of("4697/4")
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.INSERT_NODE, "md.40/f1"), (OpType.REPLACE_NODE, "md.63/b2"),
        (OpType.REPLACE_NODE, "md.63/b3")]
    assert [n.label for n in ops[0].new_nodes] == ["9."]
    assert [n.label for n in ops[1].new_nodes] == ["2."]
    # The closing paragraph continues bent 3.
    (b3,) = ops[2].new_nodes
    assert b3.label == "3." and b3.children[0].text.startswith("İndirim konusu")


def test_fikra_list_split_by_labels():
    ops = ops_of("5024/6")
    assert targets(ops) == ["md.19/f2", "md.19/f3"]
    assert [len(o.new_nodes) for o in ops] == [2, 2]


def test_alt_bent_and_fikra_in_one_operation():
    ops = ops_of("4842/12")
    assert targets(ops) == ["md.94/f1/b6/abb", "md.94/f4"]
    (b,) = ops[0].new_nodes
    assert b.label == "b)" and [c.label for c in b.children] == ["i)", "ii)", "iii)"]
    (f4,) = ops[1].new_nodes
    assert f4.level is Level.FIKRA and f4.text.startswith("Bu maddenin (6) numaralı")


def test_three_payload_ops_split_by_quotes():
    ops = ops_of("6322/4")
    assert [(o.op, o.position, str(o.target)) for o in ops] == [
        (OpType.REPLACE_NODE, None, "md.9/f1/b8"),
        (OpType.INSERT_NODE, "end", "md.9/f1"),
        (OpType.INSERT_NODE, "before", "md.9/f-1"),
    ]
    assert ops[1].new_nodes[0].label == "9."
    assert ops[2].new_nodes[0].text.startswith("Esnaf muaflığına")


def test_insert_unlabelled_alt_bents():
    (op,) = ops_of("5035/14")
    assert (op.kind, op.position, str(op.target)) == (
        Level.ALT_BENT, "after", "md.89/f1/b2/ab2")
    assert len(op.new_nodes) == 2


def test_ibare_removed_with_another_law_is_not_a_repeal():
    # 5661/3: the ibare goes; "6964 sayılı ... Kanununun ek 2 nci maddesi" is not ours.
    ops = ops_of("5661/3")
    assert [(o.op, str(o.target)) for o in ops] == [(OpType.DELETE_PHRASE, "md.53/f-1")]
    assert ops[0].old.startswith("ve Ziraat Odasından")


def test_parenthetical_removed_is_not_a_repeal():
    (op,) = ops_of("7491/9")
    assert (op.op, op.paren, op.new, str(op.target)) == (
        OpType.REPLACE_PHRASE, True, "", "md.40/f1/b1")


def test_repeal_list_with_mixed_addresses():
    ops = ops_of("7349/3/32")
    assert all(o.op is OpType.REPEAL_NODE for o in ops)
    assert targets(ops) == ["md.32", "md.64", "md.108/f1/b3", "md.109/f1/b2", "md.109/f2",
                            "md.109/f3", "md.110", "md.118", "md.122"]


def test_bent_list_then_fikra():
    ops = ops_of("7194/18")
    assert targets(ops) == ["md.mukerrer-121/f2/b1", "md.mukerrer-121/f2/b3",
                            "md.mukerrer-121/f5"]
    assert all(o.new_nodes for o in ops)


def test_paragraph_and_fikra_list_then_parenthetical_insert():
    ops = ops_of("7566/3")
    assert targets(ops)[:3] == ["md.gecici-67/f1/p6", "md.gecici-67/f8", "md.gecici-67/f17"]
    last = ops[-1]
    assert (last.op, last.position, str(last.target)) == (
        OpType.INSERT_PHRASE, "after", "md.gecici-67/f1/p6")
    assert last.anchor.startswith("sürekli olarak portföyünün")
    assert last.new.startswith("(Katılma payları")


def test_insert_phrase_series_joined_by_ve():
    ops = ops_of("7578/1/89")
    assert [(str(o.target), o.anchor) for o in ops] == [
        ("md.89/f1/b6", "faaliyetinde bulunan"), ("md.89/f1/b11", "işletmeleri hariç,")]


def test_fikra_and_article_inserted_in_one_sentence():
    ops = ops_of("5838/8")
    assert [(o.kind, o.position, str(o.target)) for o in ops] == [
        (Level.FIKRA, "end", "md.119"), (Level.MADDE, "after", "md.gecici-74")]
    assert ops[1].new_nodes[0].id == "gecici-75"


def test_title_and_fikra_replaced_together():
    ops = ops_of("7491/7")
    assert [str(o.target) for o in ops] == ["md.mukerrer-20/B/başlık", "md.mukerrer-20/B/f1"]
    assert ops[0].new.startswith("Sosyal içerik üreticiliği")


def test_numbered_insert_with_teselsul_goes_to_its_place():
    ops = ops_of("6728/11")
    assert [(o.op, o.position, str(o.target)) for o in ops] == [
        (OpType.REPLACE_NODE, None, "md.22/f1"), (OpType.INSERT_NODE, "after", "md.22/f1")]
    assert ops[1].renumber


def test_mevcut_fikra_counts_before_the_insert():
    # 7587/5: birinci fıkrasından sonra ... fıkra eklenmiş, mevcut ikinci fıkrasında ...
    # mevcut beşinci fıkrasında: once the insert is made, those are the third and sixth.
    ops = ops_of("7587/5")
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.INSERT_NODE, "md.113/f1"), (OpType.REPLACE_PHRASE, "md.113/f3"),
        (OpType.REPLACE_PHRASE, "md.113/f6")]


def test_plural_word_inside_the_ibare_is_not_plural():
    (op,) = ops_of("5035/48/Geçici")
    assert op.old == "1.1.1999 - 31.12.2003 tarihleri arasında"
    # Not plural, but the target is a whole article: every occurrence in it (see
    # test_ibare_of_a_whole_article_is_every_occurrence).
    assert str(op.target) == "md.gecici-55" and op.all
    op = am.parse_instruction(
        "3065 sayılı Kanunun 41 inci maddesinin (1) numaralı fıkrasında yer alan “1.1.1999 - "
        "31.12.2003 tarihleri arasında” ibaresi “x” şeklinde değiştirilmiştir.", [], 3065)[0]
    assert not op.all


def test_ibare_of_a_whole_article_is_every_occurrence():
    # 5615/10: "3065 sayılı Katma Değer Vergisi Kanununun 41 inci maddesinde yer alan
    # "yirminci günü" ibaresi "yirmidördüncü günü" olarak değiştirilmiştir"; md. 41 has it
    # in its first and fourth fıkras, both changed.
    (op,) = am.parse_instruction(
        "25/10/1984 tarihli ve 3065 sayılı Katma Değer Vergisi Kanununun 41 inci maddesinde "
        "yer alan \"yirminci günü\" ibaresi \"yirmidördüncü günü\" olarak değiştirilmiştir.",
        [], 3065)
    assert str(op.target) == "md.41" and op.all


def test_ordinal_bent():
    (op,) = ops_of("5228/59/üçüncü")
    assert str(op.target) == "md.19/f4/b3"


# -- whole acts --------------------------------------------------------------------------

def test_list_article_with_verbs_per_item():
    # 5527/1: "geçici 67 nci maddesinin;" then a) ... e), each with its own verb and text.
    a = ARTICLES["5527/1"]
    items = am.expand_list(am.ActArticle("1", a["instruction"], a["payload"]))
    assert len(items) == 6
    assert items[0].payload == [("\"Dar mükellef gerçek kişi ve kurumlar için bu oran % 0 "
                                "olarak uygulanır.\"")]
    ops = [o for it in items for o in am.parse_instruction(it.instruction, it.payload, 193)]
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.INSERT_NODE, "md.gecici-67/f1/p1"),
        (OpType.REPLACE_NODE, "md.gecici-67/f1/p6"),
        (OpType.INSERT_NODE, "md.gecici-67/f7/c2"),
        (OpType.REPLACE_PHRASE, "md.gecici-67/f8"),
        (OpType.DELETE_PHRASE, "md.gecici-67/f14/c2"),
        (OpType.INSERT_NODE, "md.gecici-67/f16"),
    ]
    assert ops[3].paren and ops[3].new.startswith("(borsa yatırım fonları")
    assert ops[5].renumber


def test_list_item_payload_keeps_its_own_items():
    # 5766/8 ç): the new geçici madde 72 has a) and b) of its own, inside the quotes.
    a = ARTICLES["5766/8"]
    items = am.expand_list(am.ActArticle("8", a["instruction"], a["payload"]))
    assert [it.instruction.split("Kanununun ")[1][:10] for it in items] == [
        "9 uncu mad", "29 uncu ma", "42 nci mad", "Geçici 71 "]
    ops = am.parse_instruction(items[3].instruction, items[3].payload, 193)
    (op,) = [o for o in ops if o.op is OpType.INSERT_NODE]
    (g72,) = op.new_nodes
    assert g72.id == "gecici-72" and len(g72.children) == 4


def test_parse_act_5615():
    html = decode_html((FIX / "rg_20070404-2_5615_excerpt.htm").read_bytes())
    res = am.parse_act(html, "5615", 193)
    assert not res.unparsed
    assert [(a.article, targets(a.ops)) for a in res.amendments] == [
        ("1", ["md.9/f1/b6", "md.9/f3"]),
        ("2", ["md.32"]),
        ("3", ["md.41/f1/b4"]),
        ("31", ["md.mukerrer-121"]),
    ]
    # md. 32 is quoted with '"' and contains "MADDE 32 –": it stays in article 2.
    (op,) = res.amendments[1].ops
    (m32,) = op.new_nodes
    assert op.with_title and m32.title == "Asgarî geçim indirimi" and len(m32.children) > 3
    # Bent 5's unlabelled paragraphs stay with it.
    (b5,) = res.amendments[2].ops[0].new_nodes
    assert b5.label == "5." and len(b5.children) == 3
    assert res.amendments[2].ops[0].renumber


def test_quote_balance_ascii():
    assert am._quote_balance('"Asgarî geçim indirimi') == 1
    assert am._quote_balance('hükmü uygulanır."') == -1
    assert am._quote_balance('"dört yıl içinde" ibaresi') == 0


# -- operations from the consolidated text's footnotes (acts whose RG text is a PDF) ------

# GVK md. 94/9 on mevzuat.gov.tr (footnote 129).
MD94_F9 = ("Cumhurbaşkanı, bu maddede yer alan tevkifat nispetini, kara, deniz ve hava "
           "ulaştırması işiyle iştigal eden dar mükellefler için, ülkeler itibariyle ve "
           "karşılıklı olmak şartıyla sıfıra kadar indirmeye yetkilidir.")


def _footnote_law():
    def fikra(text, fn=(), children=()):
        return Node(level=Level.FIKRA, text=text, footnotes=list(fn), children=list(children))
    md41 = Node(level=Level.MADDE, id="41", label="Madde 41 –", footnotes=[43], children=[
        fikra("Aşağıdaki giderler ...", children=[
            Node(level=Level.BENT, label="7.", text="Bakanlar Kurulu kararı ile ..."),
            Node(level=Level.BENT, label="9.", text="Bakanlar Kurulunca belirlenen ...",
                 children=[Node(level=Level.PARAGRAF, text="Bakanlar Kurulu ...")])])])
    md94 = Node(level=Level.MADDE, id="94", label="Madde 94 –", children=[
        fikra(f"fıkra {i}") for i in range(1, 9)] + [fikra(MD94_F9, fn=[129])])
    return Law(number=193, name="", body=[md41, md94])


FOOTNOTES_700 = [
    (43, "41", ("2/7/2018 tarihli ve 700 sayılı KHK’nin 45 inci maddesiyle, bu fıkranın (7) "
                "numaralı bendinde yer alan “Bakanlar Kurulu” ibaresi “Cumhurbaşkanı” şeklinde, "
                "(9) numaralı bendinde yer alan “Bakanlar Kurulunca” ibaresi “Cumhurbaşkanınca” "
                "şeklinde, aynı bendin ikinci paragrafında yer alan “Bakanlar Kurulu” ibaresi "
                "“Cumhurbaşkanı” şeklinde değiştirilmiştir.")),
    (129, "94", ("2/7/2018 tarihli ve 700 sayılı KHK’nin 45 inci maddesiyle, bu fıkrada yer "
                 "alan “Bakanlar Kurulu” ibaresi “Cumhurbaşkanı” şeklinde değiştirilmiştir.")),
]


def test_operations_from_footnotes():
    act = AmendingAct(kind="khk", number="700", footnotes=[
        FootnoteRef(footnote=n, article=a, law_article="45", text=t) for n, a, t in FOOTNOTES_700])
    ams, unparsed = am.ops_from_footnotes(act, _footnote_law())
    assert not unparsed
    (a,) = ams
    assert a.article == "45"
    assert [(str(o.target), o.old, o.new) for o in a.ops] == [
        ("md.41/b7", "Bakanlar Kurulu", "Cumhurbaşkanı"),
        ("md.41/b9", "Bakanlar Kurulunca", "Cumhurbaşkanınca"),
        ("md.41/b9/p2", "Bakanlar Kurulu", "Cumhurbaşkanı"),
        ("md.94/f9", "Bakanlar Kurulu", "Cumhurbaşkanı")]


def test_footnote_operation_follows_its_node():
    # "bu fıkrada" is md. 94's ninth fıkra today. Before a later act added a fıkra in
    # front of it, it was the eighth: the operation goes where the footnote's node is.
    act = AmendingAct(kind="khk", number="700", footnotes=[
        FootnoteRef(footnote=129, article="94", law_article="45", text=FOOTNOTES_700[1][2])])
    law = _footnote_law()
    (a,), _ = am.ops_from_footnotes(act, law)
    (op,) = a.ops
    del law.article("94").children[2]
    assert unapply(law, op).status == "ok"
    assert law.article("94").children[7].text.startswith("Bakanlar Kurulu, bu maddede")
    assert str(resolve(law, op).target) == "md.94/f8"


def test_alt_bent_of_bent_in_context():
    # 700/45 footnote on md. 9/f1/b6/a: "(b) alt bendinde" names an alt bent of the same bent.
    assert str(am.parse_address(" (b) alt bendine ",
                                Addr(madde="9", fikra=1, bent="6", alt_bent="a"))) == "md.9/f1/b6/abb"


def test_footnote_path_keeps_only_inherited_parts():
    # "(9) numaralı bendinde" names the bent itself; only the fıkra-less article comes
    # from the footnote's node, so a rebase must not move the bent.
    act = AmendingAct(kind="khk", number="700", footnotes=[
        FootnoteRef(footnote=n, article=a, law_article="45", text=t) for n, a, t in FOOTNOTES_700])
    (a,), _ = am.ops_from_footnotes(act, _footnote_law())
    named, inherited = a.ops[1], a.ops[3]
    assert named.footnote_path.bent is None
    assert inherited.footnote_path.fikra == 9


def _items(key: str) -> list[am.ActArticle]:
    a = ARTICLES[key]
    return am.expand_list(am.ActArticle(key.split("/")[1], a["instruction"], a["payload"]))


def _ops(items: list[am.ActArticle]) -> list:
    return [o for it in items if am.mentions(it.instruction, 193)
            for o in am.parse_instruction(it.instruction, it.payload, 193)]


def test_list_with_verb_after_olarak():
    # 5281/43: groups for many laws, "Olarak değiştirilmiştir." once at the end.
    ops = _ops(_items("5281/43"))
    assert [(str(o.target), o.old) for o in ops][:4] == [
        ("md.40/f1/b10", "gıda maddelerinin"),
        ("md.48/f2", ("Tekele tabi maddelerle, damga pulu, milli piyango bileti, akaryakıt, "
                      "şeker ve bunlar gibi")),
        ("md.89/f1/b2", "gelirin % 5'ini aşmaması"),
        ("md.89/f1/b6", "gıda maddelerinin")]
    assert ops[2].new == "gelirin % 10'unu aşmaması"


def test_list_item_with_numbered_sub_items():
    # 6728/15 b): "(13) numaralı bendinin;" then "1) Birinci cümlesinde ...".
    ops = _ops(_items("6728/15"))
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.REPEAL_NODE, "md.89/f1/b9"),
        (OpType.REPLACE_PHRASE, "md.89/f1/b13/c1"),
        (OpType.INSERT_PHRASE, "md.89/f1/b13/c3")]
    assert ops[2].new == "ve kazanç tutarları" and ops[2].anchor == "hizmet alanları"


def test_list_items_naming_their_own_laws():
    # 5436/14: "a) 375 sayılı KHK’ye ... eklenmiştir." with an unquoted new article, then
    # "b) 193 sayılı ... aşağıdaki bent eklenmiştir." with the unquoted bent "10. ...".
    # Item d) has sub-items 1) to 10); "15) Kurumlar Vergisi Kanununun ..." after 9) and
    # "f) Bakanlar Kurulunca ..." after c) are new texts, not items.
    items = _items("5436/14")
    assert [it.instruction[:2] for it in items] == ["27", "31", "3."] + ["31"] * 10 + ["5."]
    assert items[2].payload[0].startswith("f) Bakanlar Kurulunca")
    assert items[11].payload[0].startswith("15) Kurumlar Vergisi Kanununun")
    assert items[12].payload[0].startswith("17) Bu madde hükümlerinin")
    op = _ops(items[1:2])[0]
    assert op.op is OpType.INSERT_NODE and str(op.target) == "md.89/f1"
    assert [n.label for n in op.new_nodes] == ["10."]


def test_list_with_lettered_groups():
    # 4962/17: "A) 213 sayılı ...;" a) b) c), "B) 6183 sayılı ...;" a) b), C) to F),
    # "Değiştirilmiştir." The 6183 items stay under 6183.
    items = _items("4962/17")
    assert [it.instruction.split(" sayılı")[0][-3:] for it in items] == [
        "213", "213", "213", "183", "183", "492", "193", "193", "422"]
    ops = _ops(items)
    assert [(str(o.target), o.paren) for o in ops] == [
        ("md.86/f1/b1/abb", True), ("md.89/f1/b2", False)]
    assert ops[0].new.startswith("(birden fazla işverenden ücret almakla beraber")


def test_list_items_sharing_one_verb():
    # 6353/65: "193 sayılı Gelir Vergisi Kanununun;" a) b) "değiştirilmiştir."
    items = _items("6353/65")
    assert [it.instruction.split("Kanununun ")[1][:8] for it in items] == ["75 inci ", "94 üncü "]
    assert all(it.instruction.endswith("değiştirilmiştir") for it in items)


def test_renumbered_bent():
    # 6353/65: "... 6322 sayılı Kanunun 8 inci maddesi ile eklenen bendin “16.” olan numarası
    # “17.” olarak değiştirilmiştir"; the act that added the bent is not a target, and "bu
    # bendin" is the bent under its new number.
    a, b = _ops(_items("6353/65"))[:1], _ops(_items("6353/65"))[1:]
    assert [(o.op, str(o.target), o.old, o.new) for o in a] == [
        (OpType.RELABEL_NODE, "md.75/f2/b16", "16.", "17.")]
    assert [(o.op, str(o.target), o.old, o.new) for o in b] == [
        (OpType.RELABEL_NODE, "md.94/f1/b16", "16.", "17."),
        (OpType.REPLACE_PHRASE, "md.94/f1/b17", "(16)", "(17)"),
        (OpType.REPLACE_PHRASE, "md.94/f6", "6, 7, 8, 9 ve 16 numaralı",
         "6, 7, 8, 9 ve 17 numaralı")]


def test_new_text_inline():
    # 5436/14 d): "1) (1) numaralı fıkrasının ikinci paragrafı "Aynı menkul ..." şeklinde
    # değiştirilmiştir.", "6) (10) numaralı fıkrasından sonra gelmek üzere "11) Dar
    # mükellefler ..." şeklinde bir fıkra eklenmiş ve takip eden fıkra numaraları teselsül
    # ettirilmiştir."
    ops = {str(o.target): o for o in _ops(_items("5436/14")[3:])}
    p2 = ops["md.gecici-67/f1/p2"]
    assert p2.op is OpType.REPLACE_NODE and p2.new.startswith("Aynı menkul kıymet")
    assert p2.new.endswith("tevkifat matrahının tespitinde dikkate alınır.")
    f4 = ops["md.gecici-67/f4"]
    assert f4.op is OpType.REPLACE_NODE and f4.new_nodes[0].text.startswith("Bankalar arası")
    f10 = ops["md.gecici-67/f10"]
    assert (f10.op, f10.position, f10.renumber) == (OpType.INSERT_NODE, "after", True)
    assert [n.label for n in f10.new_nodes] == ["11)"]
    assert ops["md.gecici-67/f13"].new_nodes[0].text.startswith("Türkiye'de kurulu vadeli")


def test_new_text_inline_in_a_series():
    # 6009/39 on law 5345: the bent's new text, then ibare changes in other bents.
    text = ("5345 sayılı Kanunun 13 üncü maddesinin birinci fıkrasının (c) bendi “c) Vergi "
            "İnceleme ve Denetim Koordinasyon Kurulunun sekreterya hizmetlerini yürütmek.” "
            "şeklinde, (f) bendinde yer alan “Başkanlığın vergi inceleme ve denetim yıllık "
            "planına uygun olarak” ibaresi “Yıllık vergi inceleme ve denetim planına uygun "
            "olarak” şeklinde, (j) bendinde yer alan “Mükelleflerin” ibaresi “Risk Analiz "
            "Sistemi üzerinden mükelleflerin” şeklinde değiştirilmiş ve (d) bendi yürürlükten "
            "kaldırılmıştır.")
    ops = am.parse_instruction(text, [], 5345)
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.REPLACE_NODE, "md.13/f1/bc"), (OpType.REPLACE_PHRASE, "md.13/f1/bf"),
        (OpType.REPLACE_PHRASE, "md.13/f1/bj"), (OpType.REPEAL_NODE, "md.13/f1/bd")]
    assert [n.label for n in ops[0].new_nodes] == ["c)"]


def test_inline_new_text_stops_at_a_quoted_ibare():
    # The shape of 5436/14 d) 6) after an ibare insert: the inline fıkra does not start at
    # the inserted ibare's quote.
    ops = am.parse_instruction(
        "193 sayılı Kanunun 40 ıncı maddesinin birinci fıkrasında yer alan “Gelir” ibaresinden "
        "sonra gelmek üzere “ve kurumlar” ibaresi eklenmiş, (5) numaralı fıkrasından sonra "
        "gelmek üzere “6) Yeni fıkra metni.” şeklinde bir fıkra eklenmiştir.", [], 193)
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.INSERT_PHRASE, "md.40/f1"), (OpType.INSERT_NODE, "md.40/f5")]
    # Only a bent or fıkra "olan numarası", not a fıkra's own bent or an alt bent.
    assert am.parse_instruction("193 sayılı Kanunun 40 ıncı maddesinin ikinci fıkrasının "
                                "“16.” olan numarası “17.” olarak değiştirilmiştir.", [], 193) == []


def test_article_heading_with_figure_dash():
    # 6525/5 writes "MADDE 5 ‒" with U+2012.
    (a,) = am.act_articles([(
        "MADDE 5 ‒ 31/12/1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 89 uncu maddesinin "
        "birinci fıkrasının (5) numaralı bendinde yer alan “Diyanet İşleri Başkanlığı "
        "denetiminde yaygın din eğitimi verilen tesislerin” ibaresinden sonra gelmek üzere “ve "
        "Gençlik ve Spor Bakanlığına ait gençlik merkezleri ile gençlik ve izcilik kamplarının” "
        "ibaresi eklenmiştir.")])
    (op,) = am.parse_instruction(a.instruction, a.payload, 193)
    assert a.number == "5" and str(op.target) == "md.89/f1/b5"
    assert op.anchor == "Diyanet İşleri Başkanlığı denetiminde yaygın din eğitimi verilen tesislerin"


def test_operations_from_change_markers():
    # 6663 (a scanned PDF) added md. 89/f1/b15, which 7338 repealed; only the marker
    # "(Ek: 29/1/2016-6663/2 md.)" is left of it.
    b14 = Node(level=Level.BENT, label="14.", text="1/7/2005 tarihli ve 5378 sayılı ...")
    b15 = Node(level=Level.BENT, label="15.", repealed=True, notes=[
        "(Ek: 29/1/2016-6663/2 md.)", "(Mülga:14/10/2021-7338/5 md.)"])
    md89 = Node(level=Level.MADDE, id="89", label="Madde 89 –", children=[
        Node(level=Level.FIKRA, text="Gelir vergisi matrahının tespitinde", children=[b14, b15])])
    act = AmendingAct(kind="kanun", number="6663")
    (a,) = am.ops_from_markers(act, Law(number=193, name="", body=[md89]))
    (op,) = a.ops
    assert a.article == "2"
    assert (op.op, str(op.target), op.position) == (OpType.INSERT_NODE, "md.89/f1/b14", "after")
    assert op.new_nodes[0].label == "15." and not op.new_nodes[0].repealed
    # A footnote of the act on the node says it already: no second insertion.
    b15.footnotes = [7]
    act.footnotes = [FootnoteRef(footnote=7, article="89", law_article="2", text="...")]
    assert am.ops_from_markers(act, Law(number=193, name="", body=[md89])) == []


def test_act_on_a_day_page_ends_at_the_next_act():
    # RG 3/7/2001: 4684's header comes twice (a table and its cell); 4689 follows.
    paras = [
        "Kanun No. 4684 Kabul Tarihi : 20.6.2001",
        f"{TABLE_MARK}Kanun No. 4684 | Kabul Tarihi : 20.6.2001",
        ("MADDE 17. — 31.12.1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun 38 inci "
         "maddesinin üçüncü fıkrası aşağıdaki şekilde değiştirilmiştir."),
        f"{TABLE_MARK}Kanun No. 4689 | Kabul Tarihi : 26.6.2001",
        ("MADDE 1. – 4.11.1981 tarihli ve 2547 sayılı Yükseköğretim Kanununun 48 inci "
         "maddesi başlığıyla birlikte aşağıdaki şekilde değiştirilmiştir.")]
    assert [a.number for a in am.act_articles(paras, "4684")] == ["17"]


def test_numbered_fikras_amending_different_laws():
    # 5838/32: "(1) 4447 sayılı ...", "(2) 5510 sayılı ...:" a) b) c), ..., "(5) 193 sayılı
    # Gelir Vergisi Kanununun 99 uncu maddesinde yer alan ..." each with its own verb.
    items = _items("5838/32")
    assert [it.instruction[:3] for it in items] == [f"({n})" for n in range(1, 8)]
    assert items[1].payload[0].startswith("a) 5 inci maddesinin")
    (op,) = _ops(items)
    assert (op.op, str(op.target)) == (OpType.REPLACE_PHRASE, "md.99")
    assert op.old == "Muhtasar beyannamenin şekil, içerik ve eklerini belirlemeye"


def test_lettered_items_naming_laws_with_one_verb():
    # 5024/9: "a) ... 213 sayılı ...,", "b) ... 193 sayılı ...; 38 inci maddesinin dördüncü
    # ve beşinci fıkraları ile ...,", "c) ...", "Yürürlükten kaldırılmıştır."
    ops = _ops(_items("5024/9"))
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.REPEAL_NODE, "md.38/f4"), (OpType.REPEAL_NODE, "md.38/f5"),
        (OpType.REPEAL_NODE, "md.41/f1/b8"), (OpType.REPEAL_NODE, "md.57/f-1")]


def test_sonraki_bent_is_the_one_after_the_added_bent():
    # 5766/8 a): "(6) numaralı bentten sonra gelmek üzere aşağıdaki bent eklenmiş ve
    # sonraki bentte yer alan "1-6 numaralı" ibaresi ..." The old (7) is (8) by then.
    items = _items("5766/8")
    ops = am.parse_instruction(items[0].instruction, items[0].payload, 193)
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.INSERT_NODE, "md.9/f1/b6"), (OpType.REPLACE_PHRASE, "md.9/f1/b8")]


def test_second_pair_with_ise():
    # 5281/43 f): "“31.12.2006 tarihine kadar” ibaresi “31.12.2007 tarihine kadar” ve
    # “26.7.2001-31.12.2004 tarihleri arasında” ibaresi ise “...2005 ...”"
    ops = [o for o in _ops(_items("5281/43")) if o.target.madde == "gecici-59"]
    assert [(o.old, o.new) for o in ops] == [
        ("31.12.2006 tarihine kadar", "31.12.2007 tarihine kadar"),
        ("26.7.2001-31.12.2004 tarihleri arasında", "26.7.2001-31.12.2005 tarihleri arasında")]


def test_insert_phrase_series_with_ibaresi_between_pairs():
    # 7194/19: "“23/8,” ibaresinden sonra gelmek üzere “23/10,” ibaresi, “31,” ibaresinden
    # sonra gelmek üzere “40/1, 40/7,” ibaresi ve “48,” ibaresinden sonra ... eklenmiştir."
    ops = ops_of("7194/19")
    assert [(o.anchor, o.new) for o in ops] == [
        ("23/8,", "23/10,"), ("31,", "40/1, 40/7,"), ("48,", "68,")]
    assert {str(o.target) for o in ops} == {"md.mukerrer-123/f2"}


def test_numbered_fikras_of_the_act_own_are_not_amendments():
    # 7440/10 (2): the act's own rule, which only mentions 193 sayılı Kanun.
    a = am.ActArticle("10", (
        "(1) Hazine ve Maliye Bakanlığına bağlı tahsil dairelerince 6183 sayılı Kanuna göre "
        "takip edilen alacaklardan ... tahsilinden vazgeçilir."), [(
        "(2) Bu Kanunun 3 üncü ve 4 üncü maddelerine göre yapılandırılarak kesinleşen "
        "tarhiyatlar, yapılandırmanın ihlal edilmemesi şartıyla 193 sayılı Kanunun mükerrer "
        "121 inci maddesinin ikinci fıkrasının (2) numaralı bendi kapsamında "
        "değerlendirilmez.")])
    assert am.expand_list(a) is None


def test_sentences_added_after_the_replaced_ibare():
    # 6009/5: "... ibaresi “...” şeklinde değiştirilmiş ve bu ibareden sonra gelmek üzere
    # “Şu kadar ki, ...” cümleleri eklenmiştir."
    replace, insert = ops_of("6009/5")
    assert replace.op is OpType.REPLACE_PHRASE and str(replace.target) == "md.gecici-69/f1"
    assert insert.op is OpType.INSERT_PHRASE and insert.position == "after"
    assert insert.anchor == replace.new and insert.target == replace.target
    assert insert.new.startswith("Şu kadar ki, vergi matrahlarının")
    assert insert.new.endswith("vergi oranına göre vergi hesaplanır.")


# -- Anayasa Mahkemesi decisions ---------------------------------------------------------

AYM_2026_43 = ("Anayasa Mahkemesinin 12/2/2026 tarihli ve E.: 2025/219, K.: 2026/43 sayılı "
               "Kararı ile bu fıkranın üçüncü cümlesinde yer alan “tevkifat yapmakla sorumlu "
               "olanlarca vergi dairesine ödenmiş olması şartıyla,” ibaresi iptal edilmiştir.")
# GVK footnotes 167 (geçici 58) and 207 (geçici 73).
AYM_2003_3 = ("Bu arada yer alan “gelir” ibaresi, Anayasa Mahkemesinin 16/1/2003 tarihli ve "
              "E.:2001/36, K.:2003/3 sayılı Kararı ile iptal edilmiştir.")
AYM_2011_172 = ("Bu madde; Anayasa Mahkemesi’nin 22/12/2011 tarihli ve E.: 2010/7, K.: 2011/172 "
                "sayılı Kararı ile, 6/6/2008 tarihinden önce 29/1/2004 tarihli ve 5084 sayılı "
                "Kanun’un 3 üncü maddesi kapsamında yatırıma başlayarak gelir vergisi stopajı "
                "teşvikinden faydalanması gereken mükellefler yönünden iptal edilmiştir.")


def _aym_law():
    md72 = Node(level=Level.MADDE, id="gecici-72", label="Geçici Madde 72 –", children=[
        Node(level=Level.FIKRA, label="(1)", text="31/12/2028 tarihine kadar ..."),
        Node(level=Level.FIKRA, label="(2)", footnotes=[206], text=(
            "Bu ödemeler üzerinden 94 üncü madde kapsamında ayrıca tevkifat yapılmaz. Bu madde "
            "kapsamındaki gelirler toplamının, 103 üncü maddede yazılı tarifenin dördüncü "
            "diliminde yer alan tutarı aşması hâlinde, bu gelirler yıllık beyannameyle beyan "
            "edilir. Yıllık beyanname verilmesi durumunda, beyan edilen bu gelirler üzerinden "
            "hesaplanan gelir vergisinden, (…) bu Kanuna göre kesilen vergiler mahsup edilir."))])
    md58 = Node(level=Level.MADDE, id="gecici-58", label="Geçici Madde 58 –", children=[
        Node(level=Level.FIKRA, children=[Node(
            level=Level.BENT, label="5)", footnotes=[167], text=(
                "Mükellefler; kendilerine, eşlerine ve çocuklarına ait ve üzerinden (…) vergisi "
                "ödenen gelirleri ..."))])])
    md73 = Node(level=Level.MADDE, id="gecici-73", label="Geçici Madde 73 –", footnotes=[207],
                children=[Node(level=Level.FIKRA, text="...")])
    return Law(number=193, name="", body=[md58, md72, md73])


def _aym(number, footnotes, rg=None):
    return AmendingAct(kind="aym", number=number, rg=rg, footnotes=[
        FootnoteRef(footnote=n, article=a, text=t) for n, a, t in footnotes])


def test_annulment_from_a_footnote():
    # The RG text of E.2025/219, K.2026/43 (RG 3/6/2026) is a PDF.
    rg = RGRef(date=date(2026, 6, 3), number="33269", source="resmigazete.gov.tr")
    act = _aym("E.2025/219, K.2026/43", [(206, "gecici-72", AYM_2026_43)], rg)
    (a,), unparsed = am.ops_from_footnotes(act, _aym_law())
    assert not unparsed
    (op,) = a.ops
    assert op.op is OpType.DELETE_PHRASE and str(op.target) == "md.gecici-72/f2/c3"
    assert op.old == "tevkifat yapmakla sorumlu olanlarca vergi dairesine ödenmiş olması şartıyla,"
    assert a.effective_date == date(2026, 6, 3)
    # The decision's name may come after the ibare.
    act = _aym("E.2001/36, K.2003/3", [(167, "gecici-58", AYM_2003_3)])
    (a,), _ = am.ops_from_footnotes(act, _aym_law())
    assert [(o.op, str(o.target), o.old) for o in a.ops] == [
        (OpType.DELETE_PHRASE, "md.gecici-58/f1/b5", "gelir")]


def test_annulment_in_part_changes_no_words():
    act = _aym("E.2010/7, K.2011/172", [(207, "gecici-73", AYM_2011_172)])
    ams, (u,) = am.ops_from_footnotes(act, _aym_law())
    assert not ams and "yönünden" in u.reason


def test_decision_operative_part():
    # E.2006/95, K.2009/144: items under heads ("B- ... geçici 69. maddenin birinci
    # fıkrasının sonunda yer alan;"), rejections, an annulment "yönünden" (no words go)
    # and one of another law (5479/15).
    html = decode_html((FIX / "rg_20100108-18_aym_excerpt.htm").read_bytes())
    res = am.parse_decision(html, "E.2006/95, K.2009/144", 193, date(2010, 1, 8))
    assert not res.unparsed and res.sentences == 1
    (a,) = res.amendments
    assert (a.article, a.effective_date) == ("B/2", date(2010, 1, 8))
    (op,) = a.ops
    assert op.op is OpType.DELETE_PHRASE and str(op.target) == "md.gecici-69/f1"
    # The dots mark an ibare cut out of its sentence; they are not part of it.
    assert op.old == "sadece 2006, 2007 ve 2008 yıllarına ait"
    assert op.source_sentence.endswith("ibaresinin Anayasa’ya aykırı olduğuna ve İPTALİNE,")


def test_decision_with_a_later_date():
    # E.2006/119, K.2009/145 (RG 8/1/2010): "İPTAL HÜKMÜNÜN, KARARIN RESMÎ GAZETE’DE
    # YAYIMLANMASINDAN BAŞLAYARAK DOKUZ AY SONRA YÜRÜRLÜĞE GİRMESİNE".
    html = decode_html((FIX / "rg_20100108-19_aym_excerpt.htm").read_bytes())
    (a,) = am.parse_decision(html, "E.2006/119, K.2009/145", 193, date(2010, 1, 8)).amendments
    assert a.effective_date == date(2010, 10, 8)
    (op,) = a.ops
    assert (op.op, str(op.target), op.old) == (
        OpType.DELETE_PHRASE, "md.gecici-67/f1/p1",
        "Dar mükellef gerçek kişi ve kurumlar için bu oran % 0 olarak uygulanır.")


def test_annulled_sentence_as_an_instruction():
    # E.2010/93, K.2012/20 (RG 26/7/2013), item 2 under "23.7.2010 günlü, 6009 sayılı ...
    # Kanun’un:".
    item = ("23.7.2010 günlü, 6009 sayılı Gelir Vergisi Kanunu ile Bazı Kanun ve Kanun Hükmünde "
            "Kararnamelerde Değişiklik Yapılmasına Dair Kanun’un 5. maddesiyle 193 sayılı "
            "Kanun’un geçici 69. maddesinin birinci fıkrasına eklenen “Şu kadar ki, vergi "
            "matrahlarının tespitinde yatırım indirimi istisnası olarak indirim konusu yapılacak "
            "tutar, ilgili kazancın % 25’ini aşamaz.” biçimindeki cümlenin, Anayasa’ya aykırı "
            "olduğuna ve İPTALİNE, OYBİRLİĞİYLE,")
    text = am.annulment_instruction(item)
    assert text.endswith("aşamaz.” cümlesi iptal edilmiştir.")
    (op,) = am.parse_instruction(text, [], 193)
    assert (op.op, str(op.target)) == (OpType.DELETE_PHRASE, "md.gecici-69/f1")
    assert op.old.startswith("Şu kadar ki,") and op.old.endswith("% 25’ini aşamaz.")


# E.2006/119, K.2009/145 (RG 8/1/2010), items A and B of the operative part.
_ITEM_67 = ("31.12.1960 günlü, 193 sayılı Gelir Vergisi Kanunu’nun geçici 67. maddesinin (1) "
            "numaralı fıkrasının birinci paragrafının sonuna 27.6.2006 günlü, 5527 sayılı "
            "Yasa’nın 1. maddesinin (a) bendi ile eklenen “Dar mükellef gerçek kişi ve kurumlar "
            "için bu oran % 0 olarak uygulanır.” biçimindeki cümlenin Anayasa’ya aykırı "
            "olduğuna ve İPTALİNE")
_DEFER_67 = ("İPTAL HÜKMÜNÜN, KARARIN RESMÎ GAZETE’DE YAYIMLANMASINDAN BAŞLAYARAK DOKUZ AY "
             "SONRA YÜRÜRLÜĞE GİRMESİNE, OYBİRLİĞİYLE,")
_DONE = "15.10.2009 gününde karar verildi."


def test_annulment_with_its_own_deferral():
    # One item both annuls and defers: the annulment is kept, with its date.
    (a,) = am.annulments(["VIII- SONUÇ", f"A- {_ITEM_67}, {_DEFER_67}", _DONE])
    assert a.label == "A" and a.deferred
    assert am.annulment_instruction(a.text).endswith("uygulanır.” cümlesi iptal edilmiştir.")


def test_deferral_names_whole_ibareler():
    # “% 0” is in the text of A but is not its ibare: the deferral is B's only.
    other = _ITEM_67.replace("“Dar mükellef gerçek kişi ve kurumlar için bu oran % 0 olarak "
                             "uygulanır.” biçimindeki cümlenin", "“% 0” ibaresinin")
    a, b = am.annulments(["VIII- SONUÇ", f"A- {_ITEM_67},", f"B- {other},",
                          f"C- (B) bendinde yer alan “% 0” ibaresine ilişkin {_DEFER_67}", _DONE])
    assert (a.deferred, bool(b.deferred)) == (None, True)


def test_deferral_without_an_ibare_among_several_annulments():
    other = _ITEM_67.replace("birinci paragrafının", "ikinci paragrafının")
    paras = ["VIII- SONUÇ", f"A- {_ITEM_67},", f"B- {other},", f"C- {_DEFER_67}", _DONE]
    assert all(a.ambiguous and not a.deferred for a in am.annulments(paras))
    res = am.parse_decision("".join(f"<p>{p}</p>" for p in paras), "E.2006/119, K.2009/145",
                            193, date(2010, 1, 8))
    assert not res.amendments and [u[2] for u in res.unparsed] == [
        "a deferral names no ibare and the decision annuls more than one"] * 2
    # "İPTAL HÜKÜMLERİNİN" speaks of them all.
    paras[3] = "C- " + _DEFER_67.replace("HÜKMÜNÜN", "HÜKÜMLERİNİN")
    assert all(a.deferred for a in am.annulments(paras))


def test_deferral_to_a_date():
    assert am.deferred_date("İPTAL HÜKMÜNÜN 1/1/2027 TARİHİNDE YÜRÜRLÜĞE GİRMESİNE",
                            date(2026, 6, 3)) == date(2027, 1, 1)
    assert am.deferred_date(_DEFER_67, date(2010, 1, 8)) == date(2010, 10, 8)
    assert am.deferred_date("İPTAL HÜKMÜNÜN BİRAZ SONRA YÜRÜRLÜĞE GİRMESİNE",
                            date(2010, 1, 8)) is None


def test_decision_words_tumce_and_sozcuk():
    # E.2001/36, K.2003/3 (RG 21/11/2003), item C/a.
    item = ("23.11.2000 günlü, 4605 sayılı Kanun’un 5. maddesiyle 31.12 1960 günlü, 193 sayılı "
            "Gelir Vergisi Kanunu’na eklenen geçici 58. maddenin Birinci tümcesinde, “... "
            "üzerinden ...” sözcüğünden sonra yer alan “... gelir...” sözcüğünün Anayasa’ya "
            "aykırı olduğuna ve İPTALİNE, Fulya KANTARCIOĞLU’nun karşıoyu ve OYÇOKLUĞUYLA,")
    text = am.annulment_instruction(item)
    assert text.endswith("“gelir” ibaresi iptal edilmiştir.")
    (op,) = am.parse_instruction(text, [], 193)
    assert (op.op, str(op.target), op.old) == (OpType.DELETE_PHRASE, "md.gecici-58", "gelir")
    # RG 8/11/2003 (law 6831): "... üçüncü fıkrasının birinci tümcesinin ... İPTALİNE".
    item = ("6831 sayılı Orman Kanunu’nun 17. maddesinin 3373 sayılı Yasa ile değiştirilen "
            "üçüncü fıkrasının birinci tümcesinin Anayasa’ya aykırı olduğuna ve İPTALİNE,")
    (op,) = am.parse_instruction(am.annulment_instruction(item), [], 6831)
    assert (op.op, str(op.target)) == (OpType.REPEAL_NODE, "md.17/f3/c1")


def test_decision_item_not_read_is_unparsed():
    # A part of the text _NOUN_RE does not know stays a genitive: not the whole fıkra.
    item = ("193 sayılı Kanun’un 40. maddesinin birinci fıkrasının ikinci satırının Anayasa’ya "
            "aykırı olduğuna ve İPTALİNE,")
    paras = ["SONUÇ", f"A- {item}", _DONE]
    res = am.parse_decision("".join(f"<p>{p}</p>" for p in paras), "x", 193, date(2010, 1, 8))
    assert not res.amendments and res.unparsed[0][2] == "annulled thing not read"


def test_annulment_limited_to_some_cases():
    item = ("193 sayılı Kanun’un 40. maddesinin (5) numaralı bendinin, gerçek kişiler bakımından "
            "Anayasa’ya aykırı olduğuna ve İPTALİNE,")
    assert am.annulments(["SONUÇ", f"A- {item}", _DONE]) == []


def test_iptal_edilmis_only_as_a_verb():
    # Not an annulment: the bent "iptal edilmiş bulunan" is rewritten.
    ops = am.parse_instruction(
        "193 sayılı Kanunun 40 ıncı maddesinin Anayasa Mahkemesince iptal edilmiş bulunan (5) "
        "numaralı bendi aşağıdaki şekilde yeniden düzenlenmiştir.", ["5. z"], 193)
    assert [(o.op, str(o.target)) for o in ops] == [(OpType.REPLACE_NODE, "md.40/b5")]
    # "... birinci fıkrası iptal edilmiş ve maddeye aşağıdaki fıkralar eklenmiştir." (RG
    # 10/3/2003, a regulation's article 50).
    ops = am.parse_instruction(
        "193 sayılı Kanunun 141 inci maddesinin birinci fıkrası iptal edilmiş ve maddeye "
        "aşağıdaki fıkralar eklenmiştir.", ["(2) x", "(3) y"], 193)
    assert [o.op for o in ops] == [OpType.REPEAL_NODE, OpType.INSERT_NODE]


def test_bu_ibare_after_an_insert():
    (a, b) = am.parse_instruction(
        "193 sayılı Kanunun 40 ıncı maddesinin birinci fıkrasında yer alan “A” ibaresinden "
        "sonra gelmek üzere “B” ibaresi ve bu ibareden sonra gelmek üzere “C” ibaresi "
        "eklenmiştir.", [], 193)
    assert [(o.op, o.anchor, o.new) for o in (a, b)] == [
        (OpType.INSERT_PHRASE, "A", "B"), (OpType.INSERT_PHRASE, "B", "C")]


def test_footnote_of_another_decision():
    act = _aym("E.2010/7, K.2011/172", [])
    assert am.footnote_instruction(act, AYM_2003_3) is None
    act = _aym("E.2001/36, K.2003/3", [])
    assert am.footnote_instruction(act, AYM_2003_3) == "Bu arada yer alan “gelir” ibaresi iptal edilmiştir."
    both = AYM_2003_3.replace(" sayılı Kararı ile iptal", " sayılı Kararı ile ve Anayasa "
                              "Mahkemesinin 1/1/2004 tarihli ve E.:2003/1, K.:2004/1 sayılı "
                              "Kararı ile iptal")
    assert am.footnote_instruction(act, both) is None


def test_add_months():
    assert am.add_months(date(2010, 1, 8), 9) == date(2010, 10, 8)
    assert am.add_months(date(2011, 8, 31), 6) == date(2012, 2, 29)


def test_ibare_ile_then_a_sentence():
    # "... ibaresinden sonra gelmek üzere “...” ibaresi ile fıkraya aşağıdaki cümle
    # eklenmiştir" (7394/3 on VUK md. 4): an ibare and a sentence.
    a = ARTICLES["7394/3"]
    (ib, sent) = am.parse_instruction(a["instruction"], a["payload"], 213)
    assert (ib.op, ib.anchor, ib.position) == (
        OpType.INSERT_PHRASE, "usul ve esasları belirlemeye", "after")
    assert ib.new.startswith(", vergi dairesince bu Kanun ile")
    assert (sent.op, sent.anchor, sent.position) == (OpType.INSERT_NODE, None, "end")
    assert sent.new.startswith("Vergi daireleri tarafından düzenlenen")


@pytest.mark.parametrize(("instruction", "after", "new_id"), [
    (("4/1/1961 tarihli ve 213 sayılı Vergi Usul Kanununa 107 nci maddeden sonra gelmek üzere "
      "aşağıdaki 107/A maddesi eklenmiştir."), "107", "107/A"),  # 6009/7
    # without "aşağıdaki" (7524/8)
    ("213 sayılı Kanunun 274 üncü maddesinden sonra gelmek üzere 274/A maddesi eklenmiştir.",
     "274", "274/A"),
])
def test_lettered_article_added(instruction, after, new_id):
    (op,) = am.parse_instruction(instruction, [
        "“Başlık:", f"Madde {new_id}- Metin.”"], 213)
    assert (op.op, op.target.madde, op.position) == (OpType.INSERT_NODE, after, "after")
    assert [n.id for n in op.new_nodes] == [new_id]


def test_capitalised_title():
    # 6728/21: "mükerrer 355 inci maddesinin Başlığı “...” şeklinde değiştirilmiştir."
    (op,) = am.parse_instruction(
        "213 sayılı Kanunun mükerrer 355 inci maddesinin Başlığı “Bilgi vermekten çekinenler "
        "ile 256, 257, mükerrer 257 nci madde ve Gelir Vergisi Kanununun 98/A maddesi hükmüne "
        "uymayanlar için ceza:” şeklinde değiştirilmiştir.", [], 213)
    assert (op.op, op.target.madde, op.target.baslik) == (
        OpType.REPLACE_NODE, "mukerrer-355", True)


def test_lettered_fikras_are_bents():
    # VUK md. 359 calls its "a)" items fıkras (7394/4); the tree reads them as bents.
    ops = am.parse_instruction(
        "213 sayılı Kanunun 359 uncu maddesinin (a) fıkrasında yer alan “üç” ibaresi “beş” "
        "şeklinde, (b), (c) ve (ç) fıkralarında yer alan “beş” ibareleri “sekiz” şeklinde "
        "değiştirilmiş ve maddeye son fıkrasından önce gelmek üzere aşağıdaki fıkralar "
        "eklenmiştir.", ["“X.”"], 213)
    assert [(o.op, o.target.bent, o.old) for o in ops[:4]] == [
        (OpType.REPLACE_PHRASE, "a", "üç"), (OpType.REPLACE_PHRASE, "b", "beş"),
        (OpType.REPLACE_PHRASE, "c", "beş"), (OpType.REPLACE_PHRASE, "ç", "beş")]
    assert ops[0].source_sentence.startswith("213 sayılı Kanunun 359 uncu maddesinin (a) fıkrası")
    # 7423/1: a lettered "fıkra" after (ç) is a bent.
    (op,) = am.parse_instruction(
        "4/1/1961 tarihli ve 213 sayılı Vergi Usul Kanununun 359 uncu maddesine (ç) "
        "fıkrasından sonra gelmek üzere aşağıdaki fıkra eklenmiştir.",
        ["“d) 3/1/2002 tarihli ve 4733 sayılı Kanun ...”"], 213)
    assert (op.kind, op.target.bent, op.position) == (Level.BENT, "ç", "after")
    assert [n.label for n in op.new_nodes] == ["d)"]


def test_lettered_fikras_inside_an_ibare_stay():
    (op,) = am.parse_instruction(
        "213 sayılı Kanunun 367 nci maddesinin dördüncü fıkrasında yer alan “359 uncu maddenin "
        "(ç) ve (d) fıkralarında” ibaresi “X” şeklinde değiştirilmiştir.", [], 213)
    assert op.old == "359 uncu maddenin (ç) ve (d) fıkralarında" and op.target.fikra == 4


def test_bent_list_before_another_address():
    # 7061/12 on 7258: the replacement is in (d), not in the (ç) and (e) replaced above.
    ops = am.parse_instruction(
        "29/4/1959 tarihli ve 7258 sayılı Kanunun 2 nci maddesinin üçüncü fıkrasının (2) "
        "numaralı bendinin (ç) ve (e) alt bentleri aşağıdaki şekilde, (d) alt bendinde yer alan "
        "“Bu fıkranın (b) ve (c) bentlerinde” ibaresi “Bu bendin (b) ve (c) alt bentlerinde” "
        "şeklinde değiştirilmiştir.",
        [("“ç) Bayilerle yapılacak sözleşmelerin esasları ile bayilere verilecek komisyon ve "
          "teşvik primi oranlarını tespit etmek.”"),
         ("“e) Başbayi ile yapılacak sözleşmelerin esasları ile komisyon ve teşvik primi dahil "
          "olmak üzere ihale kıstaslarını tespit etmek.”")], 7258)
    # "aşağıdaki şekilde," takes the verb at the end: (ç) and (e) are replaced by the text
    # below (6322/39 has the same form).
    assert [(o.op, o.target.alt_bent) for o in ops] == [
        (OpType.REPLACE_NODE, "ç"), (OpType.REPLACE_NODE, "e"), (OpType.REPLACE_PHRASE, "d")]
    assert ops[1].new_nodes[0].text.startswith("Başbayi ile")


def test_table_attached_to_the_law_is_skipped():
    # 7524/10: the cetvel's title and amounts are not an article; the ibareler are.
    ops = am.parse_instruction(
        "213 sayılı Kanunun 352 nci maddesinin birinci fıkrasının birinci cümlesinde yer alan "
        "“bağlı cetvele” ibaresi “bağlı 1 sayılı cetvele” şeklinde, ikinci cümlesinde yer alan "
        "“bağlı cetvelde” ibaresi “bağlı 1 sayılı cetvelde” şeklinde ve Kanuna bağlı "
        "“Usulsüzlük Cezalarına Ait Cetvel” başlığı “1 Sayılı Usulsüzlük Cezalarına Ait "
        "Cetvel” şeklinde, mevcut Usulsüzlük Cezalarına Ait Cetveldeki miktarlar aşağıdaki "
        "şekilde değiştirilmiştir.", ["Birinci derece ..."], 213)
    assert [(o.op, o.target.cumle) for o in ops] == [
        (OpType.REPLACE_PHRASE, 1), (OpType.REPLACE_PHRASE, 2)]
    # A table inside an article is addressed by its fıkra and stays.
    ops = am.parse_instruction(
        "193 sayılı Kanunun 5 inci maddesinin birinci fıkrasında yer alan “x” ibaresi “y” "
        "şeklinde, ikinci fıkrasındaki cetvelde yer alan “a” ibaresi “b” şeklinde "
        "değiştirilmiştir.", [], 193)
    assert [str(o.target) for o in ops] == ["md.5/f1", "md.5/f2"]


def test_annulment_from_a_marker():
    # E.2019/4, K.2021/78 (RG text a PDF) annulled VUK md. 367's last fıkra; only the
    # marker is left of it. 7394/5 added a fıkra before it later.
    def f(text, **kw):
        return Node(level=Level.FIKRA, text=text, **kw)
    md367 = Node(level=Level.MADDE, id="367", label="Madde 367 –", children=[
        f("Yaptıkları inceleme sırasında ..."), f("359 uncu maddede yazılı suçlara ...",
                                                    notes=["(Ek beşinci fıkra:8/4/2022-7394/5 md.)"]),
        f("", repealed=True, notes=[
            ("(İptal fıkra: Anayasa Mahkemesi’nin 4/11/2021 tarihli ve E.: 2019/4, K.: 2021/78 "
             "sayılı Kararı ile.)")])])
    law = Law(number=213, name="", body=[md367])
    act = AmendingAct(kind="aym", number="E.2019/4, K.2021/78")
    (a,) = am.ops_from_markers(act, law)
    (op,) = a.ops
    assert (op.op, str(op.target)) == (OpType.REPEAL_NODE, "md.367/f3")
    assert am.ops_from_markers(AmendingAct(kind="aym", number="E.2019/5, K.2021/78"), law) == []
    # Undone after 7394/5's fıkra is: the node is found by its marker, not its number.
    del md367.children[1]
    assert unapply(law, op).status == "ok" and str(op.target) == "md.367/f2"
    apply(law, op)
    assert md367.children[1].repealed


def test_marker_insertion_keeps_the_unwound_text():
    # 7318/4 added VUK md. 359 (ç) with "üç yıldan beş yıla"; 7394/4 made it "üç yıldan
    # sekiz yıla" later. Read from the "(Ek: ...)" marker, the op carries today's text;
    # undone after 7394/4, it takes the text the unwind left.
    def b(label, text, **kw):
        return Node(level=Level.BENT, label=label, text=text, **kw)
    c = b("c)", "Vergi kanunları uyarınca ... (c) bendinde yazılı fiilleri işleyenler")
    cc = b("ç)", "... üç yıldan beş yıla kadar hapis ...", notes=["(Ek:3/6/2021-7318/4 md.)"])
    md359 = Node(level=Level.MADDE, id="359", label="Madde 359 –", children=[
        Node(level=Level.FIKRA, text="Vergi kanunlarına göre ...", children=[c, cc])])
    law = Law(number=213, name="", body=[md359])
    op = am.AmendmentOp(op=OpType.INSERT_NODE, target=Addr(madde="359", fikra=1, bent="c"),
                        position="after", source_sentence="(Ek:3/6/2021-7318/4 md.)",
                        new_nodes=[b("ç)", "... üç yıldan sekiz yıla kadar hapis ...")])
    assert unapply(law, op).status == "ok"
    assert md359.children[0].children == [c]
    assert op.new_nodes[0].text == "... üç yıldan beş yıla kadar hapis ..."
    # A footnoted op still has to match.
    md359.children[0].children.append(cc)
    op.footnote, op.new_nodes = 4, [b("ç)", "... sekiz ...")]
    assert unapply(law, op).status == "fail"
    # So does one whose node is not the one there.
    op.footnote, op.new_nodes = None, [b("d)", "... sekiz ...")]
    assert unapply(law, op).status == "fail"


# -- KDV (3065) -----------------------------------------------------------------------------

def _kdv(sentence, payload=()):
    return am.parse_instruction(sentence, list(payload), 3065)


def test_title_ibare_and_a_list_of_deleted_ibareler():
    # 6745/36
    ops = _kdv(
        "25/10/1984 tarihli ve 3065 sayılı Katma Değer Vergisi Kanununun geçici 30 uncu "
        "maddesinin madde başlığında yer alan “ve stratejik” ibaresi ile birinci fıkrasının "
        "birinci cümlesinde yer alan “stratejik” ibaresi madde metninden çıkarılmış ve aynı "
        "maddenin birinci fıkrasından sonra gelmek üzere aşağıdaki fıkra eklenmiştir.",
        ["“(2) Birinci fıkrada yer alan ... yetkilidir.”"])
    assert [(o.op, str(o.target), o.old) for o in ops] == [
        (OpType.DELETE_PHRASE, "md.gecici-30/başlık", "ve stratejik"),
        (OpType.DELETE_PHRASE, "md.gecici-30/f1/c1", "stratejik"),
        (OpType.INSERT_NODE, "md.gecici-30/f1", None)]


def test_new_article_ends_at_its_closing_quote():
    # 5804/3: the next article's title "Yürürlük" comes after the closing quote.
    (op,) = _kdv("25/10/1984 tarihli ve 3065 sayılı Katma Değer Vergisi Kanununa aşağıdaki "
                 "geçici madde eklenmiştir.", [
        ("\"GEÇİCİ MADDE 27 – (1) 2009 yılı Mart ayında İstanbul’da yapılacak Beşinci Dünya "
         "Su Forumunun ... müstesnadır."),
        ("(2) Maliye Bakanlığı, istisnanın uygulanmasına ilişkin usul ve esasları "
         "belirlemeye yetkilidir.\""),
        "Yürürlük"])
    (md,) = op.new_nodes
    assert [(f.label, f.text[-11:], f.children) for f in md.children][-1] == (
        "(2)", "yetkilidir.", [])


def test_parenthesised_provision_added_after_an_ibare():
    # 6728/43 (a)
    (op,) = _kdv(
        "25/10/1984 tarihli ve 3065 sayılı Katma Değer Vergisi Kanununun 17 nci maddesinin (4) "
        "numaralı fıkrasının (g) bendine “tahvil” ibaresinden sonra gelmek üzere “(elde edilen "
        "faiz gelirleri ile sınırlı olmak üzere tahvil satın almak suretiyle verilen finansman "
        "hizmetleri dâhil)” parantez içi hüküm eklenmiştir.")
    assert (op.op, str(op.target), op.anchor) == (OpType.INSERT_PHRASE, "md.17/f4/bg", "tahvil")
    assert op.new.startswith("(elde edilen")


def test_unquoted_new_text_goes_by_the_labels_each_operation_names():
    # 5035/8
    ops = _kdv(
        "3065 sayılı Kanunun 17 nci maddesinin (2) numaralı fıkrasının (b) bendi ve (4) "
        "numaralı fıkrasının (g) bendi aşağıdaki şekilde değiştirilmiş, fıkranın mülga (ı) "
        "bendi aşağıdaki şekilde yeniden düzenlenmiş ve fıkraya aşağıdaki (n) bendi "
        "eklenmiştir.", [
            "b) Kanunların gösterdiği gerek üzerine bedelsiz olarak yapılan mal teslimi ...",
            "g) Külçe altın, dore külçe altın, külçe gümüş, döviz, para, ...",
            "ı) Serbest bölgelerde verilen hizmetler, ...",
            "n) Basın, Yayın ve Enformasyon Genel Müdürlüğüne verilen haber hizmetleri."])
    assert [(o.op, str(o.target), [n.label for n in o.new_nodes]) for o in ops] == [
        (OpType.REPLACE_NODE, "md.17/f2/bb", ["b)"]), (OpType.REPLACE_NODE, "md.17/f4/bg", ["g)"]),
        (OpType.REPLACE_NODE, "md.17/f4/bı", ["ı)"]), (OpType.INSERT_NODE, "md.17/f4", ["n)"])]
    # 5228/15: "fıkraya (o) ve (p) bentleri eklenmiştir", with no "aşağıdaki".
    ops = _kdv(
        "3065 sayılı Kanunun 17 nci maddesinin (2) numaralı fıkrasının (b) bendi aşağıdaki "
        "şekilde değiştirilmiş ve fıkraya aşağıdaki (e) bendi eklenmiş, (4) numaralı "
        "fıkrasının (f), (g), (ı) ve (m) bentleri aşağıdaki şekilde değiştirilmiş ve fıkraya "
        "(o) ve (p) bentleri eklenmiştir.", [
            "b) Üniversite ve yüksekokullar ...", "e) Kamu kurumu niteliğindeki ...",
            "f) Darphane ve Damga Matbaası ...", "g) Külçe altın, külçe gümüş, ...",
            "ı) Serbest bölgelerde verilen hizmetler,", "m) Bankalar Kanunu uyarınca; ...",
            "Bu istisna işlem bedelinden Fona intikal eden tutarla orantılı uygulanır.",
            "o) Gümrük antrepoları ...", "p) Hazine ve Arsa Ofisi Genel Müdürlüğünce ..."])
    assert [[n.label for n in o.new_nodes] for o in ops] == [
        ["b)"], ["e)"], ["f)"], ["g)"], ["ı)"], ["m)"], ["o)", "p)"]]
    assert ops[5].new_nodes[0].children[0].text.startswith("Bu istisna")
    # Text left over is not dropped silently.
    with pytest.raises(am.Unparsed):
        _kdv("3065 sayılı Kanunun 17 nci maddesinin (2) numaralı fıkrasının (b) bendi ve (4) "
             "numaralı fıkrasının (g) bendi aşağıdaki şekilde değiştirilmiş ve fıkraya "
             "aşağıdaki (n) bendi eklenmiştir.", ["b) ...", "g) ...", "n) ...", "s) ..."])


def test_existing_sentence_counts_before_the_insert():
    # 7524/21: "mevcut birinci cümlesi" is the second once the new one is in.
    ops = _kdv(
        "3065 sayılı Kanunun 36 ncı maddesinin ikinci fıkrasına birinci cümlesinden önce "
        "gelmek üzere aşağıdaki cümle eklenmiş ve mevcut birinci cümlesinde yer alan “Maliye "
        "Bakanlığı” ibaresi “Şu kadar ki, Hazine ve Maliye Bakanlığı” şeklinde "
        "değiştirilmiştir.", [("“Bu Kanun hükümleri uyarınca iade hakkı doğuran işlemlerden "
                               "kaynaklanan iade taleplerinin vergi inceleme raporu sonucuna "
                               "göre yerine getirilmesi esastır.”")])
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.INSERT_NODE, "md.36/f2/c1"), (OpType.REPLACE_PHRASE, "md.36/f2/c2")]


def test_genitive_ibare_and_a_verb_given_once_at_the_end():
    # 5615/13 ("ibaresinin" for "ibaresi"; "aşağıdaki şekilde;" without its verb)
    ops = _kdv(
        "3065 sayılı Kanunun 17 nci maddesinin (2) numaralı fıkrasının (b) bendinde yer alan "
        "\"Üniversite ve yüksekokullar ile ... % 10 unu\" ibaresi \"8/2/2007 tarihli ... % "
        "50’sini\" şeklinde; (4) numaralı fıkrasının (o) bendinde yer alan \"işlemlerine konu "
        "mallar\" ibaresinin \"işlemlerine konu mallar ile transit rejim kapsamında işlem "
        "gören mallar\" şeklinde; aynı fıkranın (r) bendi aşağıdaki şekilde; 29 uncu "
        "maddesinin (2) numaralı fıkrasındaki \"işletmelerden\" ibaresi ise \"işletmeler ile "
        "organize sanayi bölgelerinden\" şeklinde değiştirilmiştir.",
        ["\"r) Basılı kitap ve süreli yayınların ...\""])
    assert [(o.op, str(o.target)) for o in ops] == [
        (OpType.REPLACE_PHRASE, "md.17/f2/bb"), (OpType.REPLACE_PHRASE, "md.17/f4/bo"),
        (OpType.REPLACE_NODE, "md.17/f4/br"), (OpType.REPLACE_PHRASE, "md.29/f2")]


def test_annulled_part_of_a_change():
    # E.2024/54, K.2025/163 on KDV md. 36 (footnote 91): "veya iade", which 7491/31 had put
    # in two places; the consolidated text marks both with "(…)".
    act = AmendingAct(kind="aym", number="E.2024/54, K.2025/163")
    text = am.footnote_instruction(act, (
        "Anayasa Mahkemesinin 22/7/2025 tarihli ve E.: 2024/54, K.: 2025/163 sayılı Kararı "
        "ile bu fıkrada yer alan “…indirim hakkını…” ibaresinin “…indirim veya iade "
        "hakkını…” şeklinde değiştirilmesinde bulunan “…veya iade…” ibaresi ile “…indirim "
        "hakkı…” ibaresinin “…indirim veya iade hakkı…” şeklinde değiştirilmesinde bulunan "
        "“…veya iade…” ibaresi iptal edilmiştir."))
    assert text == "bu fıkrada yer alan “veya iade” ibaresi ile “veya iade” ibaresi iptal edilmiştir."
    (op,) = am.parse_instruction(text, [], 3065, law_ctx="3065", ctx=Addr(madde="36", fikra=1))
    assert (op.op, op.old, op.all, op.occurrences) == (OpType.DELETE_PHRASE, "veya iade", False, 2)
    f1 = Node(level=Level.FIKRA, text="Cumhurbaşkanı indirim (…) hakkını kısmen ... bu şekilde "
              "indirim (…) hakkı kısıtlanan mal veya hizmetleri belirlemeye ...")
    law = Law(number=3065, name="", body=[
        Node(level=Level.MADDE, id="36", label="Madde 36 –", children=[f1])])
    assert unapply(law, op).status == "ok"
    assert f1.text.startswith("Cumhurbaşkanı indirim veya iade hakkını kısmen")
    assert "indirim veya iade hakkı kısıtlanan" in f1.text
    # Marks of other deletions are not filled: "ibareleri" says every occurrence, not how
    # many marks are its own (7394 on KDV md. 13 (f), two marks).
    f1.text = "Milli Savunma Bakanlığı, (…) Savunma Sanayii Başkanlığı (…) ve Gümrük"
    other = op.model_copy(update={"old": ", Emniyet Genel Müdürlüğü", "all": True,
                                  "occurrences": None})
    assert unapply(law, other).status == "lossy"
    assert f1.text == "Milli Savunma Bakanlığı, (…) Savunma Sanayii Başkanlığı (…) ve Gümrük"
    # Forward, the two places and no more.
    f1.text = "a veya iade b veya iade c veya iade"
    apply(law, op)
    assert f1.text == "a b c veya iade"


def test_annulment_wording_is_not_a_replacement():
    ops = _kdv(
        "3065 sayılı Kanunun 36 ncı maddesinin birinci fıkrasında yer alan “indirim hakkını” "
        "ibaresinin “indirim veya iade hakkını” şeklinde değiştirilmesinde bulunan “veya "
        "iade” ibaresi iptal edilmiştir.")
    assert [(o.op, o.old) for o in ops] == [(OpType.DELETE_PHRASE, "veya iade")]


def test_failed_fikra_address_is_not_a_whole_article():
    # 213 mükerrer 355: "Birinci fıkrasında" (capital B) is not read as a fıkra address.
    (op,) = am.parse_instruction(
        "213 sayılı Kanunun mükerrer 355 inci maddesinin Birinci fıkrasında yer alan “x” "
        "ibaresi “y” şeklinde değiştirilmiştir.", [], 213)
    assert not op.all


def test_law_named_only_inside_a_quote_is_not_the_target():
    # 7341/4 amends the Damga Vergisi Kanunu; 5520 is only in its new ibare.
    s = ("1/7/1964 tarihli ve 488 sayılı Damga Vergisi Kanununa ekli (2) sayılı tablonun "
         "“V-Kurumlarla ilgili kağıtlar” başlıklı bölümünün (22) numaralı fıkrasında yer alan "
         "“Kurumlar Vergisi Kanununun 7 nci maddesinin 24 numaralı bendinde” ibaresi “13/6/2006 "
         "tarihli ve 5520 sayılı Kurumlar Vergisi Kanununun 4 üncü maddesinin birinci fıkrasının "
         "(1) ve (p) bentlerinde” şeklinde değiştirilmiştir.")
    assert not am.mentions(s, 5520) and am.mentions(s, 488)


def test_list_items_with_capitalised_ordinals_and_mevcut():
    # 6728/59 on KVK md. 13: each item starts with a capital ("İkinci fıkrasına",
    # "Mevcut sekizinci fıkrası"); the last counts past the fıkra item (ç) added.
    a = am.ActArticle(number="59", instruction="5520 sayılı Kanunun 13 üncü maddesinin;",
                      payload=[
        ("a) İkinci fıkrasına “İlişkili kişiler açısından bu oranlar topluca dikkate alınır.” "
         "cümleleri eklenmiştir."),
        ("b) Dördüncü fıkrasının (ç) bendi aşağıdaki şekilde değiştirilmiş ve bu bentten sonra "
         "gelmek üzere (d) bendi eklenmiştir."),
        "“ç) İşlemsel kâr yöntemleri: ... esasına dayanır.”",
        "“d) Emsallere uygun fiyata ... bir yöntemi de kullanabilir.”",
        ("c) Beşinci fıkrasına “Mükellef ve Bakanlık, ... uygulanabilir.” cümlesi "
         "eklenmiştir."),
        ("ç) Yedinci fıkrasından sonra gelmek üzere aşağıdaki fıkra eklenmiş ve mevcut sekizinci "
         "fıkra buna göre teselsül ettirilmiştir."),
        "“(8) Transfer fiyatlandırmasına ilişkin ... %50 indirimli olarak uygulanır.”",
        "d) Mevcut sekizinci fıkrası aşağıdaki şekilde değiştirilmiştir.",
        "“(9) Bakanlar Kurulu; ikinci fıkrada yer alan oranları, ... yetkilidir.”",
    ])
    items = am.expand_list(a)
    assert items[0].instruction.startswith("5520 sayılı Kanunun 13 üncü maddesinin ikinci")
    assert items[4].instruction.startswith("5520 sayılı Kanunun 13 üncü maddesinin mevcut")
    earlier: list = []
    got = []
    for it in items:
        ops = am.parse_instruction(it.instruction, it.payload, 5520, earlier=earlier)
        earlier += ops
        got.append([(o.op, o.target.fikra, o.target.bent, o.position) for o in ops])
    assert got == [
        [(OpType.INSERT_PHRASE, 2, None, "end")],
        [(OpType.REPLACE_NODE, 4, "ç", None), (OpType.INSERT_NODE, 4, "ç", "after")],
        [(OpType.INSERT_PHRASE, 5, None, "end")],
        [(OpType.INSERT_NODE, 7, None, "after")],
        [(OpType.REPLACE_NODE, 9, None, None)],
    ]
    d = earlier[2].new_nodes[0]
    assert d.label == "d)" and d.text.endswith("bir yöntemi de kullanabilir.")


def test_renumbering_clause_is_not_the_next_address():
    # 6322/39 on KVK md. 32/A: the sentence goes to the sixth fıkra, not to bent (c).
    ops = am.parse_instruction(
        "5520 sayılı Kanunun 32/A maddesinin ikinci fıkrasının (b) bendinden sonra gelmek "
        "üzere aşağıdaki (c) bendi eklenmiş, mevcut (c) bendi (ç) bendi olarak teselsül "
        "ettirilmiş ve altıncı fıkrasına aşağıdaki cümle eklenmiştir.",
        ["“c) Yatırıma başlanan tarihten itibaren ...”",
         ("“Yatırımın kısmen veya tamamen işletilmesine başlanmadan önce indirimli kurumlar "
          "vergisi uygulanan hallerde, ...”")], 5520)
    assert [(o.op, o.target.fikra, o.target.bent) for o in ops] == [
        (OpType.INSERT_NODE, 2, "b"), (OpType.INSERT_NODE, 6, None)]
    assert ops[1].new.startswith("Yatırımın kısmen")
