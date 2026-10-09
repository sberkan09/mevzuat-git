"""Faz 2: rule-based parser for amendment sentences in Resmî Gazete texts.

An amending act is split into its own articles (``MADDE 5 –``). The first paragraph of an
article is the instruction ("193 sayılı Kanunun 41 inci maddesinin birinci fıkrasına (4)
numaralı bentten sonra gelmek üzere aşağıdaki (5) numaralı bent eklenmiştir."); when it
says "aşağıdaki", the following paragraphs are the new text.

An instruction can carry several operations ("... değiştirilmiş ve (15) numaralı bendi
yürürlükten kaldırılmıştır"). Operations are found by their verb patterns; the text
between two operations holds the address of the second one. Addresses that do not name
an article ("aynı maddenin", "fıkraya") are resolved against the previous address. See
docs/amendment-taxonomy.md for the formulas.

The new text is kept verbatim (quotes around it are not part of it and are dropped).
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path as FsPath

from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser

from mevzuat_git import mevzuat_gov as mg
from mevzuat_git.amendment_list import AmendingAct, AmendmentList
from mevzuat_git.fetch import Fetcher, NotFound, decode_html
from mevzuat_git.model import Amendment, AmendmentOp, Law, Level, Node, OpType, Path, label_key
from mevzuat_git.tree import ITEM_RE as LABEL_RE
from mevzuat_git.tree import TABLE_MARK, _follows, item_style, parse_fragment

Q_OPEN = "“\"‘"
Q_CLOSE = "”\"’"
Q = r"[“\"”]"
QTEXT = r"[^“”\"]*"

_UNITS = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk"]
_ORD_SUFFIX = {"bir": "birinci", "iki": "ikinci", "üç": "üçüncü", "dört": "dördüncü",
               "beş": "beşinci", "altı": "altıncı", "yedi": "yedinci", "sekiz": "sekizinci",
               "dokuz": "dokuzuncu", "on": "onuncu", "yirmi": "yirminci", "otuz": "otuzuncu",
               "kırk": "kırkıncı"}


def _ordinal_words() -> dict[str, int]:
    out = {}
    for n in range(1, 50):
        t, u = divmod(n, 10)
        words = [w for w in (_TENS[t], _UNITS[u]) if w]
        last = _ORD_SUFFIX[words[-1]]
        for sep in (" ", ""):
            out[sep.join(words[:-1] + [last])] = n
    return out


ORDINALS = _ordinal_words()
ORD_RE = "|".join(sorted((re.escape(w) for w in ORDINALS), key=len, reverse=True))
NUM_SUFFIX = r"(?:\s*['’]?\s*(?:inci|ıncı|uncu|üncü|nci|ncı|ncu|ncü|ünci|uncü))?"

LAW_REF_RE = re.compile(
    r"(?:(?P<date>" + mg.DATE_RE + r")\s+tarih(?:li)?\s+ve\s+)?(?P<no>\d+)\s+sayılı\s+"
    r"(?:(?:[A-ZÇĞİÖŞÜ0-9][\w’'.,]*|ve)\s+){0,12}?(?:Kanun|KANUN|Kanun\s+Hükmünde\s+Kararname)"
    r"\w*|(?P<same>[Aa]ynı\s+Kanun)\w*"
)
ARTICLE_REF_RE = re.compile(
    r"(?:(?P<pre>[Mm]ükerrer|[Gg]eçici|[Ee]k)\s+)?(?P<num>\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?)"
    + NUM_SUFFIX + r"\s+madde(?!\s*metn)(?:ler)?"
)
SAME_ARTICLE_RE = re.compile(r"[Aa]ynı\s+madde|\bmaddeye\b|\bmaddenin\b")
FIKRA_RE = re.compile(
    r"(?:(?P<ord>" + ORD_RE + r"|son)\s+fıkra|\((?P<num>\d+)\)\s*numaralı\s+fıkra)"
)
BENT_RE = re.compile(
    r"\((?P<key>[0-9]+|[a-zçğıöşü]{1,3})\)\s*(?:numaralı\s+)?(?P<alt>alt\s+)?ben[dt]"
)
ALT_ORD_RE = re.compile(r"(?P<ord>" + ORD_RE + r")\s+alt\s+ben[dt]")
BENT_ORD_RE = re.compile(r"(?P<ord>" + ORD_RE + r")\s+ben[dt]")  # "üçüncü bendinde" (5228)
CUMLE_RE = re.compile(r"(?P<ord>" + ORD_RE + r"|son)\s+cümle")
PARAGRAF_RE = re.compile(r"(?P<ord>" + ORD_RE + r"|son)\s+paragraf")
TITLE_TARGET_RE = re.compile(r"madde(?:sinin)?\s+başlığı(?!\s*(?:yla|\s+ile))")

# -- operation patterns (matched on the whole instruction) -------------------------------

PHRASE_NOUN = r"(?:ibare(?:si|leri)|cümle(?:si|leri)|rakam(?:ı|ları)|tarih(?:i|leri))"
_QQ = Q + QTEXT + Q
_QLIST = r"(?:" + _QQ + r"\s*(?:,|\bve\b)\s*)+" + _QQ
OP_PATTERNS: list[tuple[str, re.Pattern]] = [
    # “a” ve “b” ibareleri sırasıyla “x” ve “y” şeklinde
    ("replace_phrase_seq", re.compile(
        r"(?P<olds>" + _QLIST + r")\s*" + PHRASE_NOUN + r",?\s+sırasıyla\s+(?P<news>" + _QLIST
        + r")\s*(?:(?:şeklinde|olarak)\b|,(?=.*(?:şeklinde|olarak)\s+değiştiril))"
    )),
    ("replace_phrase", re.compile(
        Q + r"(?P<old>" + QTEXT + r")" + Q + r"\s*" + PHRASE_NOUN + r",?\s+(?:sırasıyla\s+)?"
        + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*(?:ibaresi\s+)?(?:(?:şeklinde|olarak)\b"
        # in a series the pairs are separated by commas: "X" ibaresi "Y", "Z" ibaresi "W"
        # şeklinde değiştirilmiştir
        r"|,(?=.*(?:şeklinde|olarak)\s+değiştiril)"
        # ... "Y," ve üçüncü fıkrasında yer alan "Z" ibaresi "W" olarak değiştirilmiştir
        r"|(?=\s+ve\s+[^“”\"]*" + Q + r".*(?:şeklinde|olarak)\s+değiştiril))"
    )),
    ("replace_phrase_yerine", re.compile(
        Q + r"(?P<old>" + QTEXT + r")" + Q + r"\s*" + PHRASE_NOUN + r"\s+yerine\s+"
        + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*(?:" + PHRASE_NOUN + r"\s+)?getiril"
    )),
    ("insert_phrase", re.compile(
        Q + r"(?P<anchor>" + QTEXT + r")" + Q + r"\s*(?:ibare|rakam|tarih|kelime)\w*\s+"
        r"(?P<pos>sonra|önce)(?:\s+gelmek\s+üzere)?\s*,?\s*"
        + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*(?:(?:" + PHRASE_NOUN + r"\s+)?eklen"
        # in a series: ... önce gelmek üzere “X”, “Y” ibaresinden sonra ... ibareleri eklenmiştir
        r"|,(?=\s*" + Q + r".*eklen)"
        # “Y” ibaresi ve (11) numaralı bendine ... eklenmiştir
        r"|" + PHRASE_NOUN + r"\s+ve\b(?=.*eklen))"
    )),
    # (5) numaralı fıkrasına birinci cümlesinden sonra gelmek üzere “...” ibaresi eklenmiş
    ("insert_phrase_cumle", re.compile(
        r"(?P<ord>" + ORD_RE + r"|son)\s+cümle\w*\s+(?P<pos>sonra|önce)\s+gelmek\s+üzere\s*,?\s*"
        + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*(?:" + PHRASE_NOUN + r"\s+)?eklen"
    )),
    ("append_phrase", re.compile(
        r"(?P<pos>sonuna|başına)\s+" + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*"
        r"(?:" + PHRASE_NOUN + r"\s+)?eklen"
    )),
    ("delete_phrase", re.compile(
        Q + r"(?P<old>" + QTEXT + r")" + Q + r"\s*" + PHRASE_NOUN
        + r"\s+(?:(?:madde|fıkra|bent)\s+)?(?:met(?:in|n)\w*\s+çıkarıl|yürürlükten\s+kaldırıl"
        # “X” ibaresi ile 6964 sayılı Kanunun ek 2 nci maddesi yürürlükten kaldırılmıştır
        r"|ile\b(?=[^“”\"]*(?:yürürlükten\s+kaldırıl|çıkarıl)))"
    )),
    ("paren_delete", re.compile(
        r"(?P<which>\w+\s+)?parantez\s+içi\s+hükm?ü?\w*\s+(?:(?:madde\s+)?met(?:in|n)\w*\s+"
        r"çıkarıl|yürürlükten\s+kaldırıl)"
    )),
    # parantez içi hükmü “(...)” olarak değiştirilmiştir
    ("paren_inline", re.compile(
        r"parantez\s+i[çc]i(?:\s+hükmü|nde\s+(?:yer\s+alan|bulunan)\s+ibare(?:si)?)\s+"
        + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*(?:şeklinde|olarak)\b"
    )),
    ("title_replace", re.compile(
        r"başlığı\s+" + Q + r"(?P<new>" + QTEXT + r")" + Q + r"\s*(?:şeklinde|olarak)\b"
    )),
    ("paren_replace", re.compile(
        r"parantez\s+i[çc]i(?:nde\s+(?:yer\s+alan|bulunan)\s+(?:ibare(?:si|ler)?|hüküm(?:ler)?)"
        r"|\s+hükm[üu](?:nü)?)\s+aşağıdaki\s+şekilde\s+değiştiril"
    )),
    ("replace_node", re.compile(
        r"(?P<title>başlığı(?:yla|\s+ile)\s+birlikte\s+)?aşağıdaki\s+şekilde\s+"
        r"(?:değiştiril|yeniden\s+düzenlen|düzenlen)"
    )),
    ("insert_node", re.compile(
        r"aşağıdaki\s+(?:(?P<label>\(\w+\))\s*(?:numaralı\s+)?)?(?P<kind>(?:alt\s+)?ben[dt](?:ler)?"
        r"|fıkra(?:lar)?|(?:(?:geçici|ek|mükerrer)\s+(?:\d+(?:/[A-ZÇĞİÖŞÜ])?\s*\w*\s+)?)?madde(?:ler)?"
        r"|cümle(?:ler)?|paragraf(?:lar)?"
        r"|parantez\s+içi\s+hüküm(?:ler)?)\w*\s*(?:eklen|(?:ile|ve)\b(?=.*eklen)|,(?=.*eklen))"
    )),
    ("repeal_node", re.compile(r"yürürlükten\s+kaldırılmış(?!\s+olan)")),
]


@dataclass
class ActArticle:
    """One article of the amending act: its instruction and the paragraphs below it."""

    number: str
    instruction: str
    payload: list[str] = field(default_factory=list)


ARTICLE_START_RE = re.compile(r"(?:(?:GEÇİCİ|EK|MÜKERRER|Geçici|Ek|Mükerrer)\s+)?(?:MADDE|Madde)\s+\d")
ACT_ARTICLE_RE = re.compile(
    r"^(?P<pre>GEÇİCİ\s+|EK\s+)?MADDE\s+(?P<num>\d+)\s*\.?\s*[–—‒-]\s*(?P<rest>.*)$"
)


def paragraphs(html: str) -> list[str]:
    """Non-empty paragraphs in order; a data table is one item (see ``tree.TABLE_MARK``).

    RG pages often lay out the whole text in tables; only tables that do not hold
    articles and have more than one column are treated as data (a tax tariff).
    """
    tree = LexborHTMLParser(html)
    out: list[str] = []
    if tree.body is None:
        return out
    data: list = [t for t in tree.css("table") if _is_data_table(t)]

    def in_data(node) -> bool:
        p = node.parent
        while p is not None:
            if p.tag == "table" and any(p.mem_id == d.mem_id for d in data):
                return True
            p = p.parent
        return False

    for node in tree.body.traverse():
        if node.tag == "table" and any(node.mem_id == d.mem_id for d in data):
            if in_data(node):
                continue
            rows = [[mg.squash(td.text()) for td in tr.css("td, th")] for tr in node.css("tr")]
            rows = [r for r in rows if any(r)]
            out.append(TABLE_MARK + "\n".join(" | ".join(r) for r in rows))
        elif node.tag == "p" and not in_data(node) and (t := mg.squash(node.text())):
            out.append(t)
    return out


def _is_data_table(t) -> bool:
    text = mg.squash(t.text())
    if not text or len(text) > 4000 or re.search(r"\bMADDE\s+\d+", text):
        return False
    rows = [[td for td in tr.css("td, th")] for tr in t.css("tr")]
    rows = [r for r in rows if any(mg.squash(td.text()) for td in r)]
    return bool(rows) and max(len(r) for r in rows) >= 2 and not t.css("table table")


def _quote_balance(text: str) -> int:
    """Open quotes minus closed ones. Older texts use '"' on both sides: an odd count opens
    when the paragraph starts with it and closes otherwise."""
    b = text.count("“") - text.count("”")
    if text.count('"') % 2:
        b += 1 if text.lstrip().startswith('"') else -1
    return b


def act_articles(paras: list[str], law_no: str | None = None) -> list[ActArticle]:
    """Split the paragraphs of an act into its articles.

    On day pages that hold several acts (before ~2005), ``law_no`` selects the act: its
    text starts at "Kanun No. <law_no>" and ends at the next "Kanun No.".
    """
    if law_no is not None:
        start = next((i for i, p in enumerate(paras)
                      if re.search(rf"Kanun\s+(?:No|Numarası)\s*[.:]*\s*{law_no}\b", p)), None)
        if start is not None:
            # The next act's header; the same act's header may come twice, as a table
            # and as its cell (4684).
            end = next((j for j in range(start + 1, len(paras))
                        if (m := re.search(r"Kanun\s+(?:No|Numarası)\s*[.:]*\s*(\d+)\b",
                                           paras[j])) and m.group(1) != law_no),
                       len(paras))
            paras = paras[start:end]
    arts: list[ActArticle] = []
    balance = 0
    expect_gecici = False  # "aşağıdaki geçici maddeler eklenmiştir" without quotes (4842)
    for p in paras:
        m = ACT_ARTICLE_RE.match(p)
        if m and m.group("pre") and expect_gecici:
            m = None
        if m and balance <= 0 and not m.group("pre"):
            expect_gecici = bool(re.search(r"aşağıdaki\s+(?:geçici|ek)\s+madde",
                                           m.group("rest")))
            arts.append(ActArticle(number=m.group("num"), instruction=m.group("rest")))
            balance = 0
            continue
        if m and balance <= 0 and m.group("pre"):
            # The act's own geçici/ek articles end the previous article's payload.
            pre = "gecici" if m.group("pre").startswith("G") else "ek"
            arts.append(ActArticle(number=f"{pre}-{m.group('num')}",
                                   instruction=m.group("rest")))
            balance = 0
            continue
        if arts:
            arts[-1].payload.append(p)
            balance += _quote_balance(p)
    return arts


LIST_VERB_RE = re.compile(
    r"^(?:(?P<how>[Şş]eklinde|[Oo]larak)\s+)?(?P<verb>değiştirilmiştir|yürürlükten\s+kaldırılmıştır"
    r"|eklenmiştir|metinden\s+çıkarılmıştır)\s*\.?$", re.IGNORECASE
)
_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})
GROUP_RE = re.compile(r"^\d+\s*[.)-]\s*(?P<text>.*)$")
ITEM_RE = re.compile(r"^[a-zçğıöşü]{1,2}\s*\)\s*(?P<text>.*)$")


def expand_list(a: ActArticle) -> list[ActArticle] | None:
    """Rewrite a list article into one instruction per item.

    Some acts collect amendments to several laws in one article and put the verb last::

        MADDE 37 – 1. 31.12.1960 tarihli ve 193 sayılı Gelir Vergisi Kanununun;
        a) Mükerrer 21 inci maddesi,
        b) 23 üncü maddesinin birinci fıkrasının (14) numaralı bendi,
        2. ...
        Yürürlükten kaldırılmıştır.

    Each item becomes "<group head> <item> <verb>".
    """
    lines = [a.instruction] + a.payload
    verb_at = next((i for i in range(len(lines) - 1, 0, -1) if LIST_VERB_RE.match(lines[i])),
                   None)
    if verb_at is None:
        if ITEM_RE.match(lines[0]) and LAW_REF_RE.search(lines[0]):
            # "MADDE 14 – a) 375 sayılı KHK’ye ... eklenmiştir." then "b) 193 sayılı ...":
            # items that each name their law and carry their own verb (5436). An item's
            # new text may be unquoted ("f) Bakanlar Kurulunca ..."), so only a line that
            # names a law starts the next item.
            head, rest = "", lines
        elif (re.search(r"sayılı\s.*[;:]$", lines[0]) and len(lines) > 1
              and ITEM_RE.match(lines[1])):
            # "193 sayılı Kanunun;" followed by items that carry their own verbs (5527, 7578).
            head, rest = lines[0].rstrip(";:").rstrip(), lines[1:]
        else:
            return None
        out = []
        sub = None  # "b) (13) numaralı bendinin;" then "1) Birinci cümlesinde ..." (6728)
        balance = 0
        for line in rest:
            if balance <= 0 and (it := ITEM_RE.match(line)) and (head or LAW_REF_RE.search(line)):
                item = it.group("text").rstrip()
                sub = None
                if item.endswith((";", ":")):
                    sub = f"{head} {item.rstrip(';:').rstrip()}".lstrip()
                    continue
                out.append(ActArticle(number=a.number, instruction=f"{head} {item}".lstrip()))
                balance = 0
            elif balance <= 0 and sub and (g := GROUP_RE.match(line)):
                # Mid-sentence once joined: "bendinin birinci cümlesinde".
                item = g.group("text").rstrip()
                low = item[:1].translate(_TR_LOWER).lower() + item[1:]
                if re.match(r"(?:" + ORD_RE + r"|son)\s", low):
                    item = low
                out.append(ActArticle(number=a.number, instruction=f"{sub} {item}"))
                balance = 0
            elif out:
                out[-1].payload.append(line)  # the new text of the item before
                balance += _quote_balance(line)
            else:
                return None
        return out or None
    head = ""
    if not GROUP_RE.match(lines[0]):
        if not (lines[0].rstrip().endswith((";", ":")) and len(lines) > 1):
            return None
        if GROUP_RE.match(lines[1]):
            # "MADDE 1 – Bu maddenin yayımı tarihinde;" then the groups (6462).
            pass
        elif ITEM_RE.match(lines[1]):
            # "193 sayılı Kanunun;" then items and one verb for all of them (6353).
            head = lines[0].rstrip().rstrip(";:").rstrip()
        else:
            return None
        lines = lines[1:]
        verb_at -= 1
    vm = LIST_VERB_RE.match(lines[verb_at])
    verb = (vm.group("how").lower() + " " if vm.group("how") else "") + vm.group("verb").lower()
    out: list[ActArticle] = []
    for line in lines[:verb_at]:
        if g := GROUP_RE.match(line):
            text = g.group("text").rstrip()
            if text.endswith((";", ":")):
                head = text.rstrip(";:").rstrip()
                continue
            head = ""
            out.append(ActArticle(number=a.number, instruction=f"{text.rstrip(',')} {verb}"))
        elif (it := ITEM_RE.match(line)) and head:
            item = it.group("text").rstrip().rstrip(",;").rstrip()
            out.append(ActArticle(number=a.number, instruction=f"{head} {item} {verb}"))
    return out or None


# -- addresses ---------------------------------------------------------------------------

def _ord(word: str) -> int:
    return -1 if word == "son" else ORDINALS[word]


def _article_id(m: re.Match) -> str:
    return mg.article_id(m.group("pre"), m.group("num"))


def law_segments(text: str, default: str | None) -> list[tuple[str | None, int, int]]:
    """Split ``text`` by law references: ``(law_no, start, end)`` of each piece."""
    pieces: list[tuple[str | None, int, int]] = []
    cur, pos = default, 0
    for m in LAW_REF_RE.finditer(text):
        # "4842 sayılı Kanunla yürürlükten kaldırılan" names who repealed it, not a target.
        if m.group(0).endswith(("la", "le")) or text[m.end():].startswith(" ile "):
            continue
        pieces.append((cur, pos, m.start()))
        cur = cur if m.group("same") else m.group("no")
        pos = m.end()
    pieces.append((cur, pos, len(text)))
    return [p for p in pieces if p[2] > p[1]]


def parse_address(seg: str, ctx: Path | None) -> Path | None:
    """The address named in ``seg``; missing parts come from ``ctx`` where ``seg``
    refers back ("aynı maddenin", "fıkraya", or nothing at all)."""
    # "mülga ikinci fıkrasından sonra gelen üçüncü fıkrası": the target is the last one.
    seg = _drop_after_gelen(seg)
    arts = list(ARTICLE_REF_RE.finditer(seg))
    fik = list(FIKRA_RE.finditer(seg))
    bents = list(BENT_RE.finditer(seg))
    alt_ord = list(ALT_ORD_RE.finditer(seg))
    bent_ord = list(BENT_ORD_RE.finditer(seg))
    cum = list(CUMLE_RE.finditer(seg))
    par = list(PARAGRAF_RE.finditer(seg))
    title = TITLE_TARGET_RE.search(seg)
    if arts:
        path = Path(madde=_article_id(arts[0]))
    elif ctx is None:
        return None
    elif not (fik or bents or alt_ord or bent_ord or cum or par or title) \
            and re.match(r"\s*bu\s+(?:alt\s+)?(?:madde|fıkra|bent|paragraf)\w*\s", seg):
        # "bu fıkrada yer alan" (a footnote of the consolidated text): the node itself.
        return ctx
    elif fik or SAME_ARTICLE_RE.search(seg):
        path = Path(madde=ctx.madde)
    elif any(not b.group("alt") for b in bents) or re.search(
        r"\bfıkra(?:ya|nın|sına|da)\b|aynı\s+fıkra", seg
    ):
        path = Path(madde=ctx.madde, fikra=ctx.fikra)
    elif (bents or re.search(r"\bbend(?:e|in|inde)\b|aynı\s+bent", seg)) and ctx.bent:
        # "(b) alt bendine": an alt bent of the bent in context.
        path = Path(madde=ctx.madde, fikra=ctx.fikra, bent=ctx.bent)
    elif cum or par:
        path = ctx.model_copy(update={"cumle": None, "paragraf": None, "baslik": False})
    else:
        return ctx
    if fik:
        f = fik[0]
        path.fikra = _ord(f.group("ord")) if f.group("ord") else int(f.group("num"))
    for b in bents:
        if b.group("alt"):
            path.alt_bent = b.group("key")
        elif path.bent is None:
            path.bent = b.group("key")
    if bent_ord and path.bent is None:
        path.bent = str(_ord(bent_ord[0].group("ord")))
    if alt_ord and path.alt_bent is None:
        path.alt_bent = str(_ord(alt_ord[0].group("ord")))
    if par:
        path.paragraf = _ord(par[0].group("ord"))
    if cum:
        path.cumle = _ord(cum[0].group("ord"))
    path.baslik = bool(title) and not fik and not bents
    return path


def _drop_after_gelen(seg: str) -> str:
    """Drop "<ordinal> fıkrasından sonra gelen", which only describes the target."""
    return re.sub(r"\S*\s+\S*(?:dan|den|tan|ten)\s+sonra\s+gelen\s+", " ", seg)


_ART_ITEM = r"(?:(?:[Mm]ükerrer|[Gg]eçici|[Ee]k)\s+)?\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?" + NUM_SUFFIX
ART_LIST_RE = re.compile(
    r"(?P<items>(?:" + _ART_ITEM + r"\s*(?:,|\bve\b|\bile\b)\s*)+" + _ART_ITEM + r")"
    r"\s+maddeler"
)
FIKRA_LIST_RE = re.compile(
    r"(?P<items>(?:\(\d+\)\s*(?:,|\bve\b|\bile\b)\s*)+\(\d+\))\s*numaralı\s+fıkralar"
    r"|(?P<ords>(?:(?:" + ORD_RE + r")\s*(?:,|\bve\b|\bile\b)\s*)+(?:" + ORD_RE + r"))"
    r"\s+fıkralar"
)
BENT_LIST_RE = re.compile(
    r"(?P<items>(?:\(\w+\)\s*(?:,|\bve\b|\bile\b)\s*(?:değişik\s+)?)+\(\w+\))\s*numaralı\s+"
    r"(?P<alt>alt\s+)?bentler"
)


def expand_targets(seg: str, path: Path) -> list[Path]:
    """"18, 19 ve 22 nci maddeleri", "(1), (5) ve (7) numaralı bentlerine": one path each."""
    if m := ART_LIST_RE.search(seg):
        ids = [mg.article_id(i.group("pre"), i.group("num"))
               for i in ARTICLE_ITEM_RE.finditer(m.group("items"))]
        return [path.model_copy(update={"madde": i}) for i in ids]
    if m := FIKRA_LIST_RE.search(seg):
        if m.group("items"):
            nums = [int(k) for k in re.findall(r"\((\d+)\)", m.group("items"))]
        else:
            nums = [ORDINALS[w.group(0)] for w in re.finditer(ORD_RE, m.group("ords"))]
        return [path.model_copy(update={"fikra": k}) for k in nums]
    if m := BENT_LIST_RE.search(seg):
        keys = re.findall(r"\((\w+)\)", m.group("items"))
        field = "alt_bent" if m.group("alt") else "bent"
        return [path.model_copy(update={field: k}) for k in keys]
    return [path]


ARTICLE_ITEM_RE = re.compile(
    r"(?:(?P<pre>[Mm]ükerrer|[Gg]eçici|[Ee]k)\s+)?(?P<num>\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?)"
)


# -- instructions -----------------------------------------------------------------------

KIND_WORDS = {"bent": Level.BENT, "alt bent": Level.ALT_BENT, "fıkra": Level.FIKRA,
              "madde": Level.MADDE, "geçici madde": Level.MADDE, "ek madde": Level.MADDE,
              "paragraf": Level.PARAGRAF, "cümle": Level.PARAGRAF,
              "parantez içi hüküm": Level.PARAGRAF}


def _kind(word: str) -> Level:
    w = re.sub(r"(ler|lar)$", "", mg.squash(word))
    w = re.sub(r"bend$", "bent", w)
    if w.endswith("madde"):
        return Level.MADDE
    return KIND_WORDS[w]


@dataclass
class OpMatch:
    name: str
    m: re.Match

    @property
    def start(self) -> int:
        return self.m.start()

    @property
    def end(self) -> int:
        return self.m.end()


def find_ops(text: str) -> list[OpMatch]:
    """All operation patterns in ``text``, left to right, without overlaps."""
    found: list[OpMatch] = []
    for name, rx in OP_PATTERNS:
        for m in rx.finditer(text):
            found.append(OpMatch(name, m))
    found.sort(key=lambda o: (o.start, -(o.end - o.start)))
    out: list[OpMatch] = []
    for o in found:
        if out and o.start < out[-1].end:
            continue
        out.append(o)
    return out


def _strip_quotes(texts: list[str]) -> list[str]:
    """Drop the quotation marks that wrap new text; inner quotes are kept."""
    out = list(texts)
    if not out or out[0].startswith(TABLE_MARK):
        return out
    opened = out[0][:1] in Q_OPEN
    if opened:
        out[0] = out[0][1:].lstrip()
    m = re.search(r"[”\"’]\s*\.?\s*$", out[-1])
    if m and not out[-1].startswith(TABLE_MARK) and (opened or _quote_balance(" ".join(texts)) < 0):
        out[-1] = out[-1][:m.start()].rstrip()
    return [t for t in out if t]


def split_payload(payload: list[str], n: int) -> list[list[str]]:
    """Split the paragraphs below an instruction among ``n`` operations.

    With one operation it gets everything. Otherwise each quoted run of paragraphs
    (opening “ ... closing ”) goes to the next operation.
    """
    if n <= 1:
        return [payload]
    chunks: list[list[str]] = []
    cur: list[str] = []
    balance = 0
    for p in payload:
        cur.append(p)
        balance += _quote_balance(p)
        if balance <= 0 and re.search(r"[”\"]\s*\.?\s*$", p):
            chunks.append(cur)
            cur, balance = [], 0
    if cur:
        chunks.append(cur)
    if len(chunks) != n and len(payload) == n:
        # Older texts do not quote new text: one paragraph per operation.
        return [[p] for p in payload]
    if len(chunks) != n and (cuts := _restarts(payload)) and len(cuts) == n - 1:
        # Unquoted runs: a list that starts over ("9." then "2.", "d)" then "15.").
        bounds = [0, *cuts, len(payload)]
        return [payload[a:b] for a, b in itertools.pairwise(bounds)]
    return chunks


def _restarts(payload: list[str]) -> list[int]:
    """Indexes of paragraphs whose label does not continue an earlier one of its style
    (nor start a new list with "a)" or "1.")."""
    seen: dict[str, str] = {}  # style -> last key
    cuts: list[int] = []
    for i, p in enumerate(payload):
        rest = p
        first = True
        while m := LABEL_RE.match(rest):
            label = m.group("label")
            style, key = item_style(label), label_key(label)
            continues = _follows(seen[style], key) if style in seen else key in ("a", "1")
            if first and i > 0 and not continues:
                cuts.append(i)
            seen[style] = key
            rest, first = rest[m.end():], False
    return cuts


class Unparsed(Exception):
    pass


# A finite verb left in an address segment means an operation the patterns did not see;
# its text would otherwise be read as the next operation's address.
_STRAY_VERB_RE = re.compile(
    r"(?:değiştiril|eklen|kaldırıl|çıkarıl|düzenlen)(?:miş|mış)(?!\s+olan)\b"
)


def _check_segment(o: OpMatch, own: str) -> None:
    masked = re.sub(Q + QTEXT + Q, "_", own)
    # The verb that closes the previous operation: "... şeklinde değiştirilmiş, (17) ...".
    masked = re.sub(r"^\W*(?:(?:şeklinde|olarak)\s+)?\w+(?:miş|mış)\b", "", masked)
    if _STRAY_VERB_RE.search(masked):
        raise Unparsed(f"unrecognised operation before {o.name}: {own!r}")
    if o.name == "repeal_node" and (re.search(Q, own) or "parantez" in own):
        # "“X” ibaresi ile ... yürürlükten kaldırılmıştır", "parantez içi hüküm yürürlükten
        # kaldırılmıştır": not the whole node.
        raise Unparsed(f"repeal of part of a node: {own!r}")


def parse_instruction(text: str, payload: list[str], target_law: int,
                      law_ctx: str | None = None, ctx: Path | None = None) -> list[AmendmentOp]:
    """Operations on ``target_law`` in one instruction sentence of an amending act.
    ``ctx`` is the address that "bu fıkrada" and the like refer to, if any."""
    ops: list[AmendmentOp] = []
    matches = find_ops(text)
    payload_ops = [o for o in matches
                   if o.name in ("replace_node", "insert_node", "paren_replace")]
    chunks = split_payload(payload, len(payload_ops))
    target = str(target_law)
    cur_law = law_ctx
    prev_end = 0
    for o in matches:
        seg = text[prev_end:o.start]
        prev_end = o.end
        pieces = law_segments(seg, cur_law)
        cur_law = pieces[-1][0] if pieces else cur_law
        raw: list[str] = []
        if o in payload_ops:
            i = payload_ops.index(o)
            raw = chunks[i] if i < len(chunks) else []
        mine = [(a, b) for law, a, b in pieces if law == target]
        # "193 sayılı Kanunun X ... ile 5520 sayılı Kanunun Y ... değiştirilmiştir": the
        # operation covers every law named before it.
        addressed = [law for law, a, b in pieces if ARTICLE_REF_RE.search(seg[a:b])]
        if not mine or (cur_law != target and target not in addressed):
            ctx = None
            continue
        own = "".join(seg[a:b] for a, b in mine)
        if o.name == "title_replace" and re.search(r"bölümünün|kısmının", own):
            continue  # heading of a kısım/bölüm: not addressable yet
        if raw and len(addressed) > 1 and len(set(addressed)) == len(addressed):
            parts = split_payload(raw, len(addressed))
            if len(parts) == len(addressed):
                raw = parts[addressed.index(target)]
        _check_segment(o, own)
        targets: list[tuple[Path, str]] = []
        for sub in split_addresses(own):
            path = parse_address(sub, ctx)
            if path is None and o.name == "insert_node" \
                    and _kind(o.m.group("kind")) is Level.MADDE:
                path = Path(madde="")  # "193 sayılı Kanuna aşağıdaki geçici madde eklenmiştir"
            if path is None:
                raise Unparsed(f"no address for {o.name}: {seg!r}")
            ctx = path
            targets.extend((t, sub) for t in expand_targets(sub, path))
        n = len(targets)
        if n > 1 and raw and (o.name in ("replace_node", "insert_node") or "sırasıyla" in text):
            parts = split_payload(raw, n)
            if len(parts) != n:
                parts = split_by_labels(raw, [t for t, _ in targets])
            if len(parts) != n:
                raise Unparsed("cannot split new text among targets")
        else:
            parts = [raw] * n
        for (t, sub), part in zip(targets, parts, strict=True):
            ops.extend(_make_ops(o, _after_inserts(t, sub, ops), sub, _strip_quotes(part), text))
    return ops


def _after_inserts(path: Path, sub: str, ops: list[AmendmentOp]) -> Path:
    """"birinci fıkrasından sonra gelmek üzere aşağıdaki fıkra eklenmiş, mevcut ikinci
    fıkrasında ...": "mevcut" counts fıkralar before the insert earlier in the sentence,
    which is applied first. Return the position the fıkra has once that is done."""
    if not re.search(r"\bmevcut\b", sub) or not path.fikra or path.fikra < 1:
        return path
    n = path.fikra
    for op in ops:
        t = op.target
        if op.op is not OpType.INSERT_NODE or op.kind is not Level.FIKRA \
                or t.madde != path.madde or not t.fikra or t.fikra < 1 or t.bent:
            continue
        if (op.position == "after" and n > t.fikra) or (op.position == "before" and n >= t.fikra):
            n += len(op.new_nodes)
    return path.model_copy(update={"fikra": n})


# Separators between two addresses in one segment: "(6) numaralı bendi ile ... üçüncü
# fıkrası", "32 nci maddesi, 64 üncü maddesi, 108 inci maddesinin ...". A separator
# counts only after a complete address (one ending in its noun), so lists like "(1), (5)
# ve (7) numaralı bentleri" or "ikinci ve üçüncü fıkraları" stay whole for
# ``expand_targets``.
_SEPARATOR_RE = re.compile(r"\s*,\s*|\s+(?:ile(?!\s+birlikte)|ve)\s+")
_ENDS_WITH_NOUN_RE = re.compile(r"(?:fıkra|ben[dt]|paragraf|cümle|madde|başlığ)\w*$")
_ADDRESS_WORD_RE = re.compile(r"fıkra|ben[dt]|paragraf|cümle|madde|başlı")


def split_addresses(seg: str) -> list[str]:
    # Quoted ibareler are not addresses: "“– Tam ve dar mükellefler ...” paragrafından".
    masked = re.sub(Q + QTEXT + Q, lambda m: "_" * len(m.group(0)), seg)
    out: list[str] = []
    start = 0
    for m in _SEPARATOR_RE.finditer(masked):
        nxt = _SEPARATOR_RE.search(masked, m.end())
        right = masked[m.end():nxt.start() if nxt else len(masked)]
        # "(2) numaralı bendine, birinci paragraftan sonra gelmek üzere": a position.
        if _ENDS_WITH_NOUN_RE.search(masked[start:m.start()]) \
                and _ADDRESS_WORD_RE.search(masked[m.end():]) and "gelmek" not in right:
            out.append(seg[start:m.start()])
            start = m.end()
    out.append(seg[start:])
    return out


def split_by_labels(raw: list[str], targets: list[Path]) -> list[list[str]]:
    """Split unquoted new text among ``targets`` by the label each one starts with: "2."
    for fıkra 2, "b)" for alt bent b. An unlabelled target (an ordinal fıkra) starts at
    the next unlabelled paragraph."""
    def expected(t: Path) -> str | None:
        if t.alt_bent is not None:
            return t.alt_bent
        if t.bent is not None:
            return t.bent
        if t.fikra is not None and t.fikra > 0 and _target_level(t) is Level.FIKRA:
            return str(t.fikra)
        return None

    paras = _strip_quotes(raw)
    keys = [label_key(m.group("label")) if (m := LABEL_RE.match(p)) else None for p in paras]
    chunks: list[list[str]] = []
    for i, (p, key) in enumerate(zip(paras, keys, strict=True)):
        if not chunks:
            chunks.append([p])
            continue
        if len(chunks) < len(targets):
            want = expected(targets[len(chunks)])
            if want not in keys[i:]:
                want = None  # "dördüncü fıkrası": the new fıkra has no label
            if (key == want) if want is not None else key is None:
                chunks.append([p])
                continue
        chunks[-1].append(p)
    return chunks


def _make_ops(o: OpMatch, path: Path, seg: str, new_text: list[str],
              sentence: str) -> list[AmendmentOp]:
    g = o.m.groupdict()
    base = {"target": path, "source_sentence": sentence}
    teselsul = "teselsül" in sentence
    if o.name in ("replace_phrase", "replace_phrase_yerine"):
        plural = bool(re.search(r"ibareleri|cümleleri|rakamları|tarihleri",
                                text_after(o.m, "old")))
        return [AmendmentOp(op=OpType.REPLACE_PHRASE, old=g["old"], new=g["new"], all=plural,
                            **base)]
    if o.name == "replace_phrase_seq":
        olds = re.findall(Q + "(" + QTEXT + ")" + Q, g["olds"])
        news = re.findall(Q + "(" + QTEXT + ")" + Q, g["news"])
        if len(olds) != len(news):
            raise Unparsed("ibare counts differ in a 'sırasıyla' list")
        return [AmendmentOp(op=OpType.REPLACE_PHRASE, old=a, new=b, all=True, **base)
                for a, b in zip(olds, news, strict=True)]
    if o.name == "insert_phrase":
        return [AmendmentOp(op=OpType.INSERT_PHRASE, anchor=g["anchor"], new=g["new"],
                            position="after" if g["pos"] == "sonra" else "before", **base)]
    if o.name == "insert_phrase_cumle":
        return [AmendmentOp(op=OpType.INSERT_PHRASE, new=g["new"],
                            position="end" if g["pos"] == "sonra" else "start",
                            target=path.model_copy(update={"cumle": _ord(g["ord"])}),
                            source_sentence=sentence)]
    if o.name == "append_phrase":
        return [AmendmentOp(op=OpType.INSERT_PHRASE, new=g["new"],
                            position="end" if g["pos"] == "sonuna" else "start", **base)]
    if o.name == "delete_phrase":
        plural = "ibareleri" in text_after(o.m, "old")
        return [AmendmentOp(op=OpType.DELETE_PHRASE, old=g["old"], all=plural, **base)]
    if o.name == "title_replace":
        return [AmendmentOp(op=OpType.REPLACE_NODE, new=g["new"],
                            target=path.model_copy(update={"baslik": True}),
                            source_sentence=sentence)]
    if o.name == "paren_replace":
        if not new_text:
            raise Unparsed("parenthetical replacement without new text")
        return [AmendmentOp(op=OpType.REPLACE_PHRASE, paren=True, new=" ".join(new_text),
                            **base)]
    if o.name == "paren_delete":
        w = (g["which"] or "").strip()
        if w in ORDINALS and w != "birinci":
            raise Unparsed(f"which parenthetical: {g['which']!r}")
        return [AmendmentOp(op=OpType.REPLACE_PHRASE, paren=True, new="", **base)]
    if o.name == "paren_inline":
        return [AmendmentOp(op=OpType.REPLACE_PHRASE, paren=True, new=g["new"], **base)]
    if o.name == "repeal_node":
        return [AmendmentOp(op=OpType.REPEAL_NODE, **base)]
    if o.name == "replace_node":
        if not new_text:
            raise Unparsed("replace_node without new text")
        if path.baslik:
            # "maddesinin başlığı ile birinci fıkrası aşağıdaki şekilde": the title part.
            if len(new_text) != 1:
                raise Unparsed("new title is not one paragraph")
            return [AmendmentOp(op=OpType.REPLACE_NODE, new=new_text[0], target=path,
                                source_sentence=sentence)]
        kind = _target_level(path)
        with_title = bool(g.get("title"))
        nodes = parse_fragment(_unquote_articles(new_text), kind) \
            if kind is not Level.PARAGRAF else []
        if kind is not Level.PARAGRAF and not nodes:
            raise Unparsed(f"no {kind.value} in the new text")
        op = AmendmentOp(op=OpType.REPLACE_NODE, kind=kind, new_nodes=nodes,
                         with_title=with_title, **base)
        if kind is Level.PARAGRAF or path.cumle is not None:
            op.new = " ".join(new_text)
        return [op]
    if o.name == "insert_node":
        if not new_text:
            raise Unparsed("insert_node without new text")
        kind = _kind(g["kind"])
        position = "end"
        target = path
        anchor = None
        if m := re.search(r"(?:dan|den|tan|ten|ndan|nden)\s+(?P<pos>sonra|önce)\s+gelmek\s+üzere",
                          seg):
            position = "after" if m.group("pos") == "sonra" else "before"
            # “– Tam ve dar ...” paragrafından sonra: the anchor is a quoted text.
            if q := re.search(Q + "(" + QTEXT + ")" + Q + r"\s*\S*$", seg[:m.start()]):
                anchor = q.group(1)
        elif teselsul and g.get("label") and (n := label_key(g["label"])).isdigit() \
                and int(n) > 1 and kind in (Level.FIKRA, Level.BENT):
            # "maddeye aşağıdaki (2) numaralı fıkra eklenmiş ve mevcut (2) ... teselsül":
            # the label gives the place.
            position = "after"
            field = "fikra" if kind is Level.FIKRA else "bent"
            prev = int(n) - 1 if kind is Level.FIKRA else str(int(n) - 1)
            target = path.model_copy(update={field: prev})
        if g["kind"].startswith("parantez") and (anchor or position == "end"):
            # "“...” ibaresinden sonra gelmek üzere aşağıdaki parantez içi hüküm" (7566/3),
            # "bentlerine sırasıyla aşağıdaki parantez içi hükümler" (7194/13): text inside
            # the node's own text, not a paragraph.
            return [AmendmentOp(op=OpType.INSERT_PHRASE, anchor=anchor, new=" ".join(new_text),
                                position=position, target=target, source_sentence=sentence)]
        if kind is Level.PARAGRAF:
            nodes = []
            new = " ".join(new_text)
        else:
            nodes = parse_fragment(_unquote_articles(new_text), kind)
            new = None
            if not nodes:
                raise Unparsed(f"no {kind.value} in the new text")
        return [AmendmentOp(op=OpType.INSERT_NODE, kind=kind, new_nodes=nodes, new=new,
                            anchor=anchor, position=position, renumber=teselsul,
                            target=target, source_sentence=sentence)]
    raise Unparsed(o.name)


def _unquote_articles(texts: list[str]) -> list[str]:
    """“GEÇİCİ MADDE 76 – ...” “GEÇİCİ MADDE 77 – ...”: each new article quoted on its own.
    The quotes around each one are dropped so that the next article is seen."""
    out = list(texts)
    for i, t in enumerate(out):
        if i and t[:1] in Q_OPEN and ARTICLE_START_RE.match(t[1:].lstrip()):
            out[i] = t[1:].lstrip()
            out[i - 1] = re.sub(r"[”\"’]\s*$", "", out[i - 1]).rstrip()
    return out


def text_after(m: re.Match, group: str) -> str:
    """The match after ``group`` up to the next quoted text: the noun, not an ibare."""
    rest = m.string[m.end(group):m.end()]
    return re.split(Q + QTEXT + Q, rest[1:], maxsplit=1)[0]


def _target_level(p: Path) -> Level:
    if p.cumle is not None or p.paragraf is not None:
        return Level.PARAGRAF
    if p.alt_bent is not None:
        return Level.ALT_BENT
    if p.bent is not None:
        return Level.BENT
    if p.fikra is not None:
        return Level.FIKRA
    return Level.MADDE


AMEND_VERB_RE = re.compile(
    r"değiştiril|eklen|yürürlükten\s+kaldırıl|çıkarıl|düzenlen|getiril|teselsül"
)


@dataclass
class ParseResult:
    amendments: list[Amendment]
    unparsed: list[tuple[str, str, str]]  # (act article, instruction, reason)
    sentences: int  # instructions that name the target law


def mentions(text: str, target_law: int) -> bool:
    for m in LAW_REF_RE.finditer(text):
        if m.group("no") == str(target_law):
            return True
    return False


def parse_act(html: str, act_no: str, target_law: int, inline: bool = False) -> ParseResult:
    """Parse every article of act ``act_no`` that amends ``target_law``."""
    paras = paragraphs(html)
    arts = act_articles(paras, act_no if inline else None)
    if not arts and not inline:
        arts = act_articles(paras, act_no)
    amendments: list[Amendment] = []
    unparsed: list[tuple[str, str, str]] = []
    sentences = 0
    expanded: list[ActArticle] = []
    for a in arts:
        expanded.extend(expand_list(a) or [a])
    for a in expanded:
        a.instruction = re.sub(r"^\(\d+\)\s*", "", a.instruction)
        if a.number.startswith(("gecici-", "ek-")):
            continue  # the act's own transitional articles
        if not mentions(a.instruction, target_law) or not AMEND_VERB_RE.search(a.instruction):
            continue
        sentences += 1
        try:
            ops = parse_instruction(a.instruction, a.payload, target_law)
        except (Unparsed, KeyError, ValueError) as exc:
            unparsed.append((a.number, a.instruction, str(exc)))
            continue
        if not ops:
            unparsed.append((a.number, a.instruction, "no operation recognised"))
            continue
        amendments.append(Amendment(amending_law=act_no, article=a.number,
                                    target_law=target_law, ops=ops))
    return ParseResult(amendments, unparsed, sentences)


# -- all acts of a law ------------------------------------------------------------------

class UnparsedSentence(BaseModel):
    act: str
    article: str
    sentence: str
    reason: str


class ActOps(BaseModel):
    act: str
    rg_date: date | None
    rg_number: str | None
    text_url: str
    # "rg": parsed from the RG text; "footnotes": from the consolidated text's footnotes,
    # for acts whose RG text we cannot read (see ``ops_from_footnotes``).
    source: str = "rg"
    sentences: int  # instructions naming the target law
    amendments: list[Amendment] = Field(default_factory=list)
    unparsed: list[UnparsedSentence] = Field(default_factory=list)
    error: str | None = None

    def ops(self) -> list[AmendmentOp]:
        return [op for am in self.amendments for op in am.ops]


class OpsFile(BaseModel):
    """data/processed/<law>_ops.json: parser output for every act with an RG text."""

    target_law: int
    acts: list[ActOps]

    def ops(self) -> list[tuple[ActOps, Amendment, AmendmentOp]]:
        out = []
        for a in self.acts:
            for am in a.amendments:
                for op in am.ops:
                    out.append((a, am, op))
        return out


def parse_all(fetcher: Fetcher, alist: AmendmentList) -> OpsFile:
    """Parse the RG text of every act in the amendment list that has one."""
    acts: list[ActOps] = []
    for act in sorted(alist.acts, key=lambda a: (a.rg.date if a.rg else date.max,
                                                  int(a.number) if a.number.isdigit() else 0)):
        if not (act.rg and act.rg.text_url) or act.kind == "aym":
            continue
        rec = ActOps(act=act.number, rg_date=act.rg.date, rg_number=act.rg.number,
                     text_url=act.rg.text_url, sentences=0)
        acts.append(rec)
        if act.rg.text_url.endswith(".pdf"):
            rec.error = "RG text is a PDF"
            continue
        try:
            html = decode_html(fetcher.get(act.rg.text_url).content)
        except (NotFound, RuntimeError) as exc:
            rec.error = f"RG text not available: {exc}"
            continue
        inline = bool(act.rg.anchor) or not act.rg.text_url.rsplit("/", 1)[-1].count("-")
        res = parse_act(html, act.number, alist.target_law, inline=inline)
        rec.sentences = res.sentences
        for am in res.amendments:
            am.rg_date, am.rg_number = act.rg.date, act.rg.number
        rec.amendments = res.amendments
        rec.unparsed = [UnparsedSentence(act=act.number, article=a, sentence=s, reason=r)
                        for a, s, r in res.unparsed]
    return OpsFile(target_law=alist.target_law, acts=acts)


# -- operations from the consolidated text's footnotes -----------------------------------

# "2/7/2018 tarihli ve 700 sayılı KHK’nin 45 inci maddesiyle, bu bentte yer alan ..."
_FOOTNOTE_ACT = re.compile(r"^.*?\b\d+\s+sayılı\s+\S+\s+\d+\s*\S*\s+maddes[iı]yle,\s*")


def node_paths(law: Law) -> list[tuple[Node, Path, list[Node]]]:
    """Every node below an article with its address and its siblings, in text order."""
    out: list[tuple[Node, Path, list[Node]]] = []

    def visit(n: Node, path: Path) -> None:
        fikras = [c for c in n.children if c.level is Level.FIKRA]
        paras = [c for c in n.children if c.level is Level.PARAGRAF]
        for c in n.children:
            if c.level is Level.FIKRA:
                k = c.key
                p = path.model_copy(update={"fikra": int(k) if k and k.isdigit()
                                            else fikras.index(c) + 1})
            elif c.level is Level.BENT:
                p = path.model_copy(update={"bent": c.key})
            elif c.level is Level.ALT_BENT:
                p = path.model_copy(update={"alt_bent": c.key})
            elif c.level is Level.PARAGRAF:
                # Paragraph 1 is the node's own text.
                p = path.model_copy(update={"paragraf": paras.index(c) + 2})
            else:
                p = path
            out.append((c, p, n.children))
            visit(c, p)

    for art in law.articles():
        if art.id:
            visit(art, Path(madde=art.id))
    return out


def footnote_paths(law: Law) -> dict[int, Path]:
    """The address of the node each footnote number is attached to."""
    out: dict[int, Path] = {}
    for art in law.articles():
        if art.id:
            for fn in art.footnotes:
                out.setdefault(fn, Path(madde=art.id))
    for n, path, _ in node_paths(law):
        for fn in n.footnotes:
            out.setdefault(fn, path)
    return out


_NODE_PARTS = ("fikra", "bent", "alt_bent", "paragraf")


def _stand_in(ctx: Path) -> Path:
    return ctx.model_copy(update={
        "fikra": ctx.fikra + 9000 if ctx.fikra else ctx.fikra,
        "bent": f"§{ctx.bent}" if ctx.bent else ctx.bent,
        "alt_bent": f"§{ctx.alt_bent}" if ctx.alt_bent else ctx.alt_bent,
        "paragraf": ctx.paragraf + 9000 if ctx.paragraf else ctx.paragraf})


def ops_from_footnotes(act: AmendingAct, law: Law) -> tuple[list[Amendment],
                                                             list[UnparsedSentence]]:
    """Operations of ``act`` as the consolidated text's footnotes describe them: "700
    sayılı KHK’nin 45 inci maddesiyle, bu bentte yer alan “Bakanlar Kurulu” ibaresi
    “Cumhurbaşkanı” şeklinde değiştirilmiştir." For acts whose RG text is a scanned PDF.
    "bu bentte", "bu fıkrada" refer to the node the footnote is attached to."""
    paths = footnote_paths(law)
    by_article: dict[str, Amendment] = {}
    unparsed: list[UnparsedSentence] = []
    for fn in act.footnotes:
        article = fn.law_article or "?"
        m = _FOOTNOTE_ACT.match(fn.text)
        ctx = paths.get(fn.footnote)
        if not m or ctx is None:
            reason = "not an amendment sentence" if not m else "footnote not in the text"
            unparsed.append(UnparsedSentence(act=act.number, article=article,
                                             sentence=fn.text, reason=reason))
            continue
        try:
            ops = parse_instruction(fn.text[m.end():], [], law.number,
                                    law_ctx=str(law.number), ctx=ctx)
            if not ops:
                raise Unparsed("no operation")
            # Parsed again with stand-ins for the node's parts: the parts of a target that
            # come out as stand-ins are the ones taken from the node ("bu bentte"), as
            # against those the sentence names ("(8) numaralı bentte").
            marked = parse_instruction(fn.text[m.end():], [], law.number,
                                       law_ctx=str(law.number), ctx=_stand_in(ctx))
        except Unparsed as exc:
            unparsed.append(UnparsedSentence(act=act.number, article=article,
                                             sentence=fn.text, reason=str(exc)))
            continue
        for op, mk in zip(ops, marked, strict=True):
            op.source_sentence = fn.text
            op.footnote = fn.footnote
            op.footnote_path = ctx.model_copy(update={
                f: None for f in _NODE_PARTS
                if getattr(mk.target, f) is None or getattr(mk.target, f) != getattr(
                    _stand_in(ctx), f)})
        am = by_article.setdefault(article, Amendment(
            amending_law=act.number, article=article, target_law=law.number,
            rg_date=act.rg.date if act.rg else None,
            rg_number=act.rg.number if act.rg else None, ops=[]))
        am.ops.extend(ops)
    return list(by_article.values()), unparsed


# "(Ek: 29/1/2016-6663/2 md.)", "(Ek:11/11/2020-7256/16 md.)"
_EK_MARK = re.compile(r"\bEk\s*:\s*[\d/.]+\s*-\s*(?P<act>\d+)\s*/\s*(?P<art>\d+)\s*md\b")


def ops_from_markers(act: AmendingAct, law: Law) -> list[Amendment]:
    """Nodes that the consolidated text marks as added by ``act`` ("(Ek: 29/1/2016-6663/2
    md.)") when no footnote says so: an insertion after the node before it. The node's
    text is today's; a repealed node's text at the time is unknown."""
    from mevzuat_git.replay import UNKNOWN

    by_article: dict[str, Amendment] = {}
    nodes = node_paths(law)
    path_of = {id(n): p for n, p, _ in nodes}
    for n, _, sibs in nodes:
        marks = [m for note in n.notes for m in _EK_MARK.finditer(note)
                 if m.group("act") == act.number]
        i = next(k for k, c in enumerate(sibs) if c is n)
        if not marks or i == 0 or n.level not in (Level.BENT, Level.ALT_BENT, Level.FIKRA):
            continue
        prev = path_of[id(sibs[i - 1])]
        new = n.model_copy(deep=True, update={"notes": [], "footnotes": []})
        if n.repealed or not (n.text or n.children):
            new.text, new.repealed, new.children = UNKNOWN, False, []
        article = marks[0].group("art")
        op = AmendmentOp(op=OpType.INSERT_NODE, target=prev, position="after", kind=n.level,
                         new_nodes=[new], source_sentence=" ".join(n.notes))
        by_article.setdefault(article, Amendment(
            amending_law=act.number, article=article, target_law=law.number,
            rg_date=act.rg.date if act.rg else None,
            rg_number=act.rg.number if act.rg else None, ops=[])).ops.append(op)
    return list(by_article.values())


def add_footnote_ops(opsfile: OpsFile, alist: AmendmentList, law: Law) -> None:
    """Fill in acts whose RG text could not be read from the footnotes of ``law``."""
    acts = {a.number: a for a in alist.acts}
    for rec in opsfile.acts:
        act = acts.get(rec.act)
        if rec.error is None or act is None:
            continue
        marked = ops_from_markers(act, law)
        if not (act.footnotes or marked):
            continue
        rec.amendments, rec.unparsed = ops_from_footnotes(act, law)
        rec.amendments += marked
        rec.sentences = len(act.footnotes)
        rec.source = "footnotes"


def load_list(path: FsPath) -> AmendmentList:
    return AmendmentList.model_validate(json.loads(path.read_text()))
