"""Faz 3: apply amendment operations to a law tree, and undo them.

``apply`` is the replay engine: it changes a :class:`~mevzuat_git.model.Law` in place
the way an amending act changed the law. ``unapply`` is its inverse, used to rebuild the
text as it stood before the first amendment we have the RG text of (see verify.py).

Text is changed only by the operations themselves; new text is inserted verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

from mevzuat_git.compare import node_lines, norm
from mevzuat_git.model import AmendmentOp, Law, Level, Node, OpType, Path, label_key
from mevzuat_git.tree import TR_ALPHABET

UNKNOWN = "\x00?"  # text of a node whose earlier content cannot be recovered


class ReplayError(Exception):
    pass


class Superseded(Exception):
    """The target lies inside text that a later operation replaced wholesale."""


# -- locating --------------------------------------------------------------------------

@dataclass
class Located:
    node: Node
    siblings: list[Node]  # the list that holds ``node``
    article: Node | None
    sentence: int | None = None  # 0-based; -1 = last


def _containers(law: Law) -> list[list[Node]]:
    out = [law.body]
    for top in law.body:
        for n in top.walk():
            out.append(n.children)
    return out


def siblings_of(law: Law, node: Node) -> list[Node]:
    for lst in _containers(law):
        if any(x is node for x in lst):
            return lst
    raise ReplayError("node not in tree")


def _index(lst: list[Node], node: Node) -> int:
    return next(i for i, x in enumerate(lst) if x is node)


def _ord_pick(items: list[Node], n: int, what: str) -> Node:
    if n == -1:
        if not items:
            raise ReplayError(f"no {what}")
        return items[-1]
    if not 1 <= n <= len(items):
        raise ReplayError(f"{what} {n} not found ({len(items)} present)")
    return items[n - 1]


def _check_known(n: Node) -> None:
    if n.text == UNKNOWN:
        raise Superseded()


def locate(law: Law, path: Path, whole: bool = False, live: bool = True) -> Located:
    """The node at ``path``. Raises :class:`Superseded` when the path runs through text
    a later operation replaced (see ``UNKNOWN``); with ``whole``, the node itself may be
    such a placeholder, since the operation replaces or repeals all of it.

    With ``live``, an ordinal that lands on a repealed fıkra counts the fıkras in force
    instead: 4684/17 calls the fıkra 3946 added to md. 38 its "üçüncü fıkrası", after the
    "(Mülga üçüncü fıkra: 4/12/1985-3239/138 md.)" one. Undoing a repeal passes ``False``."""
    if not path.madde:
        raise ReplayError("law-level path has no node")
    art = law.article(path.madde)
    if art is None:
        raise ReplayError(f"article {path.madde} not found")
    node = art
    chain = [art]
    if art.text == UNKNOWN and not art.children and path.fikra is not None:
        # The whole article is a placeholder (a repeal undone, 5479 on md. 19): its
        # fıkras then are not known.
        raise Superseded()
    if path.fikra is not None:
        fikras = [c for c in art.children if c.level is Level.FIKRA]
        by_label = [f for f in fikras if f.key == str(path.fikra)]
        node = by_label[0] if by_label and path.fikra > 0 else _ord_pick(fikras, path.fikra,
                                                                           "fıkra")
        if live and node.repealed and not by_label and path.fikra > 0:
            alive = [f for f in fikras if not f.repealed]
            if path.fikra <= len(alive):
                node = alive[path.fikra - 1]
        chain.append(node)
    if path.bent is not None:
        cands = [d for d in node.walk() if d.level is Level.BENT and d.key == path.bent]
        if not cands:
            cands = [d for d in node.walk() if d.level is Level.ALT_BENT
                     and d.key == path.bent]
        if not cands and path.fikra in (None, 1):
            # An article that is only a numbered list ("1. ...", "2. ...") reads as fıkras
            # (GVK md. 22, 6728/11 "(1) numaralı fıkrası"), but acts may call the items
            # bents: VUK md. 353, "353 üncü maddesinin birinci fıkrasının (1) numaralı
            # bendi" (7338/40).
            cands = [f for f in art.children if f.level is Level.FIKRA and f.key == path.bent
                     and re.fullmatch(r"\d+\.", (f.label or "").strip())]
        if not cands:
            if any(d.text == UNKNOWN for d in node.walk()):
                raise Superseded()
            raise ReplayError(f"bent {path.bent} not found in {path}")
        node = cands[0]
        chain.append(node)
    if path.alt_bent is not None:
        cands = [d for d in node.walk() if d.level is Level.ALT_BENT
                 and d.key == path.alt_bent and d is not node]
        if not cands and path.alt_bent.isdigit():
            kids = [c for c in node.children if c.level is Level.ALT_BENT]
            cands = [_ord_pick(kids, int(path.alt_bent), "alt bent")]
        if not cands:
            raise ReplayError(f"alt bent {path.alt_bent} not found in {path}")
        node = cands[0]
        chain.append(node)
    if (path.cumle is not None and node is art and not art.text
            and [c.level for c in art.children] == [Level.FIKRA]):
        # "256 ncı maddesinin son cümlesine" (7104/20): the sentence is in the article's
        # one fıkra.
        node = art.children[0]
        chain.append(node)
    if path.paragraf is not None and path.paragraf != 1:
        paras = [c for c in node.children if c.level is Level.PARAGRAF]
        if path.paragraf == -1:
            node = paras[-1] if paras else node
        else:
            node = _ord_pick(paras, path.paragraf - 1, "paragraf")
        chain.append(node)
    sentence = None
    for n in chain[:-1] if whole and path.cumle is None else chain:
        _check_known(n)
    if path.cumle is not None:
        sentence = path.cumle - 1 if path.cumle > 0 else -1
    sibs = siblings_of(law, node)
    return Located(node=node, siblings=sibs, article=art, sentence=sentence)


# -- text helpers ----------------------------------------------------------------------

_SENT_END = re.compile(r"(?<=[.])\s+(?=[A-ZÇĞİÖŞÜ0-9(“\"])")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [s for s in spans if s[1] > s[0]]


def _span(text: str, sentence: int | None) -> tuple[int, int]:
    if sentence is None:
        return 0, len(text)
    spans = sentence_spans(text)
    if not spans:
        raise ReplayError("no sentence in the text")
    if sentence == -1:
        return spans[-1]
    if sentence >= len(spans):
        raise ReplayError(f"sentence {sentence + 1} not found ({len(spans)} present)")
    return spans[sentence]


_FLEX = {'"': "[\"“”]", "“": "[\"“”]", "”": "[\"“”]", "'": "['’‘]", "’": "['’‘]",
         "‘": "['’‘]", "–": r"\s*[–—-]\s*", "—": r"\s*[–—-]\s*", "-": r"\s*[–—-]\s*",
         # "%15’ini" in 7061/14, "% 15'ini" on mevzuat.gov.tr.
         "%": r"%\s*",
         # "Meslekî Eğitim Kanununa tâbi" in 5228/59, "Mesleki ... tabi" in the text.
         "â": "[âa]", "a": "[âa]", "î": "[îi]", "i": "[îi]", "û": "[ûu]", "u": "[ûu]",
         "Â": "[ÂA]", "A": "[ÂA]", "Î": "[Îİ]", "İ": "[Îİ]", "Û": "[ÛU]", "U": "[ÛU]"}


def _phrase_re(phrase: str) -> re.Pattern:
    """The pattern of an ibare in the text, whatever its typography. Spacing around a
    dash between numbers varies: "1.1.1999 - 31.12.2004" in 5035/48,
    "1.1.1999-31.12.2005" on mevzuat.gov.tr. A quoted ibare may start with a space
    ("“ 3308 sayılı ...”", 5228/59)."""
    phrase = re.sub(r"(?<=\d)\s*([–—-])\s*(?=\d)", r"\1", phrase.strip())
    parts = []
    for i, ch in enumerate(phrase):
        if ch in "–—-" and i in (0, len(phrase) - 1):
            parts.append("[–—-]")  # the spaces around it are not part of the ibare
            continue
        if ch.isspace():
            if not parts or parts[-1] != r"\s+":
                parts.append(r"\s+")
        else:
            parts.append(_FLEX.get(ch, re.escape(ch)))
    return re.compile("".join(parts))


def find_all(text: str, phrase: str, lo: int = 0, hi: int | None = None) -> list[tuple[int, int]]:
    hi = len(text) if hi is None else hi
    if not phrase:
        return []
    return [(m.start(), m.end()) for m in _phrase_re(phrase).finditer(text, lo, hi)]


def _join_insert(text: str, pos: int, new: str) -> str:
    """Insert ``new`` at ``pos`` with the spacing the sentence needs."""
    before, after = text[:pos], text[pos:]
    if new[:1] not in ",.;:)" and before and not before.endswith((" ", "(", "“", '"')):
        new = " " + new
    if after and not after.startswith((" ", ",", ".", ";", ":", ")")) \
            and not new.endswith((" ", "(")):
        new = new + " "
    return before + new + after


def _remove_span(text: str, s: int, e: int) -> str:
    """``text`` without ``text[s:e]``; spacing is tidied only where the cut was made."""
    left, right = text[:s], text[e:]
    if not left.strip():
        return left + right.lstrip(" ")
    if right[:1] in (",", ".", ";", ":", ")") or not right.strip():
        return left.rstrip(" ") + right
    if left.endswith(" ") and right.startswith(" "):
        right = right.lstrip(" ")
    return left + right


# -- scope of phrase operations -------------------------------------------------------

@dataclass
class TextSlot:
    """Where a phrase operation may act: a node's text (or title), maybe one sentence."""

    node: Node
    attr: str  # "text" or "title"
    lo: int
    hi: int

    def get(self) -> str:
        return getattr(self.node, self.attr) or ""

    def set(self, value: str) -> None:
        setattr(self.node, self.attr, value)


