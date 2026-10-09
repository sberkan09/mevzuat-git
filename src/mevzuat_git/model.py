"""Core data model: a law as a tree, and amendments as structured patch ops."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Level(str, Enum):
    KISIM = "kisim"
    BOLUM = "bolum"
    MADDE = "madde"
    FIKRA = "fikra"
    BENT = "bent"
    ALT_BENT = "alt_bent"  # nests: alt bentlerin alt bentleri are ALT_BENT too
    PARAGRAF = "paragraf"  # unlabelled paragraph inside a fıkra or bent
    TABLO = "tablo"


class Node(BaseModel):
    """One node of a law.

    ``label`` and ``text`` are verbatim from the source (whitespace collapsed). Leading
    editorial markers of mevzuat.gov.tr such as ``(Değişik: 7/1/2003-4783/1 md.)`` are
    kept apart in ``notes`` and footnote reference numbers in ``footnotes``: neither is
    part of the legal text.
    """

    level: Level
    label: str = ""  # as written: "Madde 23", "Mükerrer Madde 20/A", "(2)", "a)", "1."
    id: str | None = None  # madde only: "23", "mukerrer-20/A", "gecici-67", "ek-1"
    title: str | None = None  # madde başlığı; kısım/bölüm adı
    text: str = ""
    notes: list[str] = Field(default_factory=list)
    footnotes: list[int] = Field(default_factory=list)
    children: list[Node] = Field(default_factory=list)
    repealed: bool = False  # mülga

    def walk(self) -> Iterator[Node]:
        yield self
        for c in self.children:
            yield from c.walk()

    @property
    def key(self) -> str:
        """Label without punctuation, for addressing: "(4)" / "4." / "4)" -> "4"."""
        return label_key(self.label)


def label_key(label: str) -> str:
    return re.sub(r"[\s().\-–]", "", label).casefold()


class Law(BaseModel):
    number: int  # kanun numarası, e.g. 193
    name: str
    body: list[Node] = Field(default_factory=list)  # kısım/bölüm headings and maddeler

    def articles(self) -> Iterator[Node]:
        for top in self.body:
            for n in top.walk():
                if n.level is Level.MADDE:
                    yield n

    def article(self, article_id: str) -> Node | None:
        return next((a for a in self.articles() if a.id == article_id), None)


class Path(BaseModel):
    """Address of a node inside a law: madde 23 / fıkra 2 / bent 4 / alt bent c ...

    ``fikra`` is a 1-based position ("ikinci fıkra", "(2) numaralı fıkra"); -1 is "son
    fıkra". ``bent`` and ``alt_bent`` are label keys ("4", "c"). ``cumle`` and
    ``paragraf`` narrow a phrase operation to one sentence or unlabelled paragraph.
    """

    madde: str  # canonical article id: "23", "mukerrer-80", "gecici-67"; "" = the law
    fikra: int | None = None
    bent: str | None = None
    alt_bent: str | None = None
    paragraf: int | None = None
    cumle: int | None = None
    baslik: bool = False  # the madde başlığı itself

    def __str__(self) -> str:
        parts = [f"md.{self.madde}" if self.madde else "law"]
        if self.baslik:
            parts.append("başlık")
        for name, v in (("f", self.fikra), ("b", self.bent), ("ab", self.alt_bent),
                        ("p", self.paragraf), ("c", self.cumle)):
            if v is not None:
                parts.append(f"{name}{v}")
        return "/".join(parts)


class OpType(str, Enum):
    REPLACE_PHRASE = "replace_phrase"  # "X" ibaresi "Y" şeklinde değiştirilmiştir
    INSERT_PHRASE = "insert_phrase"  # ... ibaresinden sonra gelmek üzere "Y" ibaresi eklenmiştir
    DELETE_PHRASE = "delete_phrase"  # ... ibaresi metinden çıkarılmıştır
    REPLACE_NODE = "replace_node"  # ... aşağıdaki şekilde değiştirilmiştir
    INSERT_NODE = "insert_node"  # ... sonra gelmek üzere aşağıdaki fıkra eklenmiştir
    REPEAL_NODE = "repeal_node"  # ... yürürlükten kaldırılmıştır
    RELABEL_NODE = "relabel_node"  # ... eklenen bendin “16.” olan numarası “17.” olarak


class AmendmentOp(BaseModel):
    op: OpType
    target: Path
    old: str | None = None  # phrase ops: the ibare being replaced/deleted
    new: str | None = None  # phrase ops: the new ibare; title-only replace: new title
    anchor: str | None = None  # insert_phrase: the ibare the new one goes after/before
    position: Literal["after", "before", "start", "end"] | None = None
    all: bool = False  # "ibareleri": every occurrence in the target
    paren: bool = False  # "parantez içi hükmü": the parenthesised part of the target
    kind: Level | None = None  # node ops: level of the inserted/replaced nodes
    new_nodes: list[Node] = Field(default_factory=list)
    with_title: bool = False  # "başlığıyla birlikte"
    renumber: bool = False  # teselsül
    source_sentence: str  # RG'deki ham cümle, izlenebilirlik için
    # Yürürlük after the day the consolidated text was fetched: not in it yet, so neither
    # unwound nor replayed (7524/20 adds KDV md. 30 (f) from 1/1/2030).
    pending: date | None = None
    # Operations read from a footnote of the consolidated text: the footnote's number and
    # the address of the node it is attached to today. ``target`` is resolved from where
    # that node is at the time the operation applies (see ``replay.rebase``).
    footnote: int | None = None
    footnote_path: Path | None = None


class Amendment(BaseModel):
    """One amending act applied to one target law."""

    amending_law: str
    article: str  # article of the amending act, e.g. "5"
    rg_date: date | None = None
    rg_number: str | None = None
    effective_date: date | None = None
    target_law: int
    ops: list[AmendmentOp]
