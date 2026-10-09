"""Faz 1: :class:`~mevzuat_git.model.Law` -> canonical Markdown.

Deterministic and diff friendly: one paragraph per node, labels and text exactly as in the
source. Only Markdown syntax is escaped (a bent label ``1.`` would otherwise become an
ordered list item), so un-escaping the output gives back the source text.
"""

from __future__ import annotations

import re

from mevzuat_git.model import Law, Level, Node

_LEADING = re.compile(r"^(\d+)([.)])|^([#>+*-])")


def escape(line: str) -> str:
    """Escape what Markdown would interpret at the start of a line."""
    return _LEADING.sub(lambda m: f"{m.group(1)}\\{m.group(2)}" if m.group(1)
                        else f"\\{m.group(3)}", line)


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def node_line(n: Node, notes: bool = True) -> str:
    """The node's own paragraph: label, editorial notes (optional) and text."""
    return _join(n.label, " ".join(n.notes) if notes else "", n.text)


def _table(n: Node) -> list[str]:
    rows = [r.split(" | ") for r in n.text.split("\n")]
    width = max(len(r) for r in rows)
    out = []
    for i, r in enumerate(rows):
        cells = [c.replace("|", "\\|") for c in r] + [""] * (width - len(r))
        out.append("| " + " | ".join(cells) + " |")
        if i == 0:
            out.append("|" + "---|" * width)
    return ["\n".join(out)]


def _render(n: Node, notes: bool) -> list[str]:
    out: list[str] = []
    if n.level in (Level.KISIM, Level.BOLUM):
        hashes = "##" if n.level is Level.KISIM else "###"
        if n.label:
            out.append(f"{hashes} {n.label}")
            if n.title:
                out.append(f"**{n.title}**")
        else:
            out.append(f"{hashes} {n.title or ''}")
    elif n.level is Level.MADDE:
        head = n.label + " –"
        out.append("#### " + _join(head, n.title or ""))
        if (notes and n.notes) or n.text:
            out.append(escape(_join(" ".join(n.notes) if notes else "", n.text)))
    elif n.level is Level.TABLO:
        out.extend(_table(n))
    else:
        line = node_line(n, notes)
        if line:
            out.append(escape(line))
    for c in n.children:
        out.extend(_render(c, notes))
    return out


def to_markdown(law: Law, notes: bool = True) -> str:
    """Render a law. ``notes=False`` drops mevzuat.gov.tr's editorial markers."""
    blocks = [f"# {law.name}"]
    for n in law.body:
        blocks.extend(_render(n, notes))
    return "\n\n".join(blocks) + "\n"
