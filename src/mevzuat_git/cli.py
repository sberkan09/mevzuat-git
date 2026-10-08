import typer

app = typer.Typer(help="Rebuild Turkish legislation history as git commits.")


@app.command()
def fetch(law: int = typer.Argument(..., help="Kanun numarası, ör. 193")) -> None:
    """Fetch consolidated text and amendment list for a law (Faz 0)."""
    raise NotImplementedError("Faz 0: see docs/ROADMAP.md")


@app.command()
def replay(law: int) -> None:
    """Apply parsed amendments in order and diff against consolidated text (Faz 3)."""
    raise NotImplementedError("Faz 3: see docs/ROADMAP.md")


if __name__ == "__main__":
    app()