def phrase_slots(law: Law, path: Path) -> list[TextSlot]:
    if path.baslik:
        art = law.article(path.madde)
        if art is None:
            raise ReplayError(f"article {path.madde} not found")
        return [TextSlot(art, "title", 0, len(art.title or ""))]
    loc = locate(law, path)
    if loc.sentence is not None:
        lo, hi = _span(loc.node.text, loc.sentence)
        return [TextSlot(loc.node, "text", lo, hi)]
    slots = []
    for n in loc.node.walk():
        if n.text == UNKNOWN:
            raise Superseded()
        slots.append(TextSlot(n, "text", 0, len(n.text)))
    if loc.node.level is Level.MADDE and loc.node.title:
        slots.insert(0, TextSlot(loc.node, "title", 0, len(loc.node.title)))
    return slots


def _occurrences(slots: list[TextSlot], phrase: str) -> list[tuple[TextSlot, int, int]]:
    return [(sl, s, e) for sl in slots for s, e in find_all(sl.get(), phrase, sl.lo, sl.hi)]


def _replace_in_slots(slots: list[TextSlot], old: str, new: str, every: bool) -> int:
    occ = _occurrences(slots, old)
    if not occ:
        return 0
    if not every:
        occ = occ[:1]
    # Replace right to left inside each slot so earlier offsets stay valid.
    for sl, s, e in sorted(occ, key=lambda x: -x[1]):
        t = sl.get()
        sl.set(t[:s] + _spaced(t, s, e, new) + t[e:])
    return len(occ)


