"""Faz 1: tree parser on a real excerpt of the GVK consolidated text (mevzuat.gov.tr)."""

from pathlib import Path

import pytest

from mevzuat_git.model import Level
from mevzuat_git.render import escape, to_markdown
from mevzuat_git.tree import (
    ITEM_RE,
    _follows,
    _is_repeal,
    build_tree,
    parse_fragment,
    split_markers,
)

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def law():
    return build_tree((FIX / "gvk_193_tree_excerpt.html").read_text(), 193)


def shape(node):
    return [(c.level.value, c.label) for c in node.children]


def test_articles_in_order(law):
    assert [a.id for a in law.articles()] == [
        "1", "2", "3", "4", "5", "6", "7", "8", "10", "11", "47", "48", "49", "94", "102",
        "103", "104", "105", "mukerrer-123", "124", "gecici-1", "gecici-2", "gecici-3",
        "gecici-57", "gecici-58", "gecici-59", "gecici-60", "gecici-61", "gecici-62",
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


def test_item_opening_with_sub_item(law):
    # "6. a) Dağıtılsın ..." and "b) (Değişik: ...) i) Tam mükellef ..." (md. 94).
    b6 = law.article("94").children[0].children[5]
    assert (b6.label, b6.text) == ("6.", "")
    assert shape(b6) == [("alt_bent", "a)"), ("alt_bent", "b)"), ("alt_bent", "c)")]
    assert shape(b6.children[0]) == [("alt_bent", "i)"), ("alt_bent", "ii)")]
    # "(a), (c) ve (d) bentlerinde ..." is a reference, not a label.
    assert b6.children[0].children[0].text.startswith("(a), (c) ve (d) bentlerinde")
    b = b6.children[1]
    assert b.notes == ["(Değişik: 9/4/2003-4842/12 md.)"]
    assert [c.label for c in b.children] == ["i)", "ii)", "iii)"]


def test_punctuation_typo_keeps_the_list(law):
    # md. 94: "8." is followed by "9)"; geçici 58: "1)" by "2-a)".
    bents = law.article("94").children[0].children
    assert [c.label for c in bents][7:10] == ["8.", "9)", "10."]
    assert all(c.level is Level.BENT for c in bents)
    g58 = law.article("gecici-58").children[0]
    assert [c.label for c in g58.children][:3] == ["1)", "2-", "3)"]


def test_items_continue_across_paragraphs(law):
    # Geçici 58: "a) ...", five unlabelled lines (one with its own "1. 2. 3."), "Liradır.",
    # then "b)": the lines belong to "a)" and "b)" continues the list.
    two = law.article("gecici-58").children[0].children[1]
    assert [c.label for c in two.children] == [f"{x})" for x in "abcdefghijk"]
    assert all(c.level is Level.ALT_BENT for c in two.children)  # i) after h) is a letter


def test_iptal_is_repeal(law):
    k = law.article("gecici-58").children[0].children[1].children[-1]
    assert k.notes[0].startswith("(İptal: Anayasa Mahkemesinin")
    assert k.repealed
    assert _is_repeal(["(Mülga birinci fıkra: 4/12/2003-5009/1 md.)"], whole=False)
    assert not _is_repeal(["(Mülga birinci fıkra: 4/12/2003-5009/1 md.)"])


def test_number_running_into_digits_is_not_a_label():
    assert ITEM_RE.match("18.000 TL’ye (190.000 TL) kadar") is None
    assert ITEM_RE.match("1.Bu Kanunun 21, 23/8, 47").group("label") == "1."
    assert ITEM_RE.match("H) Bu Kanunun geçici 47 nci").group("label") == "H)"


def test_turkish_alphabet_order():
    assert _follows("h", "ı") and _follows("h", "i") and _follows("ı", "i")
    assert _follows("c", "ç") and _follows("c", "d") and not _follows("a", "c")
    assert _follows("8", "9")


def test_br_is_a_space():
    html = ("<html><body><p>Madde 1 – (Değişik: 7/1/2003-4783/1 md.)</p>"
            "<p>Gerçek kişilerin gelirleri gelir vergisine<br>tâbidir.</p></body></html>")
    law = build_tree(html, 193)
    assert law.article("1").children[0].text == "Gerçek kişilerin gelirleri gelir vergisine tâbidir."


# GVK md. 94, dördüncü fıkra, as on mevzuat.gov.tr.
MD94_F4 = [
    ("MADDE 94 – Tam mükellef sermaye şirketlerinin iktisap ettikleri kendi hisse senetlerini "
    "veya ortaklık paylarını,"),
    ("i) Sermaye azaltımı yoluyla itfa etmeleri hâlinde iktisap bedeli ile hisse senetlerinin "
    "veya ortaklık paylarının itibari değeri arasındaki fark tutar sermaye azaltımına ilişkin "
    "kararın ticaret sicilinde tescil edildiği tarih,"),
    ("ii) İktisap bedelinin altında bir bedel karşılığında elden çıkarmaları hâlinde iktisap "
    "bedeli ile elden çıkarma bedeli arasındaki fark tutar elden çıkarma tarihi,"),
    ("itibarıyla dağıtılmış kâr payı sayılır ve bu tutarlar üzerinden %15 oranında vergi "
    "tevkifatı yapılır."),
]


def test_lower_case_line_continues_the_fikra():
    (art,) = parse_fragment(MD94_F4, Level.MADDE)
    (f,) = art.children
    assert [(c.level, c.label) for c in f.children] == [
        (Level.BENT, "i)"), (Level.BENT, "ii)"), (Level.PARAGRAF, "")]
    assert f.children[-1].text.startswith("itibarıyla dağıtılmış")


def _gvk(*paras: tuple[str, str] | str):
    """A law from paragraphs of the consolidated text: "text" or ("class", "text")."""
    ps = [p if isinstance(p, tuple) else ("Nor", p) for p in paras]
    body = "".join(f'<p class="{c}">{t}</p>' for c, t in ps)
    return build_tree(f"<html><body>{body}</body></html>", 193)


def test_changed_title_ends_with_its_marker():
    # Mükerrer 20/B's title is 203 characters with its marker and has no ":".
    law = _gvk(
        "", "Basit usulde tespit olunan kazançlarda gelir vergisi istisnası:",
        "Mükerrer Madde 20/A- (Ek:14/10/2021-7338/1 md.)",
        ("Bu Kanuna göre kazançları basit usulde tespit olunan mükelleflerin 46 ncı maddeye "
         "göre tespit edilen kazançları gelir vergisinden müstesnadır."),
        "",
        ("Sosyal içerik üreticiliği, internet ve benzeri elektronik ortamlar üzerinden "
         "sunulan hizmetler ile mobil cihazlar için uygulama geliştiriciliğinde kazanç "
         "istisnası (Değişik Başlık: 27/12/2023-7491/7 md.)"),
        "Mükerrer Madde 20/B- (Ek:14/10/2021-7338/2 md.)",
        "(Değişik: 27/12/2023-7491/7 md.) İnternet ve benzeri elektronik ortamlar ...")
    assert len(law.article("mukerrer-20/A").children) == 1
    assert law.article("mukerrer-20/B").title.startswith("Sosyal içerik üreticiliği")


def test_sentence_with_title_class_is_not_a_title():
    # The last fıkra of geçici 59 has the class "MaddeBasl" on mevzuat.gov.tr.
    law = _gvk(
        "", "Geçici Madde 59- (Ek:10/11/2001-4710/1 md.)",
        ("MsoNormal", "31.12.2007 tarihine kadar, 26.7.2001-31.12.2005 tarihleri arasında ..."),
        ("MaddeBasl", ("Ticari işletmelere ait olan bu tür gelirler hakkında bu madde hükmü "
                       "uygulanmaz.")),
        ("MaddeBasl", ""), ("MaddeBasl", "Geçici Madde 60- (Ek: 12/6/2002-4761/3 md.)"),
        ("ksmblm", "Mevcut veya yeni kurulacak olan sermaye şirketlerine, ..."))
    assert len(law.article("gecici-59").children) == 2
    assert law.article("gecici-60").title is None


def test_heading_over_a_title():
    # "Muhtasar beyanname:" heads md. 98 ("a) Verilme zamanı:") and md. 99 ("b)
    # Muhteviyatı:"); it is not the last fıkra of md. 98/A.
    law = _gvk(
        "", "Muhtasar ve prim hizmet beyannamesi:", "Madde 98/A- (Ek: 15/7/2016-6728/16 md.)",
        ("Bu Kanunda ve diğer kanunlarda, muhtasar beyanname ile aylık prim ve hizmet "
         "belgesine yapılmış olan atıflar, bu iki belgenin tek bir beyanname olarak "
         "birleştirildiği durumlarda, muhtasar ve prim hizmet beyannamesine yapılmış sayılır."),
        ("MaddeBasl", ""), ("MaddeBasl", "Muhtasar beyanname:"), "b) Muhteviyatı:",
        ("MsoNormal", "Madde 99 – (Değişik: 28/3/2007-5615/7 md.)"),
        ("MsoNormal", "Muhtasar beyannamenin şekil, içerik ve ekleri ile ..."))
    assert len(law.article("98/A").children) == 1
    assert law.article("99").title == "b) Muhteviyatı:"
    assert [(n.level, n.title) for n in law.body if n.level is Level.BOLUM] == [
        (Level.BOLUM, "Muhtasar beyanname:")]


def test_numbered_items_without_lead_text_are_fikras():
    # GVK md. 22: "1. Sigorta süresi ...", ..., which 6728/11 calls "(1) numaralı fıkrası".
    law = _gvk(
        "", "Menkul sermaye iratlarında:",
        ("MsoNormal", ("Madde 22 – (Mülga: 4/12/1985-3239/138 md.; Yeniden düzenleme: "
                       "9/4/2003-4842/2 md.)")),
        ("ksmblm", "1. (Değişik: 15/7/2016-6728/11 md.) Sigorta süresi en az on yıl ..."),
        ("MsoNormal", "2. (Ek: 15/7/2016-6728/11 md.) 75 inci maddenin ikinci fıkrasının ..."),
        ("MsoNormal", "3. Tam mükellef kurumlardan elde edilen, ..."))
    assert shape(law.article("22")) == [("fikra", "1."), ("fikra", "2."), ("fikra", "3.")]
    # 7491/8 "22 nci maddesine aşağıdaki fıkralar eklenmiştir.": the same in the act
    # (quotes already stripped, as in _make_ops).
    new = parse_fragment(["4. Kanuni ve iş merkezi Türkiye’de bulunmayan ...",
                          "5. Cumhurbaşkanı, üçüncü ve dördüncü fıkralarda ..."],
                         Level.FIKRA)
    assert [(n.level, n.label) for n in new] == [(Level.FIKRA, "4."), (Level.FIKRA, "5.")]


def test_short_line_after_an_open_list_closes_the_fikra():
    # GVK md. 109: "Tarh edilir." ends fıkra 1; 7349/3 repeals the "ikinci ve üçüncü
    # fıkraları" after it.
    law = _gvk(
        "", "Tarh zamanı:", "Madde 109 – (Değişik: 24/12/1980-2361/74 md.)", "",
        "Gelir Vergisi:",
        ("1. Beyanname verilmesi icabeden hallerde, beyannamenin verildiği günde, beyanname "
         "posta ile gönderilmişse, vergiyi tarh edecek daireye geldiği tarihi takibeden yedi "
         "gün içinde;"),
        "2. (Mülga:22/12/2021-7349/3 md.)", "3. (Mülga: 22/7/1998-4369/82 md.)",
        "Tarh edilir.",
        "(Mülga ikinci fıkra:22/12/2021-7349/3 md.)",
        "(Mülga üçüncü fıkra:22/12/2021-7349/3 md.)")
    f1, f2, f3 = law.article("109").children
    assert shape(f1) == [("bent", "1."), ("bent", "2."), ("bent", "3."), ("paragraf", "")]
    assert f1.children[-1].text == "Tarh edilir." and f2.repealed and f3.repealed


def test_book_heading():
    # VUK (213): "İKİNCİ KİTAP" / "Mükellefin Ödevleri" after md. 152/A, not its text.
    law = _gvk(
        "", "Uluslararası anlaşmalar gereğince bilgi değişimi:",
        "Madde 152/A – (Ek: 24/5/2013-6487/9 md.)",
        "Maliye Bakanlığı Gelir İdaresi Başkanlığı ... bilgi toplayabilir.",
        "İKİNCİ KİTAP", "Mükellefin Ödevleri", "BİRİNCİ KISIM", "Bildirmeler",
        "İşe başlamayı bildirme:", "Madde 153 – Aşağıda yazılı mükelleflerden ...")
    assert len(law.article("152/A").children) == 1
    assert [(n.label, n.title) for n in law.body if n.level is Level.KISIM][-2:] == [
        ("İKİNCİ KİTAP", "Mükellefin Ödevleri"), ("BİRİNCİ KISIM", "Bildirmeler")]


def test_comma_list_closed_by_a_short_line():
    # VUK mükerrer 227: "Bu uygulamalara ilişkin usul ve esasları belirlemeye
    # yetkilidir." ends fıkra 1; 7338/22 counts the fıkras after it.
    law = _gvk(
        "", "Vergi Beyannamelerinin İmzalanması ve Yeminli Mali Müşavir Tasdik Raporları:",
        "Mükerrer Madde 227 – (Ek: 23/10/1988 - 3505/4 md.)",
        "Maliye Bakanlığı:",
        ("1. Vergi beyannamelerinin 3568 sayılı Kanuna göre yetki almış serbest muhasebeci, "
         "serbest muhasebeci mali müşavir veya yeminli mali müşavirler tarafından imzalanması "
         "mecburiyetini getirmeye, bu mecburiyeti beyanname çeşitleri, mükellef grupları ve "
         "faaliyet konuları itibariyle ayrı ayrı uygulatmaya,"),
        ("2. Vergi kanunlarında yer alan muafiyet, istisna, yeniden değerleme, zarar mahsubu ve "
         "benzeri hükümlerden yararlanılmasını Maliye Bakanlığınca belirlenen şartlara uygun "
         "olarak yeminli mali müşavirlerce düzenlenmiş tasdik raporu ibraz edilmesi şartına "
         "bağlamaya,"),
        "Bu uygulamalara ilişkin usul ve esasları belirlemeye yetkilidir.",
        ("Yukarıdaki fıkra hükümlerine göre beyannameyi imzalayan veya tasdik raporunu "
         "düzenleyen meslek mensupları, ..."))
    f1, f2 = law.article("mukerrer-227").children
    assert shape(f1) == [("bent", "1."), ("bent", "2."), ("paragraf", "")]
    assert f2.text.startswith("Yukarıdaki fıkra")


def test_title_in_a_heading_tag():
    # VUK md. 215's title is an <h3> between empty ones.
    html = ("<html><body><p>Kayıt Nizamı</p><h3>&nbsp;</h3>"
            "<h3>Türkçe tutma ve Türk Parası kullanma zorunluluğu</h3>"
            "<p>Madde 215 – (Değişik: 4/12/2003-5024/5 md.)</p>"
            "<p>Kayıtlar Türkçe tutulur.</p></body></html>")
    law = build_tree(html, 213)
    assert law.article("215").title == "Türkçe tutma ve Türk Parası kullanma zorunluluğu"


def test_line_that_goes_on_with_the_list_is_a_fikra():
    # GVK md. 54: "2 nci grup" is a fıkra like "1 inci grup" and "3 üncü grup".
    law = _gvk(
        "", "İşletme büyüklüğü ölçüleri", "Madde 54 – (Değişik: 30/12/1980-2361/12 md.)",
        "1 inci grup: Deniz ve iç su balıkları yetiştiriciliği;",
        ("a) Denizlerdeki sınırları belirlenebilen üretim alanlarında yapılan balık "
         "yetiştiriciliğinde (ağ kafes vb.) 500 (750) m2,"),
        ("b) İç su balıkları yetiştiriciliğinde sınırları belirlenebilen havuz (beton, toprak "
         "vb), göl, gölet ve baraj gölleri gibi üretim alanlarında 600 (900) m2,"),
        "2 nci grup: Denizlerde yapılan balık avcılığında toplam tekne boyu 20 (20) metre;",
        "3 üncü grup: Arıcılık ziraatinde kovan sayısı 500 (500) adet;")
    f1, f2, f3 = law.article("54").children
    assert shape(f1) == [("bent", "a)"), ("bent", "b)")]
    assert f2.text.startswith("2 nci grup") and f3.text.startswith("3 üncü grup")


def test_footnote_reference_without_its_link():
    # KDV md. 13/f1 (l): the reference to footnote 19 has no <a href="#_ftn19">.
    law = _gvk(
        "", "Diğer istisnalar:", "Madde 13 – Aşağıda belirtilen teslim ve hizmetler vergiden müstesnadır:",
        ('l) ... birlikte sağlanan diğer teslim ve hizmetler istisnanın kapsamına dahil '
         'değildir.),</span><sup><span class=MsoFootnoteReference>19</span></sup><span>'))
    (f,) = law.article("13").children
    (bl,) = f.children
    assert bl.text.endswith("dahil değildir.),") and bl.footnotes == [19]


def test_title_over_two_lines():
    # KDV md. 13
    law = _gvk(
        "", "Araçlar, kıymetli maden ve petrol aramaları ile ulusal güvenlik",
        "harcamaları ve yatırımlarda istisna",
        "Madde 13 – (Değişik : 26/3/1985 - 3174/1 md.)",
        "Aşağıdaki teslim ve hizmetler vergiden müstesnadır.")
    a = law.article("13")
    assert a.title == ("Araçlar, kıymetli maden ve petrol aramaları ile ulusal güvenlik "
                       "harcamaları ve yatırımlarda istisna")
    assert [c.text for c in a.children] == ["Aşağıdaki teslim ve hizmetler vergiden müstesnadır."]
    # A list item under a short line stays an item.
    law = _gvk("", "Diğer istisnalar", "a) ilk bent", "Madde 13 – Metin.")
    assert law.article("13").title != "Diğer istisnalar a) ilk bent"


def test_bent_paragraphs_in_a_numbered_fikra():
    # KVK md. 5/1: "I)" after "h)" is bent (ı), so "i)" is the next bent, not a roman alt
    # bent; the capitalised paragraphs after a bent are its paragraphs ("(i) bendinin
    # üçüncü paragrafı", 6009/43), and a lower-case one after alt bents goes on with the
    # bent (j).
    law = _gvk(
        "", "Kurumlar vergisi istisnaları", "MADDE 5- (1) Aşağıda belirtilen kazançlar, ...:",
        "h) Yurt dışında yapılan inşaat, onarım, montaj işleri ile teknik hizmetlerden ...",
        "I) Okul öncesi eğitim, ilköğretim, özel eğitim ve orta öğretim özel okulları, ...",
        ("i) (Değişik birinci cümle: 28/11/2017-7061/89 md.) Kooperatif ortaklarının yönetim "
         "gideri karşılığı olarak ..."),
        "Bu risturnların ortaklara dağıtımı, kâr dağıtımı sayılmaz. ...",
        ("j) (Ek: 15/7/2016-6728/56 md.) Her türlü taşınır ve taşınmaz malların 6361 sayılı "
         "Kanun kapsamında ..."),
        "Söz konusu varlıkların,",
        "i) Kiracı tarafından veya",
        "ii) Kiralayan kurumlar tarafından finansal kiralama yöntemi dâhil olmak üzere ...",
        "üçüncü kişi ve kurumlara satılması durumunda, kiralayan kurumlara devrinden önce ...",
        "(2) Cumhurbaşkanı, bu maddede yer alan; ...")
    f1, _ = law.article("5").children
    assert [b.label for b in f1.children] == ["h)", "I)", "i)", "j)"]
    _, bi, bii, bj = f1.children
    assert bi.children == [] and shape(bii) == [("paragraf", "")]
    assert shape(bj) == [("paragraf", ""), ("alt_bent", "i)"), ("alt_bent", "ii)"),
                         ("paragraf", "")]


def test_lower_case_line_after_bents_ends_the_fikra_sentence():
    # KVK md. 5/B/2: "... gerekmektedir." closes the fıkra's sentence, after its bents.
    law = _gvk(
        "", "Patentli veya faydalı model belgeli buluşa ilişkin kazanç istisnası",
        "MADDE 5/B- (1) Kurumların, ...",
        "(2) Bu istisnadan yararlanılabilmesi için;",
        "a) Buluşun Türkiye’de gerçekleştirilen araştırma, ...",
        "b) Buluş üzerinde ... ",
        "gerekmektedir.")
    _, f2 = law.article("5/B").children
    assert shape(f2) == [("bent", "a)"), ("bent", "b)"), ("paragraf", "")]


def test_new_articles_under_a_heading_keep_their_title():
    # 7524/40: "bölüm başlığı ile birlikte aşağıdaki ek madde": the heading's title is
    # broken after a comma and the article's title stands right under it.
    (a,) = parse_fragment([
        "İKİNCİ BÖLÜM",
        "Vergi Yükünün Hesaplanması, Asgari Tamamlayıcı Kurumlar Vergisi Matrahı,",
        "Oranı ve Hesabı",
        "Vergi yükünün tespitinde düzeltilmiş kapsanan vergilerin hesaplanması",
        ("EK MADDE 4- (1) Net ülkesel bazlı kazanca sahip bir çok uluslu işletme grubunun "
         "vergi yükü, her hesap dönemi için ülkesel bazda ayrı ayrı hesaplanır."),
    ], Level.MADDE)
    assert a.id == "ek-4"
    assert a.title == "Vergi yükünün tespitinde düzeltilmiş kapsanan vergilerin hesaplanması"
    law = _gvk("", "İKİNCİ BÖLÜM",
               "Vergi Yükünün Hesaplanması, Asgari Tamamlayıcı Kurumlar Vergisi Matrahı,",
               "Oranı ve Hesabı", "", "Başlık", "Madde 4 – Metin.")
    assert law.body[0].title == ("Vergi Yükünün Hesaplanması, Asgari Tamamlayıcı Kurumlar "
                                 "Vergisi Matrahı, Oranı ve Hesabı")
    # GVK's YEDİNCİ BÖLÜM title is broken after "ve".
    law = _gvk("", "YEDİNCİ BÖLÜM", "Ortalama Kar Haddi, Asgari Gayri Safi Hasılat ve",
               "Gider Esaslarına Göre Gelir Tayini", "", "Başlık", "Madde 111 – Metin.")
    assert law.body[0].title == ("Ortalama Kar Haddi, Asgari Gayri Safi Hasılat ve Gider "
                                 "Esaslarına Göre Gelir Tayini")
    assert [a.id for a in law.body[0].children] == ["111"]
