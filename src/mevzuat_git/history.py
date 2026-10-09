"""Faz 4: write the replay as a git history, one commit per amending act and yürürlük date.

The replay of Faz 3 starts from the law as it stood before the earliest act we have and
applies the acts in the order they were published. After each act (or each part of an
act that took effect on its own date) the law is rendered to Markdown and committed.

* **Dates.** A commit's author and committer date is the yürürlük date, read from the
  yürürlük table at the end of the consolidated text (``AmendingAct.effective``). The
  table names the target law's articles, so each operation takes the date of the row that
  names its article. When no row does, or a row cannot be read as one date, the RG
  (yayım) date is used and the message says so. Commits stay in publication order, so
  dates are not always increasing (an act published later may take effect earlier).
* **Start.** The first commit is the replay's starting point: text that a later act
  replaced wholesale is unknown there and shows as :data:`UNKNOWN_TEXT`.
* **End.** The replay does not reproduce every article (acts we cannot read, operations
  we cannot parse). A last commit brings the file to today's consolidated text and lists
  the articles it changes, so the history always ends at the official text.

The history is deterministic: same inputs, same commit hashes.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from mevzuat_git import amendments as am
from mevzuat_git import mevzuat_gov as mg
from mevzuat_git.amendment_list import AmendingAct, AmendmentList, EffectiveEntry
from mevzuat_git.amendments import OpsFile
from mevzuat_git.compare import node_lines, strip_editorial
from mevzuat_git.model import Law, Level, Node, OpType
from mevzuat_git.render import to_markdown
from mevzuat_git.replay import UNKNOWN
from mevzuat_git.verify import OpResult, articles_of, batches, op_results, replay_batch, unwind

UNKNOWN_TEXT = "[Bu tarihteki metin bilinmiyor.]"

AUTHOR = ("mevzuat-git", "mevzuat-git@users.noreply.github.com")

# -- yürürlük dates --------------------------------------------------------------------------

_DATE = r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{4}"
_ARTICLE_RE = re.compile(r"(?:(?P<prefix>Mükerrer|Mükerer|Geçici|Ek)\s+)?(?:Madde\s+)?"
                         r"(?P<num>\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ](?![a-zçğıöşü]))?)", re.IGNORECASE)


_SUFFIX = r"(?:inci|nci|ncı|üncü|uncu|ıncı)"


def table_articles(text: str) -> list[tuple[str, str]]:
    """Articles named in the first column of a yürürlük table row, each with the text that
    names it: "Mükerrer 21, 25, 94 üncü maddenin (15) numaralı bendi" ->
    [("mukerrer-21", ...), ("25", ...), ("94", "94 üncü maddenin (15) numaralı bendi")].

    - A prefix carries over "ve" ("Geçici 73 ve 74 Maddeler"), and over commas to the
      next numbers in sequence in a list ending in "Maddeler" ("Geçici 61, 62, 63 ve 64
      üncü Maddeler"). Otherwise it does not: "Mükerrer 21, 25" is mükerrer 21 and 25.
    - A piece with an ordinal and no "madde" ("7 nci" in "Geçici Madde 67’nin 1 inci
      fıkrasının birinci paragrafı, 7 nci, 14 üncü, 17 nci fıkrası") is not an article but
      part of the previous one, and its text goes with it."""
    text = re.sub(r"\(\s*…\s*\)|\[\d+\]", " ", text)
    pieces = [p.strip() for p in text.split(",")]
    out: list[list[str]] = []  # [id, text]
    for k, piece in enumerate(pieces):
        if out and re.match(rf"\d+\s*{_SUFFIX}\b", piece) \
                and not re.search(r"madde", piece, re.IGNORECASE):
            out[-1][1] += ", " + piece
            continue
        prefix = None
        for sub in re.split(r"\s+ve\s+", piece):
            m = _ARTICLE_RE.search(sub)
            if not m:
                continue
            num = m.group("num").replace(" ", "")
            if m.group("prefix"):
                prefix = m.group("prefix")
            elif prefix is None and out and "-" in out[-1][0] and num.isdigit() \
                    and out[-1][0].split("-", 1)[1] == str(int(num) - 1) \
                    and _list_of_articles(pieces[k:]):
                prefix = out[-1][0].split("-", 1)[0]
            out.append([mg.article_id(prefix, num), piece])
    return [(a, t) for a, t in out]


def _list_of_articles(rest: list[str]) -> bool:
    """Does the list go on, without a new prefix, to a piece ending in "Maddeler"?"""
    for p in rest:
        if re.search(r"Maddeler\s*$", p, re.IGNORECASE):
            return True
        if re.match(r"(?:Mükerrer|Mükerer|Geçici|Ek)\b", p, re.IGNORECASE):
            return False
    return False


def _month_start(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


_DAY_ORDINALS = {"birinci": 1, "ikinci": 2, "üçüncü": 3, "dördüncü": 4, "beşinci": 5,
                 "altıncı": 6, "yedinci": 7, "sekizinci": 8, "dokuzuncu": 9, "onuncu": 10}


def yururluk_date(text: str, rg_date: date | None) -> date | None:
    """The yürürlük date in the second column of a yürürlük table row, or None if the
    text does not give one date for the whole row.

    "1/1/2007 tarihinden geçerli olmak üzere 4/4/2007": the provision takes effect on
    4/4/2007 and applies from 1/1/2007; the yürürlük date is 4/4/2007. "... uygulanmak
    üzere yayımı tarihinde (26/10/2021)", "31/3/2006 tarihini izleyen aybaşında"
    (1/4/2006) and "9/4/2003 tarihini izleyen ikinci aybaşında" (1/6/2003) likewise."""
    t = re.sub(r"\(\s*…\s*\)|\[\d+\]", " ", text)
    if re.search(r"madde", t, re.IGNORECASE):
        return None  # different dates for different articles
    clause = re.split(r"\büzere\b", t)[-1].strip()
    if m := re.search(rf"({_DATE})\s+tarihini\s+(?:izleyen|takip\s+eden)\s+(ikinci\s+)?aybaşında",
                      clause):
        d = mg.parse_date(m.group(1))
        return _month_start(d, 2 if m.group(2) else 1) if d else None
    if re.search(r"yayım\w*\s+tarihini\s+(?:izleyen|takip\s+eden)\s+ay\s*başında", clause):
        return _month_start(rg_date, 1) if rg_date else None
    if re.search(r"yayımı\s+tarihinde", clause):
        dates = re.findall(_DATE, clause)
        if len(dates) > 1:
            return None
        return mg.parse_date(dates[0]) if dates else rg_date
    if m := re.search(rf"\b(?:tarihte|ay(?:ın)?\s*başında)\s*\(\s*({_DATE})\s*\)\s*$", clause):
        # KHK 700: "... Cumhurbaşkanının andiçerek göreve başladığı tarihte (9/7/2018)";
        # VUK: "yayımını izleyen ayın başında (1/8/2025)" (7555), "Yayım tarihi olan
        # 27/3/2018’i izleyen ikinci aybaşında (1/5/2018)" (7103).
        return mg.parse_date(m.group(1))
    if m := re.search(rf"({_DATE})\s+tarihini\s+(?:izleyen|takip\s+eden)\s+(?:(\w+)\s+)?günde\s*$",
                      clause):
        # "31/7/2004 tarihini izleyen üçüncü günde" (VUK mükerrer 355, 5228).
        n = _DAY_ORDINALS.get(m.group(2) or "", None) if m.group(2) else 1
        d = mg.parse_date(m.group(1))
        return d + timedelta(days=n) if d and n else None
    dates = re.findall(_DATE, clause)
    if len(dates) == 1 and re.fullmatch(rf"\s*\d*\s*{_DATE}\s*(?:tarihinde)?\s*", clause):
        return mg.parse_date(dates[0])
    return None


_CLAUSE_SPLIT = re.compile(
    r",\s*(?=-?\s*(?:\d+\s*(?:inci|nci|ncı|üncü|uncu|ıncı)\b|geçici\b|mükerrer\b|ek\b|diğer\b))"
    r"|\s+(?=diğer\b)", re.IGNORECASE)
_CLAUSE_HEAD_END = re.compile(rf"{_DATE}|\b(?:yapılan|yer\s+alan|ilişkin|hükm|tarih|yayım|"
                              r"ibare)", re.IGNORECASE)
_CLAUSE_ARTICLE = re.compile(r"(?:(?P<prefix>Mükerrer|Geçici|Ek)\s+(?:madde\s+)?)?(?P<num>\d+)"
                             r"(?:\s*(?:inci|nci|ncı|üncü|uncu|ıncı)\b|\s|$)", re.IGNORECASE)


def clause_dates(text: str, rg_date: date | None) -> dict[str | None, date]:
    """Dates of a yürürlük row that gives different dates for different articles:
    "23 üncü maddesi ve 29 uncu maddesi 1/2/2019 tarihinde, Geçici madde 76 1/1/2019
    tarihinde" -> {"23": 1/2/2019, "29": 1/2/2019, "gecici-76": 1/1/2019}. "diğer
    hükümleri/maddeleri" gives the date for the rest (key None). A clause without a date
    ("9 uncu, 89 uncu maddeleri ... yayımı tarihinde") takes the next one's."""
    out: dict[str | None, date] = {}
    pending: list[str | None] = []
    for clause in _CLAUSE_SPLIT.split(re.sub(r"\(\s*…\s*\)|\[\d+\]", " ", text)):
        clause = clause.strip(" ,-")
        m = _CLAUSE_HEAD_END.search(clause)
        head = clause[:m.start()] if m else clause
        if re.match(r"diğer\b", clause, re.IGNORECASE):
            pending.append(None)
        pending += [mg.article_id(a.group("prefix"), a.group("num"))
                    for a in _CLAUSE_ARTICLE.finditer(head)]
        if not m:
            continue
        d = yururluk_date(clause[len(head):], rg_date)
        if d is None:
            continue
        for a in pending:
            out.setdefault(a, d)
        pending = []
    return out


@dataclass(frozen=True)
class Dated:
    """The yürürlük date of an operation and where it came from."""

    date: date
    source: str  # the table row, verbatim, or a note on the fallback
    assumed: bool = False


def _parts(text: str) -> dict[str, set[str]]:
    """The parts of an article a table row names: "1 inci fıkrasının altıncı paragrafı, 8
    inci fıkrası" -> fıkra {1, 8}, paragraf {6}; "(15) numaralı bendi" and "94/10-a" ->
    bent {15} / {10} and alt bent {a}."""
    out: dict[str, set[str]] = {"fikra": set(), "paragraf": set(), "bent": set(),
                                "alt_bent": set()}
    for m in re.finditer(r"\b\d+\s*/\s*(\d+)(?:\s*-\s*([a-zçğıöşü]))?", text):
        out["bent"].add(m.group(1))
        if m.group(2):
            out["alt_bent"].add(m.group(2))
    out["bent"] |= set(re.findall(r"\((\d+)\)\s*numaralı\s+bend", text))
    out["alt_bent"] |= set(re.findall(r"\(([a-zçğıöşü])\)\s*alt\s+bend", text))
    for m in re.finditer(r"(\w+)\s+paragraf", text):
        if m.group(1) in am.ORDINALS:
            out["paragraf"].add(str(am.ORDINALS[m.group(1)]))
    # Ordinal numbers that are not the article: fıkralar ("7 nci, 14 üncü, 17 nci fıkrası").
    for m in re.finditer(rf"\b(\d+)\s*{_SUFFIX}\b(?!\s+madde)", text, re.IGNORECASE):
        if not re.match(r"\s*[’']?\s*(?:nin|nın)", text[m.end():]):
            out["fikra"].add(m.group(1))
    return out


def _op_parts(r: OpResult) -> dict[str, set[str]]:
    t = r.op.target
    out = {"fikra": {str(t.fikra)} if t.fikra else set(),
           "paragraf": {str(t.paragraf)} if t.paragraf else set(),
           "bent": {t.bent} if t.bent else set(),
           "alt_bent": {t.alt_bent} if t.alt_bent else set()}
    field = {Level.FIKRA: "fikra", Level.BENT: "bent", Level.ALT_BENT: "alt_bent"}.get(r.op.kind)
    if field and r.op.op is OpType.INSERT_NODE:
        out[field] |= {n.key for n in r.op.new_nodes if n.key}
    return out


def _score(row: dict[str, set[str]], op: dict[str, set[str]]) -> int:
    """How well a row's parts fit an operation's: +1 for each kind of part they share, -1
    for each kind the row names but the operation does not reach."""
    score = 0
    for k, names in row.items():
        if names and op[k]:
            score += 1 if names & op[k] else -1
    return score


def op_date(r: OpResult, act: AmendingAct | None, rg_date: date,
            as_of: date | None = None) -> Dated:
    """The yürürlük date of one operation, from the act's yürürlük table rows. A date
    after ``as_of`` (the consolidated text's day) is taken as it is, however far."""
    arts = articles_of(r.op)
    rows: list[tuple[EffectiveEntry, str]] = []
    for e in act.effective if act else []:
        rows.extend((e, piece) for a, piece in table_articles(e.articles) if a in arts)
    note = ""
    if len(rows) > 1:
        # "94 üncü maddenin (11) numaralı bendi" / "(15) numaralı bendi": the row that
        # names the part the operation acts on, or adds.
        # On a tie, the row that names fewer parts: "94" covers what "94/10-a" does not.
        parts = _op_parts(r)
        scores = [(_score(_parts(p), parts), -sum(map(len, _parts(p).values())))
                  for _, p in rows]
        best = max(scores)
        rows = [row for row, sc in zip(rows, scores, strict=True) if sc == best]
        if len({e.effective for e, _ in rows}) > 1:
            note = " (birden çok satıra uyuyor; ilki alındı)"
    if not rows and r.effective is not None:
        # An Anayasa Mahkemesi annulment: on publication (Anayasa md. 153), or on the
        # later date the decision sets ("... yayımlanmasından başlayarak dokuz ay sonra").
        return Dated(r.effective, "satır yok; iptal hükmü kararın yayımıyla yürürlüğe girer "
                     "(Anayasa md. 153)" if r.effective == rg_date
                     else "satır yok; iptal hükmünün yürürlüğe gireceği tarih kararda belirlenmiş")
    if not rows:
        return Dated(rg_date, "yürürlük tablosunda yok; yayım tarihi alındı", assumed=True)
    e, _ = rows[0]
    d = yururluk_date(e.effective, rg_date)
    if d is None:
        by_article = clause_dates(e.effective, rg_date)
        d = next((by_article[a] for a in arts if a in by_article), by_article.get(None))
    if d is None:
        return Dated(rg_date, f"{e.articles}: {e.effective} (tek tarih okunamadı; yayım "
                              "tarihi alındı)", assumed=True)
    if (d - rg_date).days > 3 * 365 and not (as_of and d > as_of):
        # 4761 (RG 22/6/2002): "22/6/2012" in the table.
        return Dated(rg_date, f"{e.articles}: {e.effective} (yayımdan çok sonra; yayım "
                              "tarihi alındı)", assumed=True)
    return Dated(d, f"{e.articles}: {e.effective}{note}", assumed=bool(note))


# -- commits ---------------------------------------------------------------------------------

@dataclass
class Commit:
    date: date
    subject: str
    body: list[str] = field(default_factory=list)


def _for_output(law: Law) -> Law:
    """Placeholders spelled out; mevzuat.gov.tr's own additions left out."""
    out = law.model_copy(deep=True)

    def fix(n: Node) -> None:
        n.text = UNKNOWN_TEXT if n.text == UNKNOWN else strip_editorial(n.text)
        if n.title:
            n.title = UNKNOWN_TEXT if n.title == UNKNOWN else strip_editorial(n.title)
        for c in n.children:
            fix(c)

    for n in out.body:
        fix(n)
    return out


def render(law: Law) -> str:
    # mevzuat.gov.tr's change notes ("(Değişik: ...)") describe the text's later history:
    # left out, they would be anachronistic in an earlier commit.
    return to_markdown(_for_output(law), notes=False)


def _fmt(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year}"


def _art_list(ids: list[str]) -> str:
    def label(i: str) -> str:
        kind, _, num = i.rpartition("-")
        return {"mukerrer": "mükerrer ", "gecici": "geçici ", "ek": "ek "}.get(kind, "") + num
    return ", ".join(label(i) for i in ids)


class GitRepo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _git(self, *args: str, env: dict[str, str] | None = None) -> str:
        e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        e.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        e.update(env or {})
        return subprocess.run(["git", "-C", str(self.path), *args], env=e, check=True,
                              capture_output=True, text=True).stdout

    def init(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q", "-b", "main")

    def commit(self, c: Commit, files: dict[str, str]) -> None:
        for name, text in files.items():
            (self.path / name).write_text(text, encoding="utf-8")
            self._git("add", name)
        stamp = f"{c.date.isoformat()}T00:00:00+0300"
        env = {"GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1],
               "GIT_COMMITTER_NAME": AUTHOR[0], "GIT_COMMITTER_EMAIL": AUTHOR[1],
               "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        msg = c.subject + ("\n\n" + "\n".join(c.body) if c.body else "")
        self._git("commit", "-q", "--allow-empty", "--no-gpg-sign", "-m", msg, env=env)


@dataclass
class Step:
    """Batches of one act that take effect on one date."""

    act: str
    rg_date: date
    rg_number: str | None
    text_url: str
    source: str  # ActOps.source: "rg" or "footnotes"
    kind: str  # AmendingAct.kind: kanun, khk, cbk, aym
    date: date
    sources: list[Dated]  # one per distinct table row or fallback note
    batches: list[list[OpResult]]

    @property
    def articles(self) -> list[str]:
        out: list[str] = []
        for b in self.batches:
            for r in b:
                for a in articles_of(r.op):
                    if a and a not in out:
                        out.append(a)
        return out


def mark_pending(opsfile: OpsFile, alist: AmendmentList, as_of: date) -> int:
    """Mark the operations whose yürürlük date comes after ``as_of``, the day the
    consolidated text was fetched; returns how many."""
    acts = {a.number: a for a in alist.acts}
    n = 0
    for rec, amd, op in opsfile.ops():
        if rec.rg_date is None:
            continue
        r = OpResult(act=rec.act, article=amd.article, op=op, effective=amd.effective_date)
        d = op_date(r, acts.get(rec.act), rec.rg_date, as_of).date
        op.pending = d if d > as_of else None
        n += op.pending is not None
    return n


def plan(groups: list[list[OpResult]], opsfile: OpsFile, alist: AmendmentList) -> list[Step]:
    """Commits to make, in publication order; within an act, by yürürlük date."""
    acts = {a.number: a for a in alist.acts}
    steps: list[Step] = []
    by_act: dict[str, list[list[OpResult]]] = {}
    for b in groups:
        by_act.setdefault(b[0].act, []).append(b)
    for rec in opsfile.acts:
        if rec.act not in by_act or rec.rg_date is None:
            continue
        dated: dict[date, tuple[list[Dated], list[list[OpResult]]]] = {}
        for b in by_act[rec.act]:
            d = op_date(b[0], acts.get(rec.act), rec.rg_date)
            sources, bs = dated.setdefault(d.date, ([], []))
            if d not in sources:
                sources.append(d)
            bs.append(b)
        for day, (sources, bs) in sorted(dated.items()):
            kind = acts[rec.act].kind if rec.act in acts else "kanun"
            steps.append(Step(rec.act, rec.rg_date, rec.rg_number, rec.text_url, rec.source,
                              kind, day, sources, bs))
    return steps


def build(current: Law, opsfile: OpsFile, alist: AmendmentList, out: Path) -> list[Commit]:
    """Write the history of ``current`` into a new git repository at ``out``."""
    return build_many([(current, opsfile, alist)], out)


@dataclass
class _LawHistory:
    current: Law
    state: Law
    steps: list[Step]

    @property
    def name(self) -> str:
        return f"{self.current.number}.md"


def build_many(laws: list[tuple[Law, OpsFile, AmendmentList]], out: Path) -> list[Commit]:
    """Write the histories of several laws into one new git repository at ``out``, one
    file per law. An act that amends more than one of them on the same yürürlük date (a
    torba kanun) is one commit that changes every file it touches. Each law's commits keep
    their order; across laws, commits go in publication order, then by yürürlük date."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty")
    hs: list[_LawHistory] = []
    for current, opsfile, alist in laws:
        groups = batches(op_results(opsfile))
        state = unwind(current, groups)  # sets the checks the replay relies on
        steps = plan(groups, opsfile, alist)
        if not steps:
            raise ValueError(f"{current.number}: no operations to replay")
        hs.append(_LawHistory(current, state, steps))
    repo = GitRepo(out)
    repo.init()
    commits: list[Commit] = []
    pos = [0] * len(hs)
    while True:
        heads = [(h.steps[pos[i]], i) for i, h in enumerate(hs) if pos[i] < len(h.steps)]
        if not heads:
            break
        first, _ = min(heads, key=lambda x: (x[0].rg_date, x[0].date, x[1]))
        together = [i for s, i in heads
                    if (s.act, s.rg_date, s.date) == (first.act, first.rg_date, first.date)]
        for i in together:
            if pos[i] == 0:
                c = _start_commit(hs[i])
                repo.commit(c, {hs[i].name: render(hs[i].state)})
                commits.append(c)
        parts: list[tuple[int, Step]] = []
        for i in together:
            s = hs[i].steps[pos[i]]
            for b in s.batches:
                replay_batch(hs[i].state, b)
            parts.append((hs[i].current.number, s))
            pos[i] += 1
        # With several laws, every subject names the law: "7582 sayılı Kanun: 193 md. 17".
        c = _step_commit(parts[0][1]) if len(hs) == 1 else _joint_commit(parts)
        repo.commit(c, {hs[i].name: render(hs[i].state) for i in together})
        commits.append(c)
    syncs = [(h, *_differing_articles(h.state, h.current)) for h in hs]
    syncs = [(h, content, typo) for h, content, typo in syncs if content or typo]
    if syncs:
        last = max(c.date for c in commits)
        if len(hs) == 1:
            h, content, typo = syncs[0]
            c = Commit(last, f"{h.current.number} sayılı Kanun: güncel konsolide metinle "
                       "eşitleme", [_SYNC_INTRO, "", *_sync_lists(content, typo)])
        else:
            body = [_SYNC_INTRO]
            for h, content, typo in syncs:
                body += ["", f"{h.current.number} sayılı Kanun:", *_sync_lists(content, typo)]
            c = Commit(last, "Güncel konsolide metinlerle eşitleme: "
                       + ", ".join(str(h.current.number) for h, _, _ in syncs), body)
        repo.commit(c, {h.name: render(h.current) for h, _, _ in syncs})
        commits.append(c)
    return commits


_SYNC_INTRO = ("Değişikliklerin yeniden oynatılmasıyla elde edilen metin, mevzuat.gov.tr'deki "
               "güncel metinden ayrılıyor; bu commit dosyayı güncel metne getirir.")


def _sync_lists(content: list[str], typography: list[str]) -> list[str]:
    body: list[str] = []
    if content:
        body += [("İçeriği ayrılan maddeler (Resmî Gazete metni okunamayan ya da henüz "
                  "ayrıştırılamayan değişiklikler; ayrıntı: mevzuat-git replay raporu):"),
                 _art_list(content), ""]
    if typography:
        body += [("Yalnız yazımı ayrılan maddeler (değiştiren kanunun yazımı ile güncel "
                  "metninki: tırnak, tire, şapka, madde başlığı biçimi):"),
                 _art_list(typography), ""]
    return body[:-1]


def _start_commit(h: _LawHistory) -> Commit:
    # Dated with the law's first step, which it precedes.
    s = h.steps[0]
    return Commit(min(s.date, s.rg_date),
                  f"{h.current.number} sayılı {h.current.name}: başlangıç metni", [(
                      "Resmî Gazete metni elimizde olan en eski değişiklikten önceki hâl. "
                      "Bugünkü konsolide metinden, değişiklikler geri alınarak elde edildi; "
                      "sonradan bütünüyle değiştirilen metinlerin o tarihteki hâli "
                      f"bilinmiyor, yerlerinde \"{UNKNOWN_TEXT}\" yazar.")])


def _joint_commit(parts: list[tuple[int, Step]]) -> Commit:
    """One act's step on one or more laws of a multi-law repository: "7338 sayılı Kanun:
    193 md. mükerrer 20/A; 213 md. 4"."""
    singles = [(law, _step_commit(s)) for law, s in parts]
    first = singles[0][1]
    head = first.subject.partition(": md. ")[0]
    subject = head + ": " + "; ".join(f"{law} md. {_art_list(s.articles)}" for law, s in parts)
    body: list[str] = []
    for law, c in singles:
        body += ([""] if body else []) + [f"{law} sayılı Kanun:", *c.body]
    return Commit(first.date, subject, body)


def _differing_articles(replayed: Law, current: Law) -> tuple[list[str], list[str]]:
    """Articles whose rendered text differs between the two laws, in ``current``'s order
    (articles only in ``replayed`` last): those that differ after normalisation, and those
    that differ only in typography."""
    def one(law: Law, art_id: str) -> Law | None:
        a = law.article(art_id)
        return None if a is None else Law(number=law.number, name="", body=[a])

    ids = [a.id for a in current.articles()]
    ids += [a.id for a in replayed.articles() if current.article(a.id) is None]
    content, typography = [], []
    for i in ids:
        x, y = one(replayed, i), one(current, i)
        if x is None or y is None:
            content.append(i)
        elif render(x) != render(y):
            same = node_lines(x.body[0]) == node_lines(y.body[0])
            (typography if same else content).append(i)
    # Article order is part of the text too.
    if [a.id for a in replayed.articles()] != [a.id for a in current.articles()]:
        content.append("(madde sırası)")
    return content, typography


def _step_commit(s: Step) -> Commit:
    arts = s.articles
    acts_articles = sorted({r.article for b in s.batches for r in b},
                           key=lambda a: (len(a), a))
    from_footnotes = s.source == "footnotes"
    if s.kind == "aym":
        # A decision has items in its operative part, not articles; a footnote names none.
        items = [a for a in acts_articles if a != "?"]
        by = [f"Hüküm fıkrası: {', '.join(items)}"] if items else []
        source = f"Kaynak: {s.text_url}" + (" (PDF; işlemler mevzuat.gov.tr konsolide metninin "
                                            "dipnotlarından okundu)" if from_footnotes else "")
    else:
        by = [f"Değiştiren maddeler: {', '.join(f'{s.act}/{a}' for a in acts_articles)}"]
        source = f"Kaynak: {s.text_url}" + (" (taranmış PDF; işlemler mevzuat.gov.tr konsolide "
                                            "metninin dipnotlarından okundu)"
                                            if from_footnotes else "")
    body = [
        f"Resmî Gazete: {_fmt(s.rg_date)}" + (f", sayı {s.rg_number}" if s.rg_number else ""),
        f"Yürürlük: {_fmt(s.date)}"
        + (" (varsayılan)" if all(d.assumed for d in s.sources) else ""),
        *(f"Yürürlük tablosu: {d.source}" for d in s.sources),
        *by,
        source,
    ]
    errors = [r for b in s.batches for r in b if r.replay_error]
    if errors:
        body += ["", "Uygulanamayan işlemler:"]
        body += [f"- {r.act}/{r.article} {r.op.op.value} {r.op.target}: {r.replay_error}"
                 for r in errors]
    if s.kind == "aym":
        # "AYM E.2025/219 K.2026/43: md. geçici 72"
        return Commit(s.date, f"AYM {s.act.replace(',', '')}: md. {_art_list(arts)}", body)
    name = {"khk": "KHK", "cbk": "Cumhurbaşkanlığı Kararnamesi"}.get(s.kind, "Kanun")
    return Commit(s.date, f"{s.act} sayılı {name}: md. {_art_list(arts)}", body)
