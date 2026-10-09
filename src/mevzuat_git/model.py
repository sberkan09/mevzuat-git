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
    """Address of a node: madde 23 / fıkra 2 / bent b ..."""

    madde: str
    fikra: int | None = None
    bent: str | None = None
    alt_bent: str | None = None
    kind: Literal["madde", "gecici", "ek"] = "madde"


class OpType(str, Enum):
    REPLACE_PHRASE = "replace_phrase"  # "X" ibaresi "Y" şeklinde değiştirilmiştir
    INSERT_PHRASE = "insert_phrase"  # ... ibaresinden sonra gelmek üzere "Y" ibaresi eklenmiştir
    DELETE_PHRASE = "delete_phrase"  # ... ibaresi metinden çıkarılmıştır
    REPLACE_NODE = "replace_node"  # ... aşağıdaki şekilde değiştirilmiştir
    INSERT_NODE = "insert_node"  # ... sonra gelmek üzere aşağıdaki fıkra eklenmiştir
    REPEAL_NODE = "repeal_node"  # ... yürürlükten kaldırılmıştır


class AmendmentOp(BaseModel):
    op: OpType
    target: Path
    old: str | None = None
    new: str | None = None
    new_node: Node | None = None
    renumber: bool = False  # teselsül
    source_sentence: str  # RG'deki ham cümle, izlenebilirlik için


class Amendment(BaseModel):
    """One amending law (or one article of a torba kanun) applied to one target law."""

    amending_law: int
    rg_date: date
    rg_number: str
    effective_date: date
    target_law: int
    ops: list[AmendmentOp]
