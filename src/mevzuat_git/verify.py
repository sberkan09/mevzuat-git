"""Faz 3: replay the parsed amendments and compare the result with the consolidated text.

We have the Resmî Gazete texts of the amending acts from 2000 on, but not the 1961 text
of the law. So the replay works in two passes over the acts we have:

1. **Unwind.** Start from today's consolidated text and undo the operations from the
   newest to the oldest (``replay.unapply``). Before each undo the operation's effect is
   looked for in the text. What remains is the law as of ~2000, except for text that a
   later operation replaced wholesale and whose earlier wording is therefore unknown.
2. **Replay.** Apply the operations again from the oldest to the newest
   (``replay.apply``), then compare every touched article with the consolidated text.

An article *matches* when the replayed text equals the consolidated text after
normalisation (``compare.norm``). It is *unverified* when its replay depends on wording
we could not recover (an ibare deletion whose place is not marked, see ``Check.lossy``).
The metric is matches / (matches + mismatches), at article level.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from mevzuat_git import mevzuat_gov as mg
from mevzuat_git.amendments import OpsFile, UnparsedSentence
from mevzuat_git.compare import node_lines, strip_editorial
from mevzuat_git.fetch import Fetcher, NotFound
from mevzuat_git.model import AmendmentOp, Law, Level, OpType
from mevzuat_git.replay import (
    UNKNOWN,
    ReplayError,
    Superseded,
    apply_batch,
    resolve,
    unapply_batch,
)
from mevzuat_git.tree import build_tree

# -- replay and comparison -------------------------------------------------------------

@dataclass
class OpResult:
    act: str
    article: str
    op: AmendmentOp
    check: str = ""  # unwind check: ok / fail / superseded / lossy
    check_message: str = ""
    replay_error: str | None = None


@dataclass
class ArticleResult:
    id: str
    status: str  # match / mismatch / unverified
    detail: str = ""
    ops: list[OpResult] = field(default_factory=list)


@dataclass
class Report:
    ops: list[OpResult]
    articles: list[ArticleResult]
    sentences: int
    parsed_sentences: int
    unparsed: list[UnparsedSentence]

    @property
    def counts(self) -> Counter:
        return Counter(a.status for a in self.articles)

    @property
    def match_rate(self) -> float:
        c = self.counts
        denom = c["match"] + c["mismatch"]
        return c["match"] / denom if denom else 0.0


def articles_of(op: AmendmentOp) -> list[str]:
    if op.op is OpType.INSERT_NODE and op.kind is Level.MADDE:
        return [n.id for n in op.new_nodes if n.id]  # not the article it goes after
    if op.target.madde:
        return [op.target.madde]
    return [n.id for n in op.new_nodes if n.id]


def _has_unknown(law: Law, art_id: str) -> bool:
    art = law.article(art_id)
    return art is not None and any(n.text == UNKNOWN or n.title == UNKNOWN for n in art.walk())


def _first_diff(a: list[str], b: list[str]) -> str:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return f"line {i + 1}:\n  replay:       {x[:300]}\n  consolidated: {y[:300]}"
    return f"replay has {len(a)} lines, consolidated text {len(b)}"


def _not_undone(r: OpResult) -> bool:
    """The unwind could not undo ``r``, so the replay must not do it again. Inserted
    articles are removed even when they read differently (see ``replay``)."""
    return r.check == "fail" and not (r.op.op is OpType.INSERT_NODE and r.op.kind is Level.MADDE)


def batches(ops: list[OpResult]) -> list[list[OpResult]]:
    """Operations grouped in replay order. Ibare replacements in the same text by the same
    act article happen at once ("“sakat” ve “sakatlık” ibareleri sırasıyla “engelli” ve
    “engellilik”"): one by one, a replacement could take part of a longer ibare or
    rewrite what an earlier one wrote."""
    out: list[list[OpResult]] = []
    for r in ops:
        last = out[-1][-1] if out else None
        if last and r.op.op is OpType.REPLACE_PHRASE is last.op.op \
                and not r.op.paren and not last.op.paren \
                and (r.act, r.article, r.op.target, r.op.source_sentence) \
                == (last.act, last.article, last.op.target, last.op.source_sentence):
            out[-1].append(r)
        else:
            out.append([r])
    return out


def unwind(current: Law, groups: list[list[OpResult]]) -> Law:
    """The law before the operations: ``current`` with every batch undone, newest first.
    Sets each operation's check.

    mevzuat.gov.tr's own additions are taken out of the text first: they are not the
    law's words, and an act's ibare does not hold them. 7194/11 inserted "... ulaşım
    bedelinin 10 Türk lirasını aşmaması ..."; the consolidated text reads "... taşıma
    giderleri (Ek parantez içi hüküm:5/12/2019-7194/11 md.) (... 10 Türk lirasını (158
    TL) aşmaması ...". See ``compare.strip_editorial``."""
    state = current.model_copy(deep=True)
    for top in state.body:
        for n in top.walk():
            if n.text:
                n.text = strip_editorial(n.text)
    for b in reversed(groups):
        for r in b:
            # Footnote ops: their address, as it is at this point of the unwind.
            r.op = resolve(state, r.op)
        for r, chk in zip(b, unapply_batch(state, [r.op for r in b]), strict=True):
            r.check, r.check_message = chk.status, chk.message
    return state


def _whole_article(op: AmendmentOp) -> bool:
    t = op.target
    return (op.op is OpType.REPLACE_NODE and bool(t.madde) and not t.baslik
            and all(getattr(t, f) is None
                    for f in ("fikra", "bent", "alt_bent", "paragraf", "cumle")))


def mark_replaced(ops: list[OpResult]) -> None:
    """An operation on an article that a later act replaced as a whole acted on text that
    is gone: its effect cannot be in the consolidated text, and the replay need not do it
    (4842/10 on md. 89, before 5228/28 rewrote the article). Its failed check becomes
    "superseded"."""
    replaced: dict[str, OpResult] = {}  # article -> the earliest later replacement
    for r in reversed(ops):
        by = replaced.get(r.op.target.madde or "")
        # An inserted article's target is the article it goes after.
        article_insert = r.op.op is OpType.INSERT_NODE and r.op.kind is Level.MADDE
        if r.check == "fail" and by is not None and by.act != r.act and not article_insert:
            r.check = "superseded"
            r.check_message = f"article replaced by {by.act} md. {by.article}"
        if _whole_article(r.op) and r.check in ("ok", "superseded"):
            # Only a replacement found in the text: a failed one may be misparsed.
            replaced[r.op.target.madde or ""] = r


def replay_batch(law: Law, batch: list[OpResult]) -> None:
    """Apply one batch in place; errors are recorded on the operations."""
    live = [r for r in batch if r.check != "superseded" and not _not_undone(r)]
    if not live:
        return
    try:
        errors = apply_batch(law, [r.op for r in live])
    except Superseded:
        errors = ["target inside text replaced later"] * len(live)
    except ReplayError as exc:
        errors = [str(exc)] * len(live)
    for r, err in zip(live, errors, strict=True):
        r.replay_error = err


def op_results(opsfile: OpsFile) -> list[OpResult]:
    return [OpResult(act=a.act, article=am.article, op=op) for a, am, op in opsfile.ops()]


def run(current: Law, opsfile: OpsFile) -> Report:
    ops = op_results(opsfile)
    groups = batches(ops)
    replayed = unwind(current, groups)  # the baseline, replayed forward in place
    mark_replaced(ops)
    for b in groups:
        replay_batch(replayed, b)

    by_article: dict[str, list[OpResult]] = {}
    for r in ops:
        for a in articles_of(r.op):
            by_article.setdefault(a, []).append(r)
    articles: list[ArticleResult] = []
    order = {a.id: i for i, a in enumerate(current.articles())}
    for art_id in sorted(by_article, key=lambda a: order.get(a, len(order))):
        rs = by_article[art_id]
        cur, rep = current.article(art_id), replayed.article(art_id)
        res = ArticleResult(id=art_id, status="match", ops=rs)
        if cur is None:
            res.status, res.detail = "mismatch", "article not in the consolidated text"
        elif rep is None:
            res.status, res.detail = "mismatch", "article missing after replay"
        elif _has_unknown(replayed, art_id) or any(r.check == "lossy" for r in rs):
            res.status = "unverified"
            res.detail = "depends on wording that could not be recovered"
        else:
            a, b = node_lines(rep), node_lines(cur)
            if a != b:
                res.status, res.detail = "mismatch", _first_diff(a, b)
        errors = [r for r in rs if r.replay_error and r.check != "superseded"]
        failed = [r for r in rs if _not_undone(r)]
        if res.status == "match" and errors:
            res.status = "mismatch"
            res.detail = f"replay error: {errors[0].replay_error}"
        elif res.status != "mismatch" and failed:
            # The act's effect is not in the consolidated text: the comparison cannot
            # show that, since the replay skipped the operation.
            res.status = "mismatch"
            res.detail = f"not found in the consolidated text: {failed[0].check_message}"
        articles.append(res)

    sentences = sum(a.sentences for a in opsfile.acts)
    unparsed = [u for a in opsfile.acts for u in a.unparsed]
    return Report(ops=ops, articles=articles, sentences=sentences,
                  parsed_sentences=sentences - len(unparsed), unparsed=unparsed)


def current_tree(fetcher: Fetcher, law: int) -> Law:
    got = mg.fetch_text_html(fetcher, law)
    if got is None:
        raise NotFound(f"law {law} not on mevzuat.gov.tr")
    return build_tree(got[1], law)


# -- report ----------------------------------------------------------------------------

def render_report(rep: Report, law: int) -> str:
    c = rep.counts
    total_ops = len(rep.ops)
    checks = Counter(r.check for r in rep.ops)
    lines = [
        f"# {law} sayılı Kanun: replay raporu",
        "",
        "`mevzuat-git replay` çıktısıdır; elle düzenlemeyin. Yöntem: `src/mevzuat_git/verify.py`.",
        "",
        "## Özet",
        "",
        (f"- Hedef kanunu anan değişiklik cümlesi: {rep.sentences}; ayrıştırılan: "
         f"{rep.parsed_sentences} ({_pct(rep.parsed_sentences, rep.sentences)})"),
        f"- İşlem: {total_ops} (geri sarma kontrolü: "
        + ", ".join(f"{k} {v}" for k, v in sorted(checks.items())) + ")",
        (f"- Etkilenen madde: {len(rep.articles)}: eşleşen {c['match']}, farklı "
         f"{c['mismatch']}, doğrulanamayan {c['unverified']}"),
        (f"- **Madde düzeyinde eşleşme oranı: {rep.match_rate:.1%}** "
         f"({c['match']}/{c['match'] + c['mismatch']})"),
        "",
        "## Farklı maddeler",
        "",
    ]
    for a in rep.articles:
        if a.status != "mismatch":
            continue
        lines.append(f"### Madde {a.id}")
        lines.append("")
        lines.append("```")
        lines.append(a.detail)
        lines.append("```")
        lines.append("")
        for r in a.ops:
            flag = r.check if r.check != "ok" else ""
            msg = r.check_message or r.replay_error or ""
            lines.append(f"- {r.act} md. {r.article}: `{r.op.op.value}` {r.op.target} "
                         f"{flag} {msg}".rstrip())
        lines.append("")
    lines += ["## Ayrıştırılamayan cümleler", ""]
    for u in rep.unparsed:
        lines.append(f"- {u.act} md. {u.article} ({u.reason}): {u.sentence[:300]}")
    lines += ["", "## Doğrulanamayan maddeler", ""]
    for a in rep.articles:
        if a.status == "unverified":
            lines.append(f"- {a.id}")
    return "\n".join(lines) + "\n"


def _pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "-"
