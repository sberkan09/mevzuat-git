"""Core data model: a law as a tree, and amendments as structured patch ops."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Level(str, Enum):
    MADDE = "madde"
    FIKRA = "fikra"
    BENT = "bent"
    ALT_BENT = "alt_bent"


class Node(BaseModel):
    level: Level
    label: str  # e.g. "23", "(2)", "a)", "1."
    title: str | None = None  # madde başlığı
    text: str = ""
    children: list[Node] = Field(default_factory=list)
    repealed: bool = False  # mülga


class Law(BaseModel):
    number: int  # kanun numarası, e.g. 193
    name: str
    articles: list[Node] = Field(default_factory=list)


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
