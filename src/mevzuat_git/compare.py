"""Comparison layer: the only place where text is normalised.

mevzuat.gov.tr's consolidated text carries editorial additions (change markers such as
``(Ek cümle: 9/4/2003-4842/5 md.)`` inside the text, ``(…)`` where an ibare was removed)
and its own typography. RG texts and replay results do not. Both sides are normalised
here before comparison; stored texts are never changed.
"""

from __future__ import annotations

import re

from mevzuat_git.model import Level, Node

_MARKER_ANYWHERE = re.compile(
    # "(... sayılı Kararı ile)", "(... E.2010/93, K.2012/20 sayılı kararıyla)" (geçici 69)
    r"\((?:[^()]|\([^()]*\))*?(?:md\b\.?|[Kk]ararı(?:\s+ile|yla)\.?|[Kk]anunla\.?)\s*\)"
)
# "(Ek cümleler: 23/7/2010-6009/5 md.; İptal birinci cümle: Anayasa Mahkemesinin 9/2/2012
# tarihli ve E.2010/93, K.2012/20 sayılı kararıyla) Kalan kazanç ...": the annulled
# sentence was the first of those the marker introduces, so it stood right after it.
_ANNULLED_FIRST = re.compile(
    r"\((?:[^()]|\([^()]*\))*?;\s*İptal\s+birinci\s+cümle\s*:(?:[^()]|\([^()]*\))*?\)"
)
_ELLIPSIS = re.compile(r"\(\s*(?:…|\.\s*\.\s*\.)\s*\)\d*")
# Amounts that mevzuat.gov.tr adds after an amount for its current value: "600 milyon
# lirayı (22.000 TL) aşmayan", "51 (300 TL) Türk lirasını", "220.000 (1.900.000 TL.)
# Türk lirasını", and the space it leaves before a comma: "135.000 Türk lirasını
# (1.380.000 TL) , söz konusu". Also a range, "birmilyar ila yüzmilyar lira arasındaki
# (30.000-3.000.000 TL)" (VUK md. 104), and a bare number between an amount and its
# unit: "3.600 (30.000) Türk lirasından", "10 milyon (79.000.000) Türk lirasına", "25
# (0,43) kuruştan" (VUK md. 104, 257, 413). A bare number elsewhere is the law's own:
# "toplamı 300 (1000) dönüm" (GVK md. 52), and so are digits after an amount in words:
# "beş milyon (5.000.000,00) Türk Lirası" (6518).
_EDITORIAL_AMOUNT = re.compile(
    r"\s*\(\s*\d[\d.,]*(?:\s*-\s*\d[\d.,]*)?\s*TL\.?(?:\s*ve\s+üzeri)?\s*\)(?:\s+(?=[,;:]))?"
    r"|(?:(?<=\d)|(?<=\d\smilyon)|(?<=\d\smilyar))\s*\(\s*\d[\d.,]*\s*\)"
    r"(?=\s*(?:Türk\s+[Ll]ira|TL\b|YTL\b|kuruş|lira))"
)
_TRANSLATE = str.maketrans({
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "´": "'", "`": "'",
    "–": "-", "—": "-", " ": " ", "­": "",
    # Spelling: the consolidated text and the acts differ on the circumflex ("tâbi").
    "â": "a", "î": "i", "û": "u", "Â": "A", "Î": "I", "Û": "U",
})


_FOOTNOTE = re.compile(r"(?<=[^\d\s][.;:])\d{1,3}$")


def strip_editorial(text: str) -> str:
    """``text`` without what mevzuat.gov.tr adds to the law's own words: change markers,
    current values of old amounts and footnote numbers. ``(…)`` stays (it marks where an
    ibare was removed), and so do typography and spacing elsewhere. For output that shows
    the law at an earlier date (Faz 4), where those additions would be anachronistic, and
    for the unwind (Faz 3), which looks for the acts' ibareler in the text."""
    t = re.sub(r"[ \t]*" + _MARKER_ANYWHERE.pattern, "", text)
    t = _EDITORIAL_AMOUNT.sub("", t)
    t = _FOOTNOTE.sub("", t)
    return t.lstrip(" ") if t != text else text


def mark_annulled(text: str) -> str:
    """``text`` with a marker that records the annulment of the first sentence it
    introduces replaced by ``(…)``, the mark mevzuat.gov.tr otherwise leaves where words
    were removed. For the unwind, which puts an annulled ibare back at such a mark."""
    return _ANNULLED_FIRST.sub("(…)", text)


def norm(text: str) -> str:
    t = _MARKER_ANYWHERE.sub(" ", text)
    t = _ELLIPSIS.sub(" ", t)
    t = _EDITORIAL_AMOUNT.sub("", t)
    t = t.translate(_TRANSLATE)
    t = " ".join(t.split())
    t = re.sub(r"\s+([,.;:)])", r"\1", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"%\s+(?=\d)", "%", t)  # "% 15'ini" and "%15’ini" (7061/14)
    t = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", t)  # "1.1.1999 - 31.12.2004" (5035/48)
    # Article lists: "9/10,19, 21" (mükerrer 123) and "9/10, 19, 21" (4842/16); a decimal
    # comma ("1,5") is left alone.
    t = re.sub(r"(?<=\d/\d)(\d*),(?=\d)", r"\1, ", t)
    # A parenthesis that ends a sentence: 6327/6 "... irat tutarı dahil.).", mevzuat.gov.tr
    # "... dahil.)".
    t = re.sub(r"\.\)\.(?=\s|$)", ".)", t)
    # Unlinked footnote numbers glued to the end of a sentence: "yararlanılır.218".
    t = _FOOTNOTE.sub("", t)
    return t


def norm_label(label: str) -> str:
    return re.sub(r"\s+", "", label.translate(_TRANSLATE))


def node_lines(n: Node, with_title: bool = True) -> list[str]:
    """Normalised lines of a node and its subtree (no editorial notes)."""
    out: list[str] = []
    if n.level is Level.MADDE:
        if with_title and n.title:
            # "bilgi değişimi:" (mevzuat.gov.tr) and "bilgi değişimi" (6487/9).
            out.append("# " + norm(n.title).rstrip(":").rstrip())
        if n.text:
            out.append(norm(n.text))
    else:
        line = " ".join(p for p in (norm_label(n.label), norm(n.text)) if p)
        if line:
            out.append(line)
    for c in n.children:
        out.extend(node_lines(c))
    return out


def same(a: list[Node], b: list[Node]) -> bool:
    return [x for n in a for x in node_lines(n)] == [x for n in b for x in node_lines(n)]