def _spaced(text: str, s: int, e: int, new: str) -> str:
    """``new`` as it replaces ``text[s:e]``, with a space where it would run into a word:
    “, 86 ve mükerrer 121 inci maddelerinde” → “ve 86 ncı maddeleri ...” turns
    "82, 86 ve" into "82 ve 86", not "82ve 86" (6663/3 on mükerrer 123)."""
    # Only where the matched ibare began or ended with a separator: an ibare often ends
    # inside a word ("Bakanlar Kurulu" in "Bakanlar Kurulunca").
    if new[:1].isalnum() and s and text[s - 1].isalnum() and not text[s].isalnum():
        new = " " + new
    if new[-1:].isalnum() and e < len(text) and text[e].isalnum() \
            and not text[e - 1].isalnum():
        new = new + " "
    return new


def _replace_many(slots: list[TextSlot], pairs: list[tuple[str, str, bool]]) -> list[int]:
    """Replace several ibareler in one pass ("sırasıyla"): no replacement is looked for
    inside the text another one wrote, and a longer ibare wins over its prefix. Returns
    how many times each pair was replaced."""
    order = sorted(range(len(pairs)), key=lambda i: -len(pairs[i][0]))
    rx = re.compile("|".join(f"(?P<g{i}>{_phrase_re(pairs[i][0]).pattern})" for i in order))
    done = [0] * len(pairs)
    for sl in slots:
        t, out, pos = sl.get(), [], sl.lo
        for m in rx.finditer(t, sl.lo, sl.hi):
            i = int(m.lastgroup[1:])
            if done[i] and not pairs[i][2]:
                continue
            done[i] += 1
            out += [t[pos:m.start()], pairs[i][1]]
            pos = m.end()
        if out:
            sl.set(t[:sl.lo] + "".join(out) + t[pos:])
    return done


def apply_batch(law: Law, ops: list[AmendmentOp]) -> list[str | None]:
    """Apply ibare replacements of one sentence that act on the same text at once.
    Returns an error per operation (None when it applied); :class:`Superseded` and an
    unknown target are raised."""
    if len(ops) == 1:
        try:
            apply(law, ops[0])
        except Superseded:
            raise
        except ReplayError as exc:
            return [str(exc)]
        return [None]
    if not all(o.old for o in ops):
        raise ReplayError(f"empty ibare in a batch on {ops[0].target}")
    ops = [rebase(law, o) for o in ops]
    done = _replace_many(phrase_slots(law, ops[0].target),
                         [(o.old or "", o.new or "", o.all) for o in ops])
    return [None if n else f"ibare not found: {o.old!r} in {o.target}"
            for o, n in zip(ops, done, strict=True)]


def unapply_batch(law: Law, ops: list[AmendmentOp]) -> list[Check]:
    """Undo a batch of :func:`apply_batch`; one check per operation."""
    if len(ops) == 1:
        return [unapply(law, ops[0])]
    try:
        ops = [rebase(law, o) for o in ops]
        slots = phrase_slots(law, ops[0].target)
    except Superseded:
        return [Check("superseded") for _ in ops]
    except ReplayError as exc:
        return [Check("fail", str(exc)) for _ in ops]
    checks = [Check("lossy", "replacement with an empty ibare") if not o.new else
              Check("ok") if _occurrences(slots, o.new) else
              Check("fail", f"new ibare not in text: {o.new!r}") for o in ops]
    live = [o for o, c in zip(ops, checks, strict=True) if c.status == "ok"]
    if live:
        _replace_many(slots, [(o.new or "", o.old or "", o.all) for o in live])
    return checks


# -- node helpers ---------------------------------------------------------------------

def _style(label: str) -> str:
    k = label_key(label)
    if k.isdigit():
        return "num" + re.sub(r"[\d\s]", "", label)
    return "alpha" + re.sub(r"[a-zçğıöşü\s]", "", label)


def _bump(label: str, delta: int, alphabet: str = TR_ALPHABET) -> str:
    def num(m: re.Match) -> str:
        return str(int(m.group(0)) + delta)

    if re.search(r"\d+", label):
        return re.sub(r"\d+", num, label, count=1)

    def letter(m: re.Match) -> str:
        i = alphabet.find(m.group(0))
        if i < 0 or not 0 <= i + delta < len(alphabet):
            raise ReplayError(f"cannot renumber {label!r}")
        return alphabet[i + delta]

    # "aa)" -> "bb)": every letter of a doubled label moves.
    key = label_key(label)
    whole = len(key) > 1 and len(set(key)) == 1
    return re.sub(r"[a-zçğıöşü]", letter, label, count=0 if whole else 1)


def _alphabet(siblings: list[Node]) -> str:
    """Letter labels run in Turkish order: a) b) c) ç) d) ... Some laws skip ç, ğ, ı, ö,
    ş and ü; if the siblings go from c) straight to d), so does the renumbering."""
    keys = [k[0] for n in siblings if n.label and (k := label_key(n.label)).isalpha()]
    for x, y in pairwise(keys):
        i, j = TR_ALPHABET.find(x), TR_ALPHABET.find(y)
        if 0 <= i < j and j - i > 1 and all(c in "çğıöşü" for c in TR_ALPHABET[i + 1:j]):
            return "".join(c for c in TR_ALPHABET if c not in "çğıöşü")
    return TR_ALPHABET


def _renumber(siblings: list[Node], after: int, inserted: list[Node], delta: int) -> None:
    if not inserted or not inserted[0].label:
        return
    style = _style(inserted[0].label)
    alphabet = _alphabet(siblings)
    for n in siblings[after:]:
        if n.label and _style(n.label) == style and n.level is inserted[0].level:
            n.label = _bump(n.label, delta, alphabet)


