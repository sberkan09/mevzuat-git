"""Faz 1: tree parser on a real excerpt of the GVK consolidated text (mevzuat.gov.tr)."""

from pathlib import Path

import pytest

from mevzuat_git.model import Level
from mevzuat_git.render import escape, to_markdown
from mevzuat_git.tree import build_tree, split_markers

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def law():
    return build_tree((FIX / "gvk_193_tree_excerpt.html").read_text(), 193)


def shape(node):
    return [(c.level.value, c.label) for c in node.children]


def test_articles_in_order(law):
    assert [a.id for a in law.articles()] == [
        "1", "2", "3", "4", "5", "6", "7", "8", "10", "11", "47", "48", "49", "102", "103",
        "104", "105", "mukerrer-123", "124", "gecici-1", "gecici-2", "gecici-3",
        "gecici-70", "gecici-71", "gecici-72", "gecici-73",
    ]


def test_headings(law):
    kisim = law.body[0]
    assert (kisim.level, kisim.label, kisim.title) == (Level.KISIM, "BİRİNCİ KISIM",
                                                         "Mükellefiyet")
    assert [(b.label, b.title) for b in kisim.children[:3]] == [
        ("BİRİNCİ BÖLÜM", "Verginin Mevzuu"),
        ("İKİNCİ BÖLÜM", "Tam Mükellefiyet"),
        ("ÜÇÜNCÜ BÖLÜM", "Dar Mükellefiyet"),
    ]
    # "Son Hükümler" has no ordinal; it still opens a heading and is not a fıkra of
    # Mükerrer Madde 123.
    assert any(n.level is Level.BOLUM and n.title == "Son Hükümler"
               for top in law.body for n in top.walk())
    assert all(c.text != "Son Hükümler" for c in law.article("mukerrer-123").walk())


def test_titles(law):
    assert law.article("1").title == "Mevzuu:"
    # Titles without a trailing colon are recognised by their position.
    assert law.article("48").title == "Basit usule tabi olmanın özel şartları"
    assert law.article("gecici-1").title == "Geçmiş yıllara ait vergiler:"


def test_markers_and_text_kept_apart(law):
    a1 = law.article("1")
    assert a1.notes == ["(Değişik: 7/1/2003-4783/1 md.)"]
    assert a1.children[0].text.startswith("Gerçek kişilerin gelirleri gelir vergisine tâbidir.")
    bent = law.article("3").children[0].children[1]
    assert (bent.label, bent.notes) == ("2.", ["(Değişik: 19/2/1963-202/1 md.)"])
    assert bent.text.startswith("Resmi daire ve müesseselere")


def test_bents_and_alt_bents(law):
    a7 = law.article("7")
    f1 = a7.children[0]
    assert shape(f1) == [("bent", f"{i}.") for i in range(1, 8)]
    assert shape(f1.children[2]) == [("alt_bent", "a)"), ("alt_bent", "b)")]
    # "Türkiye'de satmaktan maksat ..." continues bent 1; bent 2 is not under it.
    assert shape(f1.children[0]) == [("paragraf", "")]
    assert f1.children[0].children[0].text.startswith("Türkiye'de satmaktan maksat")
    assert len(a7.children) == 2


def test_numbered_fikras(law):
    g72 = law.article("gecici-72")
    assert [c.label for c in g72.children] == ["(1)", "(2)", "(3)", "(4)"]
    f1 = g72.children[0]
    assert shape(f1) == [("bent", "a)"), ("bent", "b)")]
    assert shape(f1.children[0]) == [("alt_bent", "1)"), ("alt_bent", "2)"),
                                     ("alt_bent", "3)")]
    assert g72.children[1].notes == ["(Değişik:5/12/2019-7194/21 md.)"]


def test_repealed(law):
    assert law.article("10").repealed
    assert law.article("10").notes == ["(Mülga: 22/7/1998-4369/82 md.)"]
    assert not law.article("1").repealed
    # "(Mülga: ...; Yeniden düzenleme: ...)" is in force.
    _, rest = split_markers("(Mülga: 22/7/1998-4369/82 md.; Yeniden düzenleme: "
                            "7/1/2003-4783/4 md.) Metin")
    assert rest == "Metin"


def test_table(law):
    a103 = law.article("103")
    table = a103.children[0].children[0]
    assert table.level is Level.TABLO
    rows = table.text.split("\n")
    assert rows[0] == "18.000 TL’ye (190.000 TL) kadar | %15"
    assert len(rows) == 5


def test_footnote_refs_are_not_text(law):
    a = law.article("mukerrer-123")
    assert a.footnotes == [154, 155]
    assert all("[154]" not in n.text for n in a.walk())


def test_markdown_is_deterministic_and_verbatim(law):
    md = to_markdown(law)
    assert md == to_markdown(build_tree((FIX / "gvk_193_tree_excerpt.html").read_text(), 193))
    assert "#### Madde 1 – Mevzuu:" in md
    assert "\n1\\. Ticarî kazançlar,\n" in md
    assert "(Değişik: 7/1/2003-4783/1 md.)" in md
    assert "(Değişik: 7/1/2003-4783/1 md.)" not in to_markdown(law, notes=False)


def test_escape():
    assert escape("1. Ticari") == "1\\. Ticari"
    assert escape("1) En üst") == "1\\) En üst"
    assert escape("a) Lig") == "a) Lig"
    assert escape("- x") == "\\- x"


def test_full_gvk_when_cached():
    """The whole consolidated GVK, if `mevzuat-git fetch 193` has filled the cache."""
    from mevzuat_git.fetch import DEFAULT_CACHE_DIR, cache_path, decode_html
    from mevzuat_git.mevzuat_gov import iframe_url

    p = cache_path(iframe_url(193, tertip=4), DEFAULT_CACHE_DIR)
    if not p.exists():
        pytest.skip("GVK not in data/raw cache")
    law = build_tree(decode_html(p.read_bytes()), 193)
    ids = [a.id for a in law.articles()]
    assert len(ids) == len(set(ids))
    assert {"1", "mukerrer-20/D", "103", "gecici-94", "126"} <= set(ids)
    assert [n.label for n in law.body] == ["BİRİNCİ KISIM", "İKİNCİ KISIM", "ÜÇÜNCÜ KISIM",
                                           "DÖRDÜNCÜ KISIM", "BEŞİNCİ KISIM"]
