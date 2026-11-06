"""Faz 6: data for the static viewer, read from a history repository.

The input is a repository written by ``mevzuat-git history`` (such as mevzuat-tarihce):
one ``<law>.md`` per law in Faz 1's canonical Markdown, one commit per amending act and
yürürlük date, in publication order. The output is JSON for the viewer in ``site/``:

* ``index.json``: the laws, with their date range and how many articles are unverified.
* ``<law>.json``: the law's commits (act, RG date and number, yürürlük, sources), the
  table of contents as it changed, and for each article every version it went through.
  A version is stored only when the article's text changed.

Nothing here touches the text: paragraphs are the file's own, with only the Markdown
escapes of :func:`mevzuat_git.render.escape` undone.

**Verification.** The history ends with a commit that brings each file to the official
consolidated text and lists the articles it changes. Those listed under "İçeriği ayrılan
maddeler" are *unverified*: the replay did not reproduce them, so their earlier versions
may be wrong. Those under "Yalnız yazımı ayrılan maddeler" differ only in typography. Every
other article matched the official text after replay.

**Text at a date.** Commits are in publication order and dated by yürürlük, so dates do
not always increase. The text of an article on day D is its version from the last commit,
in publication order, whose yürürlük is on or before D (:func:`article_at`).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from mevzuat_git import mevzuat_gov as mg

UNKNOWN_TEXT = "[Bu tarihteki metin bilinmiyor.]"  # mevzuat_git.history.UNKNOWN_TEXT

# -- the law file ----------------------------------------------------------------------------

_UNESCAPE_NUM = re.compile(r"^(\d+)\\([.)])")
_UNESCAPE_SYM = re.compile(r"^\\([#>+*-])")
_TABLE_SEP = re.compile(r"^\|(?:---\|)+$")
_CELL_SPLIT = re.compile(r"(?<!\\) \| ")


def unescape(line: str) -> str:
    """Undo :func:`mevzuat_git.render.escape`: "1\\. Ticarî kazançlar," -> "1. Ticarî ..."."""
    line = _UNESCAPE_NUM.sub(r"\1\2", line)
    return _UNESCAPE_SYM.sub(r"\1", line)


def _table(block: str) -> list[list[str]] | None:
    lines = block.split("\n")
    if len(lines) < 2 or not _TABLE_SEP.match(lines[1]) \
            or not all(ln.startswith("| ") and ln.endswith(" |") for ln in lines[:1] + lines[2:]):
        return None
    rows = []
    for ln in lines[:1] + lines[2:]:
        cells = _CELL_SPLIT.split(ln[2:-2])
        rows.append([c.replace("\\|", "|") for c in cells])
    return rows


Block = str | list[list[str]]  # a paragraph, or a table's rows


@dataclass
class Article:
    id: str
    label: str  # "Madde 40 –", "Geçici Madde 67 –"
    title: str  # "Safi kazancın tespitinde indirilecek giderler:" or ""
    blocks: list[Block] = field(default_factory=list)

    def version(self) -> dict:
        return {"label": self.label, "title": self.title, "body": self.blocks}


@dataclass
class LawFile:
    name: str
    toc: list  # article ids (str) and headings ({"l": 2|3, "t": text, "s": title})
    articles: dict[str, Article]
    preamble: list[Block] = field(default_factory=list)  # text outside any article


def parse_law(text: str) -> LawFile:
    """Read one law file of a history repository back into articles."""
    blocks = text.strip("\n").split("\n\n")
    name = blocks[0][2:] if blocks and blocks[0].startswith("# ") else ""
    law = LawFile(name=name, toc=[], articles={})
    current: Article | None = None
    heading: dict | None = None
    for b in blocks[1:]:
        m = re.match(r"^(#{2,4}) (.*)$", b)
        if m and "\n" not in b:
            level, rest = len(m.group(1)), m.group(2)
            if level == 4:
                current, heading = _open_article(law, rest), None
            else:
                heading = {"l": level, "t": rest, "s": None}
                law.toc.append(heading)
                current = None
            continue
        if heading is not None and heading["s"] is None and re.fullmatch(r"\*\*.*\*\*", b):
            heading["s"] = b[2:-2]  # the heading's title: "**Mükellefiyet**"
            continue
        heading = None
        block = _table(b) or unescape(b)
        (current.blocks if current else law.preamble).append(block)
    return law


def _open_article(law: LawFile, heading: str) -> Article:
    m = mg.ARTICLE_RE.match(heading)
    if m:
        label, title = m.group("label").strip(), heading[m.end():].strip()
        art_id = mg.article_id(m.group("prefix"), m.group("num"))
    else:  # not expected in the canonical Markdown; kept rather than dropped
        label, title, art_id = heading, "", "x-" + re.sub(r"\W+", "-", heading).strip("-")
    base, k = art_id, 2
    while art_id in law.articles:  # the same number twice: keep both
        art_id, k = f"{base}~{k}", k + 1
    a = Article(art_id, label, title)
    law.articles[art_id] = a
    law.toc.append(art_id)
    return a


# -- commit messages -------------------------------------------------------------------------

_DMY = r"(\d{1,2})/(\d{1,2})/(\d{4})"
_LAW_HEADER = re.compile(r"^(\d+) sayılı Kanun:$")
_FAILED = re.compile(r"^- (?P<act>\S+) (?P<op>\S+) md\.(?P<art>(?:[a-z]+-)?\d+(?:/[A-ZÇĞİÖŞÜ])?)"
                     r"(?=[/: ])")
_LIST_ITEM = re.compile(r"^(?:(mükerrer|geçici|ek) )?(\d+(?:/[A-ZÇĞİÖŞÜ])?)$")


def _dmy(text: str) -> date | None:
    m = re.match(_DMY, text)
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def article_ids(text: str) -> tuple[list[str], bool]:
    """An article list of a commit message: "23, mükerrer 20/A, geçici 59, ek 1" ->
    ["23", "mukerrer-20/A", "gecici-59", "ek-1"], and whether "(madde sırası)" is in it."""
    ids, order = [], False
    for item in (p.strip() for p in text.split(",")):
        if item == "(madde sırası)":
            order = True
            continue
        m = _LIST_ITEM.match(item)
        if m:
            ids.append(mg.article_id(m.group(1), m.group(2)))
    return ids, order


def subject_articles(subject: str, law: int | None) -> list[str]:
    """Articles a commit subject names for a law: "4684 sayılı Kanun: 193 md. 38; 3065
    md. 17" -> ["38"] for 193. ``law`` None: a single-law subject ("...: md. 38")."""
    _, _, rest = subject.partition(": ")
    prefix = "md. " if law is None else f"{law} md. "
    for part in rest.split("; "):
        if part.startswith(prefix):
            return article_ids(part[len(prefix):])[0]
    return []