def _blank(n: Node) -> None:
    n.text = UNKNOWN
    n.children = []
    n.notes = []


def _article_key(art_id: str) -> tuple[int, str]:
    """Sort key within one kind of article: "gecici-80" -> (80, ""), "20/A" -> (20, "A")."""
    m = re.search(r"(\d+)(?:/(\w+))?$", art_id)
    return (int(m.group(1)), m.group(2) or "") if m else (0, art_id)


def _law_insert_articles(law: Law, nodes: list[Node]) -> None:
    """Add new articles among those of the same kind, in number order: geçici 81 goes
    after geçici 80 even when it is inserted first (6322 adds both; they take effect on
    different dates and the history commits 81 first)."""
    for new in nodes:
        prefix = (new.id or "").split("-")[0] if "-" in (new.id or "") else ""
        arts = list(law.articles())
        same = [a for a in arts if (a.id or "").startswith(prefix + "-")] if prefix else []
        before = [a for a in same if _article_key(a.id or "") < _article_key(new.id or "")]
        if same and not before:
            sibs = siblings_of(law, same[0])
            sibs.insert(_index(sibs, same[0]), new)
            continue
        anchor = before[-1] if before else (arts[-1] if arts else None)
        if anchor is None:
            law.body.append(new)
            continue
        sibs = siblings_of(law, anchor)
        sibs.insert(_index(sibs, anchor) + 1, new)


def _past_family(siblings: list[Node], i: int, new_id: str) -> int:
    """7338 md. 1-3 add mükerrer 20/A, 20/B and 20/C, each "mükerrer 20 nci maddesinden
    sonra gelmek üzere": a new article goes after the ones of its family before it. So
    do ek 14 to ek 18, each "ek 13 üncü maddesinden sonra" (7338/46-50)."""
    family = new_id.split("/")[0]
    kind = new_id.split("-")[0] if "-" in new_id else None

    def before(sib_id: str) -> bool:
        if sib_id.split("/")[0] == family and "/" in sib_id:
            return sib_id < new_id
        return bool(kind) and sib_id.startswith(kind + "-") and "/" not in new_id \
            and _article_key(sib_id) < _article_key(new_id)

    while i < len(siblings) and siblings[i].level is Level.MADDE and siblings[i].id \
            and before(siblings[i].id):
        i += 1
    return i


# -- apply -----------------------------------------------------------------------------

def _is_sentence_op(op: AmendmentOp) -> bool:
    return op.target.cumle is not None or bool(
        re.search(r"aşağıdaki\s+cümle", op.source_sentence))


_REBASED = ("fikra", "bent", "alt_bent", "paragraf")


def rebase(law: Law, op: AmendmentOp) -> AmendmentOp:
    """``op`` with its target where the footnote's node is in ``law`` now. A footnote op's
    address was read on today's text: "bu fıkrada" is the 9th fıkra today, but was the 8th
    before a later act added one. The parts of the target that came from the footnote's
    node are taken from that node's present position."""
    if op.footnote is None or op.footnote_path is None:
        return op
    here = _footnote_path(law, op.footnote)
    if here is None:
        raise Superseded()  # the node carrying the footnote was replaced later
    # ``footnote_path`` keeps only the parts the target took from the footnote's node.
    then, t = op.footnote_path, op.target
    update = {f: getattr(here, f) for f in _REBASED if getattr(then, f) is not None}
    return op.model_copy(update={"target": t.model_copy(update=update)})


def resolve(law: Law, op: AmendmentOp) -> AmendmentOp:
    """``op`` rebased (see :func:`rebase`) on ``law`` with its footnote anchor dropped, for
    a replay that rebuilds nodes from the acts' texts, which carry no footnote numbers.
    Unchanged if the footnote's node is gone (the undo then reports it superseded)."""
    try:
        return rebase(law, op).model_copy(update={"footnote": None, "footnote_path": None})
    except Superseded:
        return op


def _footnote_path(law: Law, n: int) -> Path | None:
    from mevzuat_git.amendments import footnote_paths  # amendments imports tree, not replay
    return footnote_paths(law).get(n)


def apply(law: Law, op: AmendmentOp) -> None:
    """Apply one operation in place. Raises :class:`ReplayError` if it does not fit."""
    op = rebase(law, op)
    t = op.target
    if op.op is OpType.REPLACE_PHRASE and op.paren:
        sl, s, e = _paren_group(phrase_slots(law, t))
        sl.set(sl.get()[:s] + (op.new or "") + sl.get()[e:])
        return
    if op.op is OpType.REPLACE_PHRASE:
        if not _replace_in_slots(phrase_slots(law, t), op.old or "", op.new or "", op.all):
            raise ReplayError(f"ibare not found: {op.old!r} in {t}")
        return
    if op.op is OpType.DELETE_PHRASE:
        slots = phrase_slots(law, t)
        occ = _occurrences(slots, op.old or "")
        if not occ:
            raise ReplayError(f"ibare not found: {op.old!r} in {t}")
        for sl, s, e in sorted(occ if op.all else occ[:1], key=lambda x: -x[1]):
            sl.set(_remove_span(sl.get(), s, e))
        return
    if op.op is OpType.INSERT_PHRASE:
        slots = phrase_slots(law, t)
        new = op.new or ""
        if op.position in ("after", "before"):
            occ = _occurrences(slots, op.anchor or "")
            if not occ:
                raise ReplayError(f"anchor not found: {op.anchor!r} in {t}")
            for sl, s, e in sorted(occ if op.all else occ[:1], key=lambda x: -x[1]):
                pos = e if op.position == "after" else s
                sl.set(_join_insert(sl.get(), pos, new))
            return
        sl = slots[0] if op.position == "start" else _last_text_slot(slots)
        pos = sl.lo if op.position == "start" else sl.hi
        sl.set(_join_insert(sl.get(), pos, new))
        return
    if op.op is OpType.REPEAL_NODE:
        if t.baslik:
            raise ReplayError("repeal of a title")
        loc = locate(law, t, whole=True)
        if loc.sentence is not None:
            s, e = _span(loc.node.text, loc.sentence)
            loc.node.text = _remove_span(loc.node.text, s, e)
            return
        loc.node.repealed = True
        loc.node.text = ""
        loc.node.children = []
        return
    if op.op is OpType.RELABEL_NODE:
        _relabel(law, t, op.old or "", op.new or "")
        return
    if op.op is OpType.REPLACE_NODE:
        _apply_replace(law, op)
        return
    if op.op is OpType.INSERT_NODE:
        _apply_insert(law, op)
        return
    raise ReplayError(f"unsupported op {op.op}")


