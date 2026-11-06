"""A small history repository for the viewer's tests, from ``fixtures/site_history.json``.

The fixture is a slice of sberkan09/mevzuat-tarihce: commit messages verbatim, and for a
few articles (GVK md. 1, 17, 38, 40, 41; VUK md. 359; KDV md. 1) their text at every commit
that changed it. The law files are rebuilt from each law's skeleton (headings and article
order) and the articles' current text.

    python tests/site_fixture.py OUT                 # OUT/repo (git), OUT/www (site/ + data/)
    python tests/site_fixture.py --extract TARIHCE   # rewrite the fixture from a clone
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "site_history.json"

# The articles kept, and why: GVK 1 never changes; 17 differs from the official text only
# in typography; 38 is named by 4684 without a change; 40 is unverified; 41 is verified,
# with seven versions. VUK 359 has a change published before, and in force after, the next
# one (7423, then the AYM decision). KDV 1: a second law in the same commits.
KEEP = {"193": ["1", "17", "38", "40", "41"], "213": ["359"], "3065": ["1"]}


def make_repo(out: Path) -> Path:
    from mevzuat_git.history import Commit, GitRepo

    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    repo = GitRepo(out)
    repo.init()
    texts: dict[str, dict[str, str]] = {}
    for c in spec["commits"]:
        files = {}
        for law, arts in c["articles"].items():
            cur = texts.setdefault(law, {})
            for k, md in arts.items():
                if md is None:
                    cur.pop(k, None)
                else:
                    cur[k] = md
            meta = spec["laws"][law]
            parts = [meta["name"]] + [cur.get(s, s) for s in meta["skeleton"]
                                      if s in cur or s.startswith("#")]
            files[f"{law}.md"] = "\n\n".join(parts) + "\n"
        subject, _, body = c["message"].partition("\n\n")
        repo.commit(Commit(date.fromisoformat(c["date"]), subject,
                           body.split("\n") if body else []), files)
    return out


def make_site(out: Path) -> Path:
    """OUT/repo and OUT/www: the viewer with the fixture's data, ready to serve."""
    from mevzuat_git.site import build

    if out.exists():
        shutil.rmtree(out)
    repo = make_repo(out / "repo")
    www = out / "www"
    shutil.copytree(ROOT / "site", www, ignore=shutil.ignore_patterns("data"))
    build(repo, www / "data", "https://github.com/sberkan09/mevzuat-tarihce")
    return www


def extract(tarihce: Path) -> dict:
    """The fixture from a clone of mevzuat-tarihce: every commit that changes a kept
    article, the laws' first commits, the sync commit and 4684 (no change)."""
    from mevzuat_git import mevzuat_gov as mg
    from mevzuat_git.site import _git, read_commits

    def split(text: str) -> tuple[str, list[list]]:
        blocks = text.strip("\n").split("\n\n")
        items: list[list] = []  # [kind, key, markdown]: "h" heading, "a" article
        for b in blocks[1:]:
            m = re.match(r"^(#{2,4}) (.*)$", b)
            if m and "\n" not in b:
                if len(m.group(1)) == 4:
                    a = mg.ARTICLE_RE.match(m.group(2))
                    items.append(["a", mg.article_id(a.group("prefix"), a.group("num")), b])
                else:
                    items.append(["h", len(m.group(1)), b])
            elif items:
                items[-1][2] += "\n\n" + b
        return blocks[0], items

    commits = read_commits(tarihce)
    state: dict[str, dict[str, str]] = {}
    laws: dict[str, dict] = {}
    out: list[dict] = []
    for c in commits:
        arts: dict[str, dict] = {}
        for f in c.files:
            law = f[:-3]
            if law not in KEEP:
                continue
            name, items = split(_git(tarihce, "show", f"{c.sha}:{f}"))
            cur = {k: md for kind, k, md in items if kind == "a" and k in KEEP[law]}
            skeleton: list[str] = []
            heads: dict[int, str] = {}
            for kind, k, md in items:
                if kind == "h":
                    heads = {lv: v for lv, v in heads.items() if lv < k} | {k: md}
                elif k in KEEP[law]:
                    skeleton += [heads[lv] for lv in sorted(heads) if heads[lv] not in skeleton]
                    skeleton.append(k)
            laws[law] = {"name": name, "skeleton": skeleton}
            old = state.get(law, {})
            changed = {k: v for k, v in cur.items() if old.get(k) != v}
            changed |= {k: None for k in old if k not in cur}
            if changed or law not in state:
                arts[law] = changed
            state[law] = cur
        keep = arts or "eşitleme" in c.subject or c.subject.startswith("4684 ")
        if keep:
            out.append({"date": c.date.isoformat(),
                        "message": c.subject + ("\n\n" + c.body if c.body else ""),
                        "articles": arts})
    return {"source": f"sberkan09/mevzuat-tarihce @ {commits[-1].sha}", "laws": laws,
            "commits": out}


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    if sys.argv[1] == "--extract":
        FIXTURE.write_text(json.dumps(extract(Path(sys.argv[2])), ensure_ascii=False, indent=1)
                           + "\n", encoding="utf-8")
        print(FIXTURE)
    else:
        print(make_site(Path(sys.argv[1])))
