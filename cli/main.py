from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import httpx
import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(name="scanme", help="CLI for the scanme document archive")
console = Console()

SCANME_URL = os.getenv("SCANME_URL", "http://localhost:8000")
_state: dict[str, str] = {"url": SCANME_URL}


@app.callback()
def _main(
    url: str = typer.Option(
        "http://localhost:8000", envvar="SCANME_URL", help="Server base URL"
    ),
) -> None:
    _state["url"] = url.rstrip("/")


def _client() -> httpx.Client:
    return httpx.Client(base_url=_state["url"], timeout=30)


@app.command()
def add(
    files: list[Path] = typer.Argument(..., help="Files to upload"),
    no_wait: bool = typer.Option(
        False, "--no-wait", help="Fire and forget; prints job_id"
    ),
) -> None:
    """Upload one or more files to the archive."""
    for f in files:
        if not f.exists():
            typer.echo(f"File not found: {f}", err=True)
            raise typer.Exit(1)

    with _client() as client:
        try:
            upload_files = [
                ("files", (f.name, f.read_bytes(), "application/octet-stream"))
                for f in files
            ]
            resp = client.post("/api/upload", files=upload_files)
            resp.raise_for_status()
        except httpx.ConnectError:
            typer.echo(f"Cannot connect to server at {_state['url']}", err=True)
            raise typer.Exit(1)
        except httpx.HTTPStatusError as e:
            typer.echo(f"Upload failed: {e.response.text}", err=True)
            raise typer.Exit(1)

        data = resp.json()
        job_id = data["job_id"]
        original_filename = data["original_filename"]

        if no_wait:
            typer.echo(job_id)
            return

        with console.status(
            f"[bold green]Processing {original_filename}...[/bold green]"
        ):
            while True:
                try:
                    poll = client.get(f"/api/jobs/{job_id}")
                    poll.raise_for_status()
                    job = poll.json()
                except httpx.HTTPStatusError as e:
                    typer.echo(f"Job poll failed: {e}", err=True)
                    raise typer.Exit(1)

                if job["status"] == "done":
                    break
                elif job["status"] == "error":
                    typer.echo(f"Processing error: {job['error']}", err=True)
                    raise typer.Exit(1)
                time.sleep(2)

    lines = [f"[bold]{job['filename']}[/bold]"]
    if job.get("short_code"):
        lines.append(f"[dim]code: {job['short_code']}[/dim]")
    rprint(Panel("\n".join(lines), title="[green]Uploaded[/green]", expand=False))


@app.command()
def search(
    query: Optional[str] = typer.Argument(None, help="Search query"),
    date: Optional[str] = typer.Option(None, "--date", help="Month filter YYYY-MM"),
    top: int = typer.Option(10, "--top", help="Max results"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Search the document archive."""
    params: dict[str, str | int] = {"limit": top}
    if query:
        params["q"] = query
    if date:
        params["date"] = date

    with _client() as client:
        try:
            resp = client.get("/api/documents", params=params)
            resp.raise_for_status()
        except httpx.ConnectError:
            typer.echo(f"Cannot connect to server at {_state['url']}", err=True)
            raise typer.Exit(1)
        except httpx.HTTPStatusError as e:
            typer.echo(f"Search failed: {e.response.text}", err=True)
            raise typer.Exit(1)

    data = resp.json()

    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return

    docs = data["documents"]
    if not docs:
        typer.echo("No documents found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("code", style="cyan", no_wrap=True)
    table.add_column("date")
    table.add_column("tags")
    table.add_column("filename")
    table.add_column("size", justify="right")
    table.add_column("due", style="red")
    table.add_column("paid")

    for doc in docs:
        table.add_row(
            doc.get("short_code", ""),
            doc.get("date", ""),
            ", ".join((f"[on gray19]{tag}[/]" for tag in doc.get("tags", []))),
            doc.get("original_filename", ""),
            doc.get("size_display", ""),
            doc.get("due_status") or "",
            "yes" if doc.get("is_paid") else "",
        )

    console.print(table)
    if data.get("has_more"):
        typer.echo("  ... and more (use --top to see more)")


@app.command()
def edit(
    short_code: str = typer.Argument(..., help="Document short code"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags"),
    date: Optional[str] = typer.Option(None, "--date", help="Date YYYY-MM-DD"),
    due_date: Optional[str] = typer.Option(
        None, "--due-date", help="Due date YYYY-MM-DD, or 'none' to clear"
    ),
    filename: Optional[str] = typer.Option(
        None, "--filename", help="Original filename"
    ),
    paid: Optional[bool] = typer.Option(
        None, "--paid/--no-paid", help="Mark paid/unpaid"
    ),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Edit document metadata by short code."""
    with _client() as client:
        try:
            resp = client.get(f"/api/documents/{short_code}")
            resp.raise_for_status()
        except httpx.ConnectError:
            typer.echo(f"Cannot connect to server at {_state['url']}", err=True)
            raise typer.Exit(1)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                typer.echo(f"Document not found: {short_code}", err=True)
            else:
                typer.echo(f"Error: {e.response.text}", err=True)
            raise typer.Exit(1)

        payload: dict[str, str | bool] = {}
        if tags is not None:
            payload["tags"] = tags
        if date is not None:
            payload["date"] = date
        if due_date is not None:
            payload["due_date"] = "" if due_date.lower() == "none" else due_date
        if filename is not None:
            payload["original_filename"] = filename
        if paid is not None:
            payload["paid"] = paid

        if not payload:
            typer.echo(
                "No fields to update. Use --tags, --date, --due-date, --filename, --paid/--no-paid",
                err=True,
            )
            raise typer.Exit(1)

        try:
            resp = client.post(f"/api/documents/{short_code}", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            typer.echo(f"Edit failed: {e.response.text}", err=True)
            raise typer.Exit(1)

    doc = resp.json()

    if as_json:
        typer.echo(json.dumps(doc, indent=2))
        return

    table = Table(show_header=False, box=None)
    table.add_column("field", style="bold")
    table.add_column("value")
    for key, val in [
        ("short_code", doc.get("short_code")),
        ("date", doc.get("date")),
        ("tags", ", ".join(doc.get("tags", []))),
        ("filename", doc.get("original_filename")),
        ("due_date", doc.get("due_date") or ""),
        ("paid", "yes" if doc.get("is_paid") else "no"),
    ]:
        table.add_row(key, str(val) if val else "")
    console.print(table)


if __name__ == "__main__":
    app()