def _paren_group(slots: list[TextSlot]) -> tuple[TextSlot, int, int]:
    """The first top-level "( ... )" of the target, ignoring short ones like "(a)"."""
    for sl in slots:
        text, depth, start = sl.get(), 0, -1
        for i in range(sl.lo, sl.hi):
            if text[i] == "(":
                if depth == 0:
                    start = i
                depth += 1
            elif text[i] == ")" and depth:
                depth -= 1
                if depth == 0 and i - start > 20:
                    return sl, start, i + 1
    raise ReplayError("no parenthetical in target")


def _last_text_slot(slots: list[TextSlot]) -> TextSlot:
    texts = [s for s in slots if s.attr == "text"]
    if not texts:
        raise ReplayError("no text to append to")
    return texts[0]  # the target's own text, not its sub-nodes


def _live(op: AmendmentOp) -> bool:
    """Whether an ordinal fıkra in ``op`` counts the fıkras in force (see ``locate``); not
    when the act names a repealed one: "mülga ikinci fıkrasından sonra gelmek üzere"."""
    return not re.search(r"\bmülga\b|kaldırılan", op.source_sentence)


def _keep_label(old: Node, new: list[Node]) -> list[Node]:
    """``new`` as it replaces ``old``. A bent's new text given without its number keeps
    the number: "(10) numaralı bendi ile 5520 sayılı Kanunun ... (e) bendi aşağıdaki
    şekilde değiştirilmiştir. “Başbakanlıkça ...”" (6552/92). So does a fıkra: "(4) numaralı
    fıkrası "Bankalar arası mevduat ..." şeklinde değiştirilmiştir" (5436/14)."""
    if (len(new) == 1 and not new[0].label and old.label and not new[0].children
            and old.level in (Level.FIKRA, Level.BENT, Level.ALT_BENT)):
        return [new[0].model_copy(update={"level": old.level, "label": old.label})]
    return new


def _apply_replace(law: Law, op: AmendmentOp) -> None:
    t = op.target
    if t.baslik:
        art = law.article(t.madde)
        if art is None:
            raise ReplayError(f"article {t.madde} not found")
        art.title = op.new
        return
    loc = locate(law, t, whole=True, live=_live(op))
    if op.kind is Level.PARAGRAF or loc.sentence is not None:
        new = op.new or ""
        if loc.sentence is not None:
            s, e = _span(loc.node.text, loc.sentence)
            loc.node.text = loc.node.text[:s] + new + loc.node.text[e:]
        else:
            loc.node.text = new
        return
    if not op.new_nodes:
        raise ReplayError("replace without new nodes")
    i = _index(loc.siblings, loc.node)
    new_nodes = _keep_label(loc.node, [n.model_copy(deep=True) for n in op.new_nodes])
    if loc.node.level is Level.MADDE:
        new = new_nodes[0]
        new.id = loc.node.id
        if new.title is None or (not op.with_title and loc.node.title):
            new.title = loc.node.title if not op.with_title else new.title
        new.repealed = False
        loc.siblings[i] = new
        return
    loc.siblings[i:i + 1] = new_nodes


def _at_anchor(loc: Located, anchor: str | None) -> Located:
    """With a quoted anchor ("“– Tam ve dar ...” paragrafından sonra"), the node inside
    ``loc`` whose text holds it; the insertion goes next to that node."""
    if not anchor:
        return loc
    stack: list[tuple[Node, list[Node]]] = [(loc.node, loc.siblings)]
    while stack:
        node, sibs = stack.pop(0)
        if find_all(node.text, anchor):
            return Located(node=node, siblings=sibs, article=loc.article)
        stack.extend((c, node.children) for c in node.children)
    raise ReplayError(f"anchor not found: {anchor[:80]!r}")


