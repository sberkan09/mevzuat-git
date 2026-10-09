from datetime import date
from pathlib import Path

import typer

from mevzuat_git.fetch import DEFAULT_CACHE_DIR, Fetcher

app = typer.Typer(help="Rebuild Turkish legislation history as git commits.")

PROCESSED_DIR = Path("data/processed")


@app.command()
def fetch(
    law: int = typer.Argument(..., help="Kanun numarası, ör. 193"),
    since: int = typer.Option(2000, help="Download RG texts of acts published from this year"),
    cache_dir: Path = typer.Option(DEFAULT_CACHE_DIR, help="Raw response cache"),
    out_dir: Path = typer.Option(PROCESSED_DIR, help="Where <law>_amendments.json goes"),
    min_interval: float = typer.Option(1.0, help="Seconds between requests to one host"),
    offline: bool = typer.Option(False, help="Use only the cache, never the network"),
) -> None:
    """Fetch consolidated text and amendment list for a law (Faz 0)."""
    from mevzuat_git.amendment_list import act_date, build_list

    def progress(i: int, n: int, act) -> None:
        typer.echo(f"[{i + 1}/{n}] {act.kind} {act.number}", err=True)

    with Fetcher(cache_dir=cache_dir, min_interval=min_interval, offline=offline) as f:
        result = build_list(f, law, since=date(since, 1, 1), progress=progress)
        requests = f.network_requests

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{law}_amendments.json"
    out.write_text(result.model_dump_json(indent=2, exclude_none=True) + "\n")

    recent = [a for a in result.acts if (d := act_date(a)) and d.year >= since]
    with_text = [a for a in recent if a.rg and a.rg.text_url]
    undated = [a for a in result.acts if act_date(a) is None]
    typer.echo(f"{out}: {len(result.acts)} acts; {len(recent)} dated {since} or later, "
               f"{len(with_text)} of them with RG text cached; {requests} network requests")
    for a in recent:
        if a.kind != "aym" and not (a.rg and a.rg.text_url):
            typer.echo(f"  no RG text: {a.kind} {a.number} ({'; '.join(a.notes)})")
    if undated:
        typer.echo("  undated (only in the yürürlük table, no own page): "
                   + ", ".join(a.number for a in undated))


@app.command()
def parse(
    law: int = typer.Argument(..., help="Kanun numarası, ör. 193"),
    cache_dir: Path = typer.Option(DEFAULT_CACHE_DIR, help="Raw response cache"),
    out_dir: Path = typer.Option(PROCESSED_DIR, help="Where <law>.json and <law>.md go"),
    offline: bool = typer.Option(False, help="Use only the cache, never the network"),
) -> None:
    """Parse the consolidated text into a tree; write JSON and Markdown (Faz 1)."""
    from mevzuat_git import mevzuat_gov as mg
    from mevzuat_git.render import to_markdown
    from mevzuat_git.tree import build_tree

    with Fetcher(cache_dir=cache_dir, offline=offline) as f:
        got = mg.fetch_text_html(f, law)
    if got is None:
        raise typer.BadParameter(f"law {law} not on mevzuat.gov.tr")
    tree = build_tree(got[1], law)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{law}.json").write_text(tree.model_dump_json(indent=1, exclude_defaults=True))
    (out_dir / f"{law}.md").write_text(to_markdown(tree))
    n = sum(1 for _ in tree.articles())
    typer.echo(f"{out_dir}/{law}.md: {n} articles")


@app.command()
def amendments(
    law: int = typer.Argument(..., help="Kanun numarası, ör. 193"),
    cache_dir: Path = typer.Option(DEFAULT_CACHE_DIR, help="Raw response cache"),
    out_dir: Path = typer.Option(PROCESSED_DIR, help="Where <law>_ops.json goes"),
    offline: bool = typer.Option(True, help="Use only the cache (run `fetch` first)"),
) -> None:
    """Parse the amending acts' RG texts into operations (Faz 2)."""
    from mevzuat_git.amendments import load_list, parse_all

    alist = load_list(out_dir / f"{law}_amendments.json")
    with Fetcher(cache_dir=cache_dir, offline=offline) as f:
        ops = parse_all(f, alist)
    out = out_dir / f"{law}_ops.json"
    out.write_text(ops.model_dump_json(indent=1, exclude_defaults=True) + "\n")
    sentences = sum(a.sentences for a in ops.acts)
    unparsed = sum(len(a.unparsed) for a in ops.acts)
    n_ops = len(ops.ops())
    typer.echo(f"{out}: {len(ops.acts)} acts, {sentences} sentences naming law {law}, "
               f"{sentences - unparsed} parsed into {n_ops} operations")
    for a in ops.acts:
        if a.error:
            typer.echo(f"  {a.act}: {a.error}")


@app.command()
def replay(
    law: int = typer.Argument(..., help="Kanun numarası, ör. 193"),
    cache_dir: Path = typer.Option(DEFAULT_CACHE_DIR, help="Raw response cache"),
    out_dir: Path = typer.Option(PROCESSED_DIR, help="Where <law>_replay.md goes"),
    offline: bool = typer.Option(True, help="Use only the cache (run `fetch` first)"),
) -> None:
    """Replay parsed amendments and compare with the consolidated text (Faz 3)."""
    from mevzuat_git.verify import OpsFile, current_tree, render_report, run

    ops = OpsFile.model_validate_json((out_dir / f"{law}_ops.json").read_text())
    with Fetcher(cache_dir=cache_dir, offline=offline) as f:
        current = current_tree(f, law)
    rep = run(current, ops)
    out = out_dir / f"{law}_replay.md"
    out.write_text(render_report(rep, law))
    c = rep.counts
    typer.echo(f"{out}: article match rate {rep.match_rate:.1%} "
               f"({c['match']} match, {c['mismatch']} mismatch, {c['unverified']} unverified)")


@app.command()
def history(
    law: int = typer.Argument(..., help="Kanun numarası, ör. 193"),
    cache_dir: Path = typer.Option(DEFAULT_CACHE_DIR, help="Raw response cache"),
    data_dir: Path = typer.Option(PROCESSED_DIR, help="Where <law>_ops.json is"),
    out: Path = typer.Option(None, help="New git repository [default: data/history/<law>]"),
    offline: bool = typer.Option(True, help="Use only the cache (run `fetch` first)"),
) -> None:
    """Write the replayed amendments as a git history, dated by yürürlük (Faz 4)."""
    from mevzuat_git.amendments import OpsFile, load_list
    from mevzuat_git.history import build
    from mevzuat_git.verify import current_tree

    ops = OpsFile.model_validate_json((data_dir / f"{law}_ops.json").read_text())
    alist = load_list(data_dir / f"{law}_amendments.json")
    with Fetcher(cache_dir=cache_dir, offline=offline) as f:
        current = current_tree(f, law)
    out = out or Path("data/history") / str(law)
    commits = build(current, ops, alist, out)
    typer.echo(f"{out}: {len(commits)} commits, {commits[0].date} .. "
               f"{max(c.date for c in commits)}")


if __name__ == "__main__":
    app()
