"""Faz 1: consolidated text (mevzuat.gov.tr iframe HTML) -> :class:`~mevzuat_git.model.Law`.

The Word-exported HTML has no reliable structure (``class="Nor"`` and ``"MsoNormal"`` are
used interchangeably), so the tree is rebuilt from the text of each paragraph:

* ``BİRİNCİ KISIM`` / ``İKİNCİ BÖLÜM`` lines, followed by their name, open headings;
* ``Madde 12 –``, ``Mükerrer Madde 20/A-``, ``Geçici Madde 67 –``, ``Ek Madde 1 –`` open an
  article; the paragraph right before it that ends with ``:`` is its title;
* inside an article, a paragraph is a fıkra, a bent or an alt bent depending on its label.
  ``(1)`` is a numbered fıkra; for item labels (``1.``, ``a)``, ``1)``, ``aa)`` ...) the
  level is the order in which the styles appear inside the fıkra: the first style seen is
  the bent level, a new style below it the alt bent level, and so on;
* unlabelled paragraphs are new fıkras, except in articles with numbered fıkras, where
  they are paragraphs of the current fıkra.

Text is kept verbatim (only HTML whitespace is collapsed). Footnote reference links
(``[12]``) and leading editorial markers (``(Değişik: 7/1/2003-4783/1 md.)``) are moved to
``Node.footnotes`` and ``Node.notes``; the text itself is not touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser, LexborNode

from mevzuat_git import mevzuat_gov as mg
from mevzuat_git.model import Law, Level, Node, label_key

ORDINAL = (
    r"(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU"
    r"|ON\s+\w+|YİRMİNCİ)"
)
HEADING_RE = re.compile(rf"^{ORDINAL}\s+(?P<kind>KISIM|BÖLÜM)$")
ARTICLE_RE = re.compile(
    r"^(?P<label>(?P<prefix>(?:Mükerrer|Mükerer|Geçici|Ek)\s+)?Madde\s+"
    r"(?P<num>\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ])?))\s*[–-]\s*",
    re.IGNORECASE,
)
# A leading editorial marker: "(Değişik: 7/1/2003-4783/1 md.)", "(Mülga: ...; Yeniden
# düzenleme: ...)", "(İptal: Anayasa Mahkemesinin ... sayılı Kararı ile.)".
LEADING_MARKER_RE = re.compile(
    r"^\((?:[^()]|\([^()]*\))*?(?:md\b\.?|Kararı\s+ile\.?|[Kk]anunla\.?)\s*\)\s*"
)
ITEM_RE = re.compile(
    r"^(?P<label>\(\d+\)|\d+\s*[.)]|\d+\s*-(?!\d)|[a-zçğıöşü]{1,4}\s*\)|\([a-zçğıöşü]{1,3}\))"
    r"\s*"
)
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


@dataclass(eq=False)
class Block:
    """A paragraph (or table) of the main text, before tree building."""

    text: str
    footnotes: list[int] = field(default_factory=list)
    table: list[list[str]] | None = None
    html_class: str = ""

    @property
    def blank(self) -> bool:
        return self.table is None and not self.text


def _in(node: LexborNode, pred) -> bool:
    p = node.parent
    while p is not None:
        if pred(p):
            return True
        p = p.parent
    return False


def _is_footnote_div(n: LexborNode) -> bool:
    return n.tag == "div" and (n.attributes.get("id") or "").startswith("ftn")


def _text_of(node: LexborNode) -> tuple[str, list[int]]:
    """Paragraph text without footnote reference links, and the footnote numbers."""
    fns: list[int] = []
    for a in node.css("a"):
        if m := re.fullmatch(r"#_ftn(\d+)", a.attributes.get("href") or ""):
            fns.append(int(m.group(1)))
            a.decompose()
    return mg.squash(node.text()), fns


def blocks(html: str) -> list[Block]:
    """Paragraphs and tables of the main text, in order, up to the appendices."""
    tree = LexborHTMLParser(html)
    out: list[Block] = []
    if tree.body is None:
        return out
    for node in tree.body.traverse():
        if node.tag not in ("p", "table"):
            continue
        if _in(node, _is_footnote_div) or _in(node, lambda n: n.tag == "table"):
            continue
        if node.tag == "table":
            rows = []
            fns: list[int] = []
            for tr in node.css("tr"):
                cells = []
                for td in tr.css("td, th"):
                    t, f = _text_of(td)
                    cells.append(t)
                    fns += f
                if any(cells):
                    rows.append(cells)
            out.append(Block(text="", footnotes=fns, table=rows))
            continue
        text, fns = _text_of(node)
        if mg.END_OF_MAIN_RE.search(text):
            break
        out.append(Block(text=text, footnotes=fns, html_class=node.attributes.get("class") or ""))
    return out


def split_markers(text: str) -> tuple[list[str], str]:
    notes = []
    while m := LEADING_MARKER_RE.match(text):
        notes.append(m.group(0).strip())
        text = text[m.end():]
    return notes, text


def _is_repeal(notes: list[str]) -> bool:
    if not notes:
        return False
    last = notes[-1].casefold()
    # "(Mülga: ...; Yeniden düzenleme: ...)" is in force again.
    events = [e for e in re.split(r";", last) if e.strip()]
    return any(w in events[-1] for w in ("mülga", "iptal")) if events else False


def item_style(label: str) -> str:
    k = re.sub(r"[\s().\-]", "", label)
    if label.startswith("(") and k.isdigit():
        return "fikra"
    if k.isdigit():
        return "num" + ("." if "." in label else ")" if ")" in label else "-")
    if label.startswith("("):
        return "(alpha)"
    return "alpha" if len(k) == 1 else "alpha2"


def article_id(prefix: str | None, num: str) -> str:
    return mg.article_id(prefix, num)


class _Builder:
    def __init__(self, law: Law) -> None:
        self.law = law
        self.kisim: Node | None = None
        self.bolum: Node | None = None
        self.article: Node | None = None
        self.fikra: Node | None = None
        self.stack: list[tuple[str, Node]] = []  # open item levels in the current fıkra
        self.numbered = False
        # The fıkra and item stack before the last unlabelled paragraph, to undo it when it
        # turns out to continue an item: "1. ...", "<unlabelled>", "2. ..." (GVK md. 7).
        self.prev: tuple[Node, list[tuple[str, Node]]] | None = None

    # -- containers -------------------------------------------------------------------

    def heading(self, level: Level, label: str, title: str | None) -> Node:
        n = Node(level=level, label=label, title=title)
        if level is Level.KISIM:
            self.law.body.append(n)
            self.kisim, self.bolum = n, None
        else:
            (self.kisim.children if self.kisim else self.law.body).append(n)
            self.bolum = n
        self.article = None
        return n

    def open_article(self, label: str, art_id: str, title: str | None, notes: list[str],
                     fns: list[int]) -> Node:
        a = Node(level=Level.MADDE, label=label, id=art_id, title=title, notes=notes,
                 footnotes=fns, repealed=_is_repeal(notes))
        parent = self.bolum or self.kisim
        (parent.children if parent else self.law.body).append(a)
        self.article, self.fikra, self.stack, self.numbered = a, None, [], False
        self.prev = None
        return a

    # -- content ----------------------------------------------------------------------

    def _new_fikra(self, label: str = "") -> Node:
        assert self.article is not None
        f = Node(level=Level.FIKRA, label=label)
        self.article.children.append(f)
        self.fikra, self.stack = f, []
        return f

    def paragraph(self, text: str, fns: list[int]) -> None:
        if self.article is None:
            return  # preamble lines between headings and the first article
        notes, rest = split_markers(text)
        label = ""
        if m := ITEM_RE.match(rest):
            label = m.group("label")
            rest = rest[m.end():]
            more, rest = split_markers(rest)
            notes += more
        repealed = _is_repeal(notes) and not rest
        if not label:
            if self.numbered and self.fikra is not None:
                parent = self.stack[-1][1] if self.stack else self.fikra
                node = Node(level=Level.PARAGRAF, text=rest, notes=notes, footnotes=fns,
                            repealed=repealed)
                (self.fikra if not self.stack else parent).children.append(node)
                return
            self.prev = (self.fikra, list(self.stack)) if self.fikra is not None else None
            f = self._new_fikra()
            f.text, f.notes, f.footnotes, f.repealed = rest, notes, fns, repealed
            return
        style = item_style(label)
        if style == "fikra":
            self.numbered = True
            f = self._new_fikra(label)
            f.text, f.notes, f.footnotes, f.repealed = rest, notes, fns, repealed
            return
        if style == "alpha" and label[0] in ROMAN:
            # "i)" after "h)" is a letter; otherwise "i)", "ii)" ... are roman numerals.
            open_alpha = [n for s, n in self.stack if s == "alpha"]
            prev = open_alpha[-1].key if open_alpha else None
            if not (prev and ord(label[0]) == ord(prev) + 1):
                style = "alpha2"
        if self.fikra is None:
            self._new_fikra()
        elif not self.stack and not self.fikra.label and not self.fikra.children:
            self._maybe_continuation(style, label)
        node = Node(level=Level.BENT, label=label, text=rest, notes=notes, footnotes=fns,
                    repealed=repealed)
        styles = [s for s, _ in self.stack]
        if style in styles:
            del self.stack[styles.index(style):]
        parent = self.stack[-1][1] if self.stack else self.fikra
        if self.stack:
            node.level = Level.ALT_BENT
        assert parent is not None
        parent.children.append(node)
        self.stack.append((style, node))

    def _maybe_continuation(self, style: str, label: str) -> None:
        if self.prev is None or self.article is None:
            return
        prev_fikra, prev_stack = self.prev
        for i, (s, item) in enumerate(prev_stack):
            if s == style and _follows(item.key, label_key(label)):
                para = self.fikra
                assert para is not None
                del self.article.children[-1]  # the fıkra opened for ``para``
                item.children.append(Node(level=Level.PARAGRAF, text=para.text,
                                          notes=para.notes, footnotes=para.footnotes,
                                          repealed=para.repealed))
                self.fikra, self.stack = prev_fikra, prev_stack[: i + 1]
                self.prev = None
                return

    def table(self, rows: list[list[str]], fns: list[int]) -> None:
        if self.article is None:
            return
        node = Node(level=Level.TABLO, text="\n".join(" | ".join(r) for r in rows),
                    footnotes=fns)
        parent = self.stack[-1][1] if self.stack else (self.fikra or self.article)
        parent.children.append(node)


def _follows(prev: str, key: str) -> bool:
    """Is ``key`` the label right after ``prev`` ("3" -> "4", "b" -> "c")?"""
    if prev.isdigit() and key.isdigit():
        return int(key) == int(prev) + 1
    return len(prev) == len(key) == 1 and ord(key) == ord(prev) + 1


def _next_nonblank(bs: list[Block], i: int) -> int | None:
    for j in range(i + 1, len(bs)):
        if not bs[j].blank:
            return j
    return None


def _is_title(bs: list[Block], i: int) -> bool:
    """Is ``bs[i]`` the title (madde başlığı) of the article that follows it?

    Titles usually end with ":"; some do not ("Basit usule tabi olmanın özel şartları"),
    but they always stand right after a blank line or a heading.
    """
    b = bs[i]
    j = _next_nonblank(bs, i)
    nxt = bs[j] if j is not None else None
    if b.table is not None or nxt is None or nxt.table is not None:
        return False
    if not ARTICLE_RE.match(nxt.text) or ARTICLE_RE.match(b.text):
        return False
    if b.text.endswith(":") or "MaddeBasl" in b.html_class:
        return True
    prev = bs[i - 1] if i > 0 else None
    return (prev is None or prev.blank) and len(b.text) < 200 \
        and not LEADING_MARKER_RE.match(b.text) and not ITEM_RE.match(b.text)


def _is_unnumbered_heading(bs: list[Block], i: int) -> bool:
    """A short line set apart by blank lines and followed by an article ("Son Hükümler")."""
    blk = bs[i]
    if i == 0 or i + 1 >= len(bs) or not (bs[i - 1].blank and bs[i + 1].blank):
        return False
    t = blk.text
    if len(t) > 60 or t.endswith((":", ".", ";", ",")) or ARTICLE_RE.match(t):
        return False
    if LEADING_MARKER_RE.match(t) or ITEM_RE.match(t):
        return False
    j = _next_nonblank(bs, i)
    return j is not None and bs[j].table is None and (
        ARTICLE_RE.match(bs[j].text) is not None or _is_title(bs, j)
    )


def build_tree(html: str, number: int) -> Law:
    header = mg.parse_header(html)
    law = Law(number=number, name=header.title)
    b = _Builder(law)
    bs = blocks(html)
    pending_title: Block | None = None
    i = 0
    while i < len(bs):
        blk = bs[i]
        i += 1
        if blk.table is not None:
            b.table(blk.table, blk.footnotes)
            continue
        if blk.blank:
            continue
        text = blk.text
        if m := HEADING_RE.match(text):
            j = _next_nonblank(bs, i - 1)
            title = None
            if j is not None and bs[j].table is None and not ARTICLE_RE.match(bs[j].text) \
                    and not HEADING_RE.match(bs[j].text) and not _is_title(bs, j):
                title = bs[j].text
                i = j + 1
            lvl = Level.KISIM if m.group("kind") == "KISIM" else Level.BOLUM
            b.heading(lvl, text, title).footnotes = blk.footnotes
            continue
        if _is_unnumbered_heading(bs, i - 1):
            b.heading(Level.BOLUM, "", text).footnotes = blk.footnotes
            continue
        if _is_title(bs, i - 1):
            pending_title = blk
            continue
        if b.article is None and not ARTICLE_RE.match(text):
            continue  # law title and header block
        if m := ARTICLE_RE.match(text):
            notes, rest = split_markers(text[m.end():])
            title = pending_title.text if pending_title else None
            fns = (pending_title.footnotes if pending_title else []) + blk.footnotes
            pending_title = None
            art_id = article_id(m.group("prefix"), m.group("num"))
            b.open_article(m.group("label"), art_id, title, notes, fns)
            if rest:
                b.paragraph(rest, [])
            continue
        if pending_title is not None:
            # A ":"-ending paragraph not followed by an article after all.
            b.paragraph(pending_title.text, pending_title.footnotes)
            pending_title = None
        b.paragraph(text, blk.footnotes)
    return law