def _apply_insert(law: Law, op: AmendmentOp) -> None:
    t = op.target
    new_nodes = [n.model_copy(deep=True) for n in op.new_nodes]
    if op.kind is Level.MADDE and (not t.madde or op.position == "end"):
        for n in new_nodes:
            if law.article(n.id or "") is not None:
                raise ReplayError(f"article {n.id} already exists")
        _law_insert_articles(law, new_nodes)
        return
    # An article goes after another wherever that one stands, whatever its text: 7338/46
    # puts ek 14 after ek 13, which 7524/15 rewrote later.
    loc = locate(law, t, whole=op.kind is Level.MADDE, live=_live(op))
    if op.kind is Level.PARAGRAF and not new_nodes:
        new = op.new or ""
        if _is_sentence_op(op):
            if loc.sentence is not None and op.position in ("after", "before"):
                s, e = _span(loc.node.text, loc.sentence)
                pos = e if op.position == "after" else s
            else:
                pos = len(loc.node.text)
            loc.node.text = _join_insert(loc.node.text, pos, new)
            return
        para = Node(level=Level.PARAGRAF, text=new)
        loc = _at_anchor(loc, op.anchor)
        if op.position in ("after", "before"):
            i = _index(loc.siblings, loc.node)
            loc.siblings.insert(i + 1 if op.position == "after" else i, para)
        else:
            loc.node.children.append(para)
        return
    if not new_nodes:
        raise ReplayError("insert without new nodes")
    if op.position in ("after", "before"):
        i = _index(loc.siblings, loc.node) + (1 if op.position == "after" else 0)
        if op.kind is Level.MADDE and op.position == "after":
            i = _past_family(loc.siblings, i, new_nodes[0].id or "")
        loc.siblings[i:i] = new_nodes
        if op.renumber:
            _renumber(loc.siblings, i + len(new_nodes), new_nodes, +len(new_nodes))
        return
    container = loc.node
    if op.kind in (Level.BENT, Level.ALT_BENT) and container.level is Level.MADDE:
        fikras = [c for c in container.children if c.level is Level.FIKRA]
        if fikras:
            container = fikras[-1]
    if op.kind is Level.BENT and container.level in (Level.BENT, Level.ALT_BENT):
        for n in new_nodes:
            n.level = Level.ALT_BENT
    h = _end_split(container, new_nodes)
    at = len(container.children)
    if new_nodes and new_nodes[0].level in (Level.BENT, Level.ALT_BENT):
        # Before the words that close the list ("Bu işleri dolayısiyle serbest meslek
        # erbabı sayılırlar." after the bents of md. 66/2, 7394/2).
        while at > 1 and container.children[at - 1].level is Level.PARAGRAF \
                and any(c.level is new_nodes[0].level for c in container.children[:at - 1]):
            at -= 1
    container.children[at:at] = new_nodes[:h]
    if h < len(new_nodes):
        sibs = siblings_of(law, container)
        i = _index(sibs, container) + 1
        sibs[i:i] = new_nodes[h:]


def _end_split(container: Node, nodes: list[Node]) -> int:
    """How many of ``nodes``, added at the end of ``container``, go into it. The rest are
    unlabelled fıkras that follow it, as the consolidated text has them: an added bent's
    closing paragraph ("Cumhurbaşkanı bu bentte yer alan oran…", 7256/16) is a fıkra of
    the article there, after the fıkra with the bents."""
    if container.level is not Level.FIKRA:
        return len(nodes)
    return next((i for i, n in enumerate(nodes) if i and n.level is Level.FIKRA), len(nodes))


# -- unapply (inverse, with a check that the operation's result is in the text) ---------

@dataclass
class Check:
    status: str  # "ok" | "fail" | "superseded" | "lossy"
    message: str = ""


def unapply(law: Law, op: AmendmentOp) -> Check:
    """Undo ``op`` on a law that already contains its effect.

    Before undoing, the effect is looked for in the text: the new ibare must be there,
    a replaced node must read like the act's new text, and so on. The result says
    whether it was found ("ok") or not ("fail"); "superseded" means a later operation
    has already replaced the text this one acted on, "lossy" that the old text cannot
    be recovered exactly (a deleted ibare whose place is not marked).
    """
    try:
        return _unapply(law, op)
    except Superseded:
        return Check("superseded")
    except ReplayError as exc:
        return Check("fail", str(exc))


def _unapply(law: Law, op: AmendmentOp) -> Check:
    op = rebase(law, op)
    t = op.target
    if op.op is OpType.REPLACE_PHRASE and op.paren:
        if not op.new:
            return Check("lossy", "deleted parenthetical")
        slots = phrase_slots(law, t)
        if not _occurrences(slots, op.new or ""):
            return Check("fail", f"new parenthetical not in text: {(op.new or '')[:120]!r}")
        return Check("lossy", "replaced parenthetical")
    if op.op is OpType.REPLACE_PHRASE:
        slots = phrase_slots(law, t)
        if not op.new:
            return Check("lossy", "replacement with an empty ibare")
        if not _occurrences(slots, op.new):
            return Check("fail", f"new ibare not in text: {op.new!r}")
        _replace_in_slots(slots, op.new, op.old or "", op.all)
        return Check("ok")
    if op.op is OpType.INSERT_PHRASE:
        slots = phrase_slots(law, t)
        occ = _occurrences(slots, op.new or "")
        if not occ:
            return Check("fail", f"inserted ibare not in text: {op.new!r}")
        if op.position in ("after", "before"):
            anchors = _occurrences(slots, op.anchor or "")
            if not anchors:
                return Check("fail", f"anchor not in text: {op.anchor!r}")
            occ = [o for o in occ if _next_to(o, anchors, op.position)]
            if not occ:
                return Check("fail", f"inserted ibare not next to its anchor: {op.new!r}")
        sl, s, e = occ[-1] if op.position == "end" else occ[0]
        sl.set(_remove_span(sl.get(), s, e))
        return Check("ok")
    if op.op is OpType.DELETE_PHRASE:
        slots = phrase_slots(law, t)
        marks = [(sl, m.start(), m.end()) for sl in slots
                 # A footnote number may stick to the mark: "bu (…)134 kazanç" (md. 106).
                 for m in re.finditer(r"\(\s*(?:…|\.\.\.)\s*\)\d*", sl.get()[sl.lo:sl.hi])]
        if len(marks) == 1:
            sl, s, e = marks[0]
            txt = sl.get()
            left, old = txt[:sl.lo + s], op.old or ""
            if old[:1] in ",.;:)":
                # "akşamına kadar (…) tam" with “, gelirin ... kadar,” put back (7338/6).
                left = left.rstrip(" ")
            sl.set(left + old + txt[sl.lo + e:])
            return Check("ok")
        return Check("lossy", "deleted ibare: its place in the text is not marked")
    if op.op is OpType.REPEAL_NODE:
        loc = locate(law, t, live=False)
        if loc.sentence is not None:
            return Check("lossy", "repealed sentence")
        n = loc.node
        if not (n.repealed or (not n.text and not n.children)):
            return Check("fail", f"{t} is not repealed in the consolidated text")
        _blank(n)
        n.repealed = False
        return Check("ok")
    if op.op is OpType.RELABEL_NODE:
        try:
            _relabel(law, _numbered(t, op.new or ""), op.new or "", op.old or "")
        except ReplayError as exc:
            return Check("fail", str(exc))
        return Check("ok")
    if op.op is OpType.REPLACE_NODE:
        return _unapply_replace(law, op)
    if op.op is OpType.INSERT_NODE:
        return _unapply_insert(law, op)
    return Check("fail", f"unsupported op {op.op}")