@dataclass
class Section:
    """What a commit message says about one law."""

    rg_date: date | None = None
    rg_number: str | None = None
    effective: date | None = None
    assumed: bool = False  # "Yürürlük: ... (varsayılan)"
    table: list[str] = field(default_factory=list)  # "Yürürlük tablosu:" lines
    by: str | None = None  # "Değiştiren maddeler: ..." or "Hüküm fıkrası: ..."
    source: str | None = None
    source_note: str | None = None  # "(taranmış PDF; işlemler ... dipnotlarından okundu)"
    failed: dict[str, list[str]] = field(default_factory=dict)  # article -> operations
    content: list[str] = field(default_factory=list)  # sync: articles whose content differs
    typography: list[str] = field(default_factory=list)  # sync: only typography differs
    order_differs: bool = False  # sync: "(madde sırası)"


def parse_sections(body: str) -> dict[int | None, Section]:
    """The parts of a commit message body, by law ("193 sayılı Kanun:" opens one). Lines
    before any such header (a single-law history) are under None."""
    out: dict[int | None, Section] = {}
    sec = out.setdefault(None, Section())
    pending: str | None = None  # the list a header line announces
    for line in body.split("\n"):
        m = _LAW_HEADER.match(line)
        if m:
            sec = out.setdefault(int(m.group(1)), Section())
            continue
        if pending:
            ids, order = article_ids(line)
            getattr(sec, pending).extend(ids)
            sec.order_differs |= order
            pending = None
            continue
        if line.startswith("İçeriği ayrılan maddeler"):
            pending = "content"
        elif line.startswith("Yalnız yazımı ayrılan maddeler"):
            pending = "typography"
        elif line.startswith("Resmî Gazete: "):
            rest = line[len("Resmî Gazete: "):]
            sec.rg_date = _dmy(rest)
            num = re.search(r", sayı (.+)$", rest)
            sec.rg_number = num.group(1) if num else None
        elif line.startswith("Yürürlük: "):
            sec.effective = _dmy(line[len("Yürürlük: "):])
            sec.assumed = line.endswith("(varsayılan)")
        elif line.startswith("Yürürlük tablosu: "):
            sec.table.append(line[len("Yürürlük tablosu: "):])
        elif line.startswith(("Değiştiren maddeler: ", "Hüküm fıkrası: ")):
            sec.by = line
        elif line.startswith("Kaynak: "):
            url, _, note = line[len("Kaynak: "):].partition(" ")
            sec.source, sec.source_note = url, note.strip(" ()") or None
        elif (f := _FAILED.match(line)):
            sec.failed.setdefault(f.group("art"), []).append(line[2:])
    if out[None] == Section():
        del out[None]
    return out


