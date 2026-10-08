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
def replay(law: int) -> None:
    """Apply parsed amendments in order and diff against consolidated text (Faz 3)."""
    raise NotImplementedError("Faz 3: see docs/ROADMAP.md")


if __name__ == "__main__":
    app()