def _numbered(path: Path, label: str) -> Path:
    """``path`` with its last bent or fıkra numbered ``label``."""
    key = label_key(label)
    if path.bent is not None:
        return path.model_copy(update={"bent": key})
    return path.model_copy(update={"fikra": int(key)})


def _relabel(law: Law, path: Path, old: str, new: str) -> None:
    """Number the node at ``path`` ``new`` instead of ``old`` ("16." -> "17.") and move it
    to its number's place among its siblings. 6322 and 6327 each added a bent "16." to
    md. 75/2; 6353/65 renumbered the first to 17, and it now stands after the other. Going
    back, a node goes before a sibling with its number (it was there first)."""
    loc = locate(law, path, whole=True, live=False)
    n, sibs = loc.node, loc.siblings
    if label_key(n.label or "") != label_key(old):
        raise ReplayError(f"{path} is numbered {n.label!r}, not {old!r}")
    n.label = new
    key = label_key(new)
    if not key.isdigit():
        return
    others = [s for s in sibs if s is not n and s.level is n.level
              and label_key(s.label or "").isdigit()]
    if not others:
        return  # no number to place it by
    sibs.remove(n)
    ids = {id(s) for s in others}
    numbered = [(i, int(label_key(s.label or ""))) for i, s in enumerate(sibs) if id(s) in ids]
    later = int(key) > int(label_key(old))
    if later:
        i = max((i + 1 for i, k in numbered if k <= int(key)), default=0)
    else:
        i = min((i for i, k in numbered if k >= int(key)), default=len(sibs))
    sibs.insert(i, n)


def _next_to(o: tuple[TextSlot, int, int], anchors: list[tuple[TextSlot, int, int]],
             position: str | None) -> bool:
    """Does the ibare at ``o`` sit right after (or before) one of the anchors?"""
    sl, s, e = o
    text = sl.get()
    for asl, a_s, a_e in anchors:
        if asl is not sl:
            continue
        if position == "after" and a_e <= s and not text[a_e:s].strip():
            return True
        if position == "before" and e <= a_s and not text[e:a_s].strip():
            return True
    return False


def _differs(have: list[Node], want: list[Node], with_title: bool = True) -> str | None:
    """Where the consolidated nodes ``have`` differ from the act's ``want``. Raises
    :class:`Superseded` if ``have`` holds text a later operation replaced wholesale."""
    if any(n.text == UNKNOWN or (with_title and n.title == UNKNOWN)
           for h in have for n in h.walk()):
        raise Superseded()
    a = [x for n in have for x in node_lines(n, with_title)]
    b = [x for n in want for x in node_lines(n, with_title)]
    if a == b:
        return None
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return f"line {i + 1}: consolidated {_around(x, y)} != act {_around(y, x)}"
    return f"{len(a)} lines in consolidated text, {len(b)} in the act"


def _around(x: str, y: str, width: int = 60) -> str:
    """``x`` around the first position where it differs from ``y``."""
    i = next((k for k, (p, q) in enumerate(zip(x, y, strict=False)) if p != q),
             min(len(x), len(y)))
    lo = max(0, i - width)
    return repr(("…" if lo else "") + x[lo:i + width] + ("…" if i + width < len(x) else ""))


def _unapply_replace(law: Law, op: AmendmentOp) -> Check:
    t = op.target
    if t.baslik:
        art = law.article(t.madde)
        if art is None:
            return Check("fail", f"article {t.madde} not found")
        if art.title == UNKNOWN:
            raise Superseded()
        if norm(art.title or "") != norm(op.new or ""):
            return Check("fail", f"title is {art.title!r}, act says {op.new!r}")
        art.title = UNKNOWN
        return Check("ok")
    loc = locate(law, t, live=_live(op))
    if op.kind is Level.PARAGRAF or loc.sentence is not None:
        if loc.sentence is not None:
            s, e = _span(loc.node.text, loc.sentence)
            have = loc.node.text[s:e]
        else:
            have = loc.node.text
        if UNKNOWN in have:
            raise Superseded()
        if norm(have) != norm(op.new or ""):
            return Check("fail", f"text is {have[:120]!r}, act says {(op.new or '')[:120]!r}")
        if loc.sentence is None:
            loc.node.text = UNKNOWN
            return Check("ok")
        return Check("lossy", "replaced sentence")
    if loc.node.level is Level.MADDE:
        diff = _differs([loc.node], op.new_nodes[:1], with_title=op.with_title)
        if diff:
            return Check("fail", diff)
        title = loc.node.title
        _blank(loc.node)
        loc.node.title = UNKNOWN if op.with_title else title
        return Check("ok")
    i = _index(loc.siblings, loc.node)
    k = len(op.new_nodes)
    diff = _differs(loc.siblings[i:i + k], _keep_label(loc.node, op.new_nodes))
    if diff:
        return Check("fail", diff)
    placeholder = Node(level=loc.node.level, label=loc.node.label, text=UNKNOWN)
    loc.siblings[i:i + k] = [placeholder]
    return Check("ok")