def commit_kind(subject: str, body: str) -> str:
    """start, sync, aym, kanun, khk or cbk."""
    if subject.endswith(": başlangıç metni"):
        return "start"
    if "eşitleme" in subject and "yeniden oynatılmasıyla" in body:
        return "sync"
    head = subject.partition(": ")[0]
    if head.startswith("AYM "):
        return "aym"
    if head.endswith("KHK"):
        return "khk"
    if head.endswith("Kararnamesi"):
        return "cbk"
    return "kanun"


# -- the repository --------------------------------------------------------------------------

@dataclass
class RawCommit:
    sha: str
    date: date
    subject: str
    body: str
    files: list[str]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def read_commits(repo: Path) -> list[RawCommit]:
    """The repository's commits, oldest first, with the files each one changes."""
    out = _git(repo, "log", "--reverse", "--first-parent", "--name-only", "--date=short",
               "--format=%x1e%H%x00%ad%x00%s%x00%b%x00")
    commits = []
    for rec in out.split("\x1e")[1:]:
        sha, day, subject, body, files = rec.split("\x00")
        commits.append(RawCommit(sha, date.fromisoformat(day), subject, body.strip("\n"),
                                 [f for f in files.split("\n") if f.strip()]))
    return commits


def _remote_url(repo: Path) -> str | None:
    try:
        url = _git(repo, "remote", "get-url", "origin").strip()
    except subprocess.CalledProcessError:
        return None
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)(.+?)(?:\.git)?$", url)
    return f"https://github.com/{m.group(1)}" if m else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def build_law(repo: Path, number: int, commits: list[RawCommit], single: bool) -> dict:
    """The viewer's data for one law. ``single``: the repository holds only this law, so
    commit messages have no "<law> sayılı Kanun:" headers."""
    fname = f"{number}.md"
    out_commits: list[dict] = []
    versions: dict[str, list[dict]] = {}
    labels: dict[str, tuple[str, str]] = {}  # last label and title of each article
    tocs: list[dict] = []
    preambles: list[dict] = []
    status = {"content": [], "typography": [], "order_differs": False}
    state: LawFile | None = None
    name = ""
    for c in commits:
        sections = parse_sections(c.body)
        sec = sections.get(None if single else number)
        touches = fname in c.files
        if not touches and sec is None:
            continue
        if state is None and not touches:
            continue  # a message naming the law before its first text: nothing to show
        kind = commit_kind(c.subject, c.body)
        sec = sec or Section()
        i = len(out_commits)
        changed: list[str] = []
        if touches:
            new = parse_law(_git(repo, "show", f"{c.sha}:{fname}"))
            name = new.name or name
            old = state.articles if state else {}
            for aid, a in new.articles.items():
                if aid not in old or old[aid].version() != a.version():
                    versions.setdefault(aid, []).append({"c": i, **a.version()})
                    changed.append(aid)
                labels[aid] = (a.label, a.title)
            for aid in old:
                if aid not in new.articles:
                    versions[aid].append({"c": i, "absent": True})
                    changed.append(aid)
            if state is None or state.toc != new.toc:
                tocs.append({"c": i, "items": new.toc})
            if (state.preamble if state else []) != new.preamble:
                preambles.append({"c": i, "body": new.preamble})
            state = new
        if kind == "sync":
            status["content"] = sec.content
            status["typography"] = sec.typography
            status["order_differs"] = sec.order_differs
        out_commits.append({
            "sha": c.sha,
            "date": c.date.isoformat(),
            "kind": kind,
            "act": c.subject.partition(": ")[0],
            "subject": c.subject,
            "rg_date": _iso(sec.rg_date),
            "rg_number": sec.rg_number,
            "effective": _iso(sec.effective),
            "assumed": sec.assumed,
            "table": sec.table,
            "by": sec.by,
            "source": sec.source,
            "source_note": sec.source_note,
            "failed": sec.failed,
            "changed": changed,
            "named": subject_articles(c.subject, None if single else number),
        })
    if state is None:
        raise ValueError(f"{fname} is not in the repository")
    articles = {}
    for aid, vs in versions.items():
        label, title = labels[aid]
        articles[aid] = {
            "label": label,
            "title": title,
            "status": ("unverified" if aid in status["content"]
                       else "typography" if aid in status["typography"] else "verified"),
            "versions": vs,
        }
    return {
        "number": number,
        "name": name,
        "first": min(c["date"] for c in out_commits),
        "last": max(c["date"] for c in out_commits),
        "order_differs": status["order_differs"],
        "commits": out_commits,
        "toc": tocs,
        "preamble": preambles,
        "articles": articles,
    }


