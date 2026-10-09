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
    r"\((?:[^()]|\([^()]*\))*?(?:md\b\.?|Kararı\s+ile\.?|[Kk]anunla\.?)\s*\)"
)
_ELLIPSIS = re.compile(r"\(\s*(?:…|\.\s*\.\s*\.)\s*\)\d*")
# Amounts that mevzuat.gov.tr adds after an amount for its current value: "600 milyon
# lirayı (22.000 TL) aşmayan", "51 (300 TL) Türk lirasını".
_EDITORIAL_AMOUNT = re.compile(r"\s*\(\s*\d[\d.,]*\s*TL\s*\)")
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
    the law at an earlier date (Faz 4), where those additions would be anachronistic."""
    t = re.sub(r"[ \t]*" + _MARKER_ANYWHERE.pattern, "", text)
    t = _EDITORIAL_AMOUNT.sub("", t)
    t = _FOOTNOTE.sub("", t)
    return t.lstrip(" ") if t != text else text


def norm(text: str) -> str:
    t = _MARKER_ANYWHERE.sub(" ", text)
    t = _ELLIPSIS.sub(" ", t)
    t = _EDITORIAL_AMOUNT.sub("", t)
    t = t.translate(_TRANSLATE)
    t = " ".join(t.split())
    t = re.sub(r"\s+([,.;:)])", r"\1", t)
    t = re.sub(r"\(\s+", "(", t)
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
            out.append("# " + norm(n.title))
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