def _with_siblings(node: Node, siblings: list[Node]) -> list[tuple[Node, list[Node]]]:
    out = [(node, siblings)]
    for c in node.children:
        out.extend(_with_siblings(c, node.children))
    return out


def _inserted_differs(have: list[Node], want: list[Node]) -> str | None:
    """Like :func:`_differs`, for nodes an operation inserted. A later operation may have
    replaced part of them; they are removed anyway, and the replay inserts the act's text
    again before applying the later operation on it."""
    try:
        return _differs(have, want)
    except Superseded:
        return None


def _unapply_insert(law: Law, op: AmendmentOp) -> Check:
    t = op.target
    k = len(op.new_nodes)
    if op.kind is Level.MADDE:
        diffs = []
        for n in op.new_nodes:
            art = law.article(n.id or "")
            if art is None:
                return Check("fail", f"inserted article {n.id} not found")
            diff = _inserted_differs([art], [n])
            if diff and not art.repealed:
                diffs.append(diff)
        # Removed even when it reads differently (a change we have no act for): the replay
        # adds the act's text back and the comparison shows the difference.
        for n in op.new_nodes:
            art = law.article(n.id or "")
            sibs = siblings_of(law, art)
            del sibs[_index(sibs, art)]
        return Check("fail", diffs[0]) if diffs else Check("ok")
    loc = locate(law, t, live=_live(op))
    if op.kind is Level.PARAGRAF and not op.new_nodes:
        new = op.new or ""
        if _is_sentence_op(op):
            occ = find_all(loc.node.text, new)
            if not occ:
                return Check("fail", f"inserted sentence not in text: {new[:120]!r}")
            s, e = occ[-1]
            loc.node.text = _remove_span(loc.node.text, s, e)
            return Check("ok")
        paras = [c for c in loc.node.children if c.level is Level.PARAGRAF
                 and norm(c.text) == norm(new)]
        if op.anchor:
            # Undone before the anchor is looked for: the anchor may be anywhere in the node.
            hits = [(n, sibs) for n, sibs in _with_siblings(loc.node, loc.siblings)
                    if n.level is Level.PARAGRAF and norm(n.text) == norm(new)]
            if not hits:
                return Check("fail", f"inserted paragraph not found: {new[:120]!r}")
            n, sibs = hits[0]
            del sibs[_index(sibs, n)]
            return Check("ok")
        if op.position in ("after", "before"):
            paras = [c for c in loc.siblings if c.level is Level.PARAGRAF
                     and norm(c.text) == norm(new)]
            if not paras:
                return Check("fail", f"inserted paragraph not found: {new[:120]!r}")
            del loc.siblings[_index(loc.siblings, paras[0])]
            return Check("ok")
        if not paras:
            return Check("fail", f"inserted paragraph not found: {new[:120]!r}")
        del loc.node.children[_index(loc.node.children, paras[-1])]
        return Check("ok")
    if op.position in ("after", "before"):
        i = _index(loc.siblings, loc.node) + (1 if op.position == "after" else 0)
        if op.position == "before":
            i -= k
            if i < 0:
                return Check("fail", "nothing before the anchor")
        got = loc.siblings[i:i + k]
        diff = _inserted_differs(got, op.new_nodes)
        if diff:
            return Check("fail", diff)
        del loc.siblings[i:i + k]
        if op.renumber:
            _renumber(loc.siblings, i, op.new_nodes, -k)
        return Check("ok")
    container = loc.node
    if op.kind in (Level.BENT, Level.ALT_BENT) and container.level is Level.MADDE:
        fikras = [c for c in container.children if c.level is Level.FIKRA]
        if fikras:
            container = fikras[-1]
    # Inserted at the end then; later insertions at the end were undone already, but an
    # amendment may have added it with an explicit number among others ("(15) numaralı").
    h = _end_split(container, op.new_nodes)
    head, k = op.new_nodes[:h], h
    sibs, after = [], slice(0)
    if h < len(op.new_nodes):
        sibs = siblings_of(law, container)
        i = _index(sibs, container) + 1
        after = slice(i, i + len(op.new_nodes) - h)
    keys = [n.key for n in head]
    if keys and all(keys):
        idx = [i for i, c in enumerate(container.children) if c.key in keys
               and c.level in (Level.BENT, Level.ALT_BENT, Level.FIKRA)]
        if len(idx) == k and idx == list(range(idx[0], idx[0] + k)):
            return _remove_end(container, idx[0], k, sibs, after, op.new_nodes)
    # The last nodes of the first one's level, with what follows them ("şarttır." after
    # an added bent's alt bents is a paragraph of the fıkra).
    kb = sum(1 for n in head if n.level is head[0].level) if head else 0
    same_level = [i for i, c in enumerate(container.children)
                  if c.level is head[0].level] if head else []
    if not head or len(same_level) < kb:
        return Check("fail", f"{k} inserted node(s) not found in {t}")
    return _remove_end(container, same_level[-kb], k, sibs, after, op.new_nodes)


def _remove_end(container: Node, start: int, k: int, sibs: list[Node], after: slice,
                want: list[Node]) -> Check:
    """Remove ``k`` children of ``container`` from ``start`` and the fıkras ``after`` it
    in ``sibs``, if they read as ``want``."""
    got = container.children[start:start + k] + sibs[after]
    diff = _inserted_differs(got, want)
    if diff:
        return Check("fail", diff)
    del container.children[start:start + k]
    del sibs[after]
    return Check("ok")