def build(repo: Path, out: Path, repo_url: str | None = None) -> dict:
    """Write ``index.json`` and ``<law>.json`` for every law file of ``repo`` into ``out``."""
    commits = read_commits(repo)
    numbers = sorted({int(f[:-3]) for c in commits for f in c.files
                      if re.fullmatch(r"\d+\.md", f)})
    if not numbers:
        raise ValueError(f"{repo}: no <law>.md files in the history")
    out.mkdir(parents=True, exist_ok=True)
    laws = []
    for n in numbers:
        data = build_law(repo, n, commits, single=len(numbers) == 1)
        _write(out / f"{n}.json", data)
        arts = data["articles"]
        present = [a for a in arts.values() if not a["versions"][-1].get("absent")]
        laws.append({
            "number": n,
            "name": data["name"],
            "first": data["first"],
            "last": data["last"],
            "commits": len(data["commits"]),
            "articles": len(present),
            "unverified": sum(a["status"] == "unverified" for a in arts.values()),
            "typography": sum(a["status"] == "typography" for a in arts.values()),
        })
    index = {
        "source": {"url": repo_url or _remote_url(repo), "head": commits[-1].sha},
        "laws": laws,
    }
    _write(out / "index.json", index)
    return index


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")


# -- reading the data ------------------------------------------------------------------------

def article_at(law: dict, art_id: str, day: date) -> tuple[dict | None, list[int]]:
    """The version of an article in force on ``day``, and the commits whose changes it may
    carry although they were not yet in force.

    The version is the one from the last commit, in publication order, whose yürürlük
    date is on or before ``day`` (None if there is none, or the article did not exist
    then). A commit is a replay step: its text includes every change published before it.
    So when an earlier-published change of the article takes effect after ``day`` (6327
    for GVK md. 94: published before 6353, in force 29/8/2012, after 6353's 12/7/2012), the
    version shown may already carry it; those commits come back as the second value.
    The viewer (``site/js/data.js``) does the same."""
    commits = law["commits"]
    versions = law["articles"][art_id]["versions"]
    best = None
    for k, v in enumerate(versions):
        if date.fromisoformat(commits[v["c"]]["date"]) <= day:
            best = k  # versions are in publication order
    if best is None:
        return None, []
    pending = [v["c"] for v in versions[:best]
               if date.fromisoformat(commits[v["c"]]["date"]) > day]
    v = versions[best]
    return (None if v.get("absent") else v), pending
