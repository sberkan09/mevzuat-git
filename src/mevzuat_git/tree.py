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
ARTICLE_RE = mg.ARTICLE_RE
# A leading editorial marker: "(Değişik: 7/1/2003-4783/1 md.)", "(Mülga: ...; Yeniden
# düzenleme: ...)", "(İptal: Anayasa Mahkemesinin ... sayılı Kararı ile.)".
LEADING_MARKER_RE = re.compile(r"^" + mg.MARKER_RE.pattern + r"\s*")
# Item labels. A number must not run on into digits ("18.000 TL" is not bent 18).
ITEM_RE = re.compile(
    r"^(?P<label>\(\d+\)|\d+\s*[.)](?!\d)|\d+\s*-(?!\d)|[a-zçğıöşü]{1,4}\s*\)"
    r"|[A-ZÇĞİÖŞÜ]\s*\)|\([a-zçğıöşü]{1,3}\))\s*"
)
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"


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
    for br in tree.css("br"):
        br.replace_with(" ")  # lexbor would glue the words on both sides together
    for node in tree.body.traverse():
        if node.tag not in ("p", "table"):
            continue
        if mg._is_footnote_area(node) or mg._inside(node, "table"):
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


def _lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _is_repeal(notes: list[str], whole: bool = True) -> bool:
    """Does the last marker repeal (or annul) the node it stands on?

    "(Mülga: ...; Yeniden düzenleme: ...)" is in force again. With ``whole``, a marker
    that names a part ("Mülga birinci fıkra: ...") does not count.
    """
    if not notes:
        return False
    events = [e for e in _lower(notes[-1]).strip("()").split(";") if e.strip()]
    if not events:
        return False
    label = events[-1].split(":", 1)[0].strip()
    if not any(w in label for w in ("mülga", "iptal")):
        return False
    return not whole or label in ("mülga", "iptal")


def item_style(label: str) -> str:
    k = re.sub(r"[\s().\-]", "", label)
    if label.startswith("(") and k.isdigit():
        return "fikra"
    if k.isdigit():
        return "num" + ("." if "." in label else ")" if ")" in label else "-")
    if label.startswith("("):
        return "(alpha)"
    return "alpha" if len(k) == 1 else "alpha2"


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
        self.last_alpha: str | None = None  # last letter label in the article

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
        self.prev, self.last_alpha = None, None
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
        repealed = _is_repeal(notes, whole=False) and not rest
        if not label:
            if self.numbered and self.fikra is not None:
                node = Node(level=Level.PARAGRAF, text=rest, notes=notes, footnotes=fns,
                            repealed=repealed)
                self.fikra.children.append(node)
                return
            if self.prev is None and self.fikra is not None and self.stack:
                self.prev = (self.fikra, list(self.stack))
            f = self._new_fikra()
            f.text, f.notes, f.footnotes, f.repealed = rest, notes, fns, repealed
            return
        # "6. a) Dağıtılsın ...", "b) i) Tam mükellef ...": an item that opens with its
        # first sub-item. The outer item gets no text; the rest is parsed again below it.
        nested = (m2 := ITEM_RE.match(rest)) is not None and not re.match(
            r"[,;]|ve\b|ile\b|alt\s+bend|bend|numaralı", rest[m2.end():])
        own_text, own_fns = ("", []) if nested else (rest, fns)
        style = item_style(label)
        if style == "fikra":
            self.numbered, self.prev = True, None
            f = self._new_fikra(label)
            f.text, f.notes, f.footnotes, f.repealed = own_text, notes, own_fns, repealed
        else:
            self._item(label, style, own_text, notes, own_fns, repealed and not nested)
        if nested:
            self.paragraph(rest, fns)

    def _item(self, label: str, style: str, text: str, notes: list[str], fns: list[int],
              repealed: bool) -> None:
        key = label_key(label)
        # "i)" after "h)" or "ı)" is a letter; otherwise "i)", "ii)" ... are roman.
        if style == "alpha" and key in ROMAN and not (
            self.last_alpha and _follows(self.last_alpha, key)
        ):
            style = "alpha2"
        if style.startswith("num"):
            # "8." then "9)": the same list with a typo in the punctuation.
            for s, n in self.stack:
                if s.startswith("num") and s != style and _follows(n.key, key):
                    style = s
                    break
        if style == "alpha":
            self.last_alpha = key
        if self.fikra is None:
            self._new_fikra()
        elif not self.stack and not self.fikra.label and not self.fikra.children:
            self._maybe_continuation(style, label)
        elif self.prev is not None and style not in [s for s, _ in self.stack]:
            # "- Ticari kazancı ..." opened its own list ("1.", "2."): a later "b)" may
            # still continue the "a)" before it.
            self._maybe_continuation(style, label)
        node = Node(level=Level.BENT, label=label, text=text, notes=notes, footnotes=fns,
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
                # Every fıkra opened since then was a paragraph of ``item``.
                kids = self.article.children
                start = next(j for j, f in enumerate(kids) if f is prev_fikra) + 1
                for para in kids[start:]:
                    para.level = Level.PARAGRAF
                    item.children.append(para)
                del kids[start:]
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
    """Is ``key`` the label right after ``prev``? "3" -> "4"; letters in Turkish order,
    where ç, ğ, ı, ö, ş, ü may be skipped ("h" -> "ı" or "i")."""
    if prev.isdigit() and key.isdigit():
        return int(key) == int(prev) + 1
    if len(prev) != 1 or len(key) != 1:
        return False
    a, b = TR_ALPHABET.find(prev), TR_ALPHABET.find(key)
    if a < 0 or b <= a:
        return False
    return all(c in "çğıöşü" for c in TR_ALPHABET[a + 1:b])


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
    """A short line set apart by blank lines and followed by a titled article
    ("Son Hükümler", then "Kaldırılan hükümler:", then "Madde 124 –")."""
    blk = bs[i]
    if i == 0 or i + 1 >= len(bs) or not (bs[i - 1].blank and bs[i + 1].blank):
        return False
    t = blk.text
    if len(t) > 60 or t.endswith((":", ".", ";", ",")) or ARTICLE_RE.match(t):
        return False
    if LEADING_MARKER_RE.match(t) or ITEM_RE.match(t):
        return False
    j = _next_nonblank(bs, i)
    # Directly before an article it would be that article's title instead.
    return j is not None and bs[j].table is None and _is_title(bs, j)


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
            art_id = mg.article_id(m.group("prefix"), m.group("num"))
            b.open_article(mg.squash(m.group("label")), art_id, title, notes, fns)
            if rest:
                b.paragraph(rest, [])
            continue
        b.paragraph(text, blk.footnotes)
    for a in law.articles():
        # "Madde 20 – (Mülga: ...)" followed by fıkras in force is not repealed.
        if a.repealed and any(n.text for n in a.walk()):
            a.repealed = False
    return law
