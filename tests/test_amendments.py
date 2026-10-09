"""Faz 2: amendment sentences taken verbatim from Resmî Gazete texts."""

import json
from pathlib import Path

import pytest

from mevzuat_git import amendments as am
from mevzuat_git.fetch import decode_html
from mevzuat_git.model import Level, OpType
from mevzuat_git.model import Path as Addr

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
    assert op.old == "1.1.1999 - 31.12.2003 tarihleri arasında" and not op.all


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
