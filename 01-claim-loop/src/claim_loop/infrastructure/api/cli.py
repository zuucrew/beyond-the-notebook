"""claim-loop CLI.

Everything is a CLI at v0.1 because you need to run two reviewers at once and
watch them race. A browser tab hides exactly the concurrency this project is
about.
"""
import os
import socket
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ...application import extraction_service
from ...config import (
    ALWAYS_ESCALATE,
    CONFIDENCE_THRESHOLD,
    DATASET_DIR,
    LEASE_SECONDS,
    PROJECT_ROOT,
)
from ...domain.routing import MANDATORY_FIELDS, fields_needing_review
from ..db import claims_repository as repo, migrate

app = typer.Typer(add_completion=False, help="Human-in-the-loop claims processing.")
console = Console()


def _default_actor(prefix: str) -> str:
    return f"{prefix}-{socket.gethostname().split('.')[0]}-{os.getpid()}"


@app.command()
def migrate_up():
    """Apply pending migrations."""
    applied = migrate.migrate_up()
    if not applied:
        console.print("[dim]nothing to apply — schema is current[/dim]")
        return
    for version in applied:
        console.print(f"[green]applied[/green] {version}")


@app.command()
def submit(
    paths: list[Path] = typer.Argument(None, help="PDFs to submit. Defaults to all of dataset/."),
    client: str = typer.Option("metlife", help="Client the form belongs to."),
):
    """Enqueue claims. Submitting the same file twice creates one claim."""
    files = sorted(paths) if paths else sorted(DATASET_DIR.glob("*.pdf"))
    if not files:
        console.print("[red]no PDFs found[/red]")
        raise typer.Exit(1)

    created = duplicate = 0
    for path in files:
        # Relative to the project root, so the same claim resolves on the host
        # and inside a container. An absolute host path would not.
        resolved = path.resolve()
        try:
            uri = f"file://{resolved.relative_to(PROJECT_ROOT)}"
        except ValueError:
            uri = f"file://{resolved}"
        form_code = path.name.split("_")[0]
        claim_id = repo.submit(client, form_code, uri)
        if claim_id:
            created += 1
            console.print(f"[green]queued[/green]  {path.name}  [dim]{claim_id}[/dim]")
        else:
            duplicate += 1
            console.print(f"[yellow]already submitted[/yellow]  {path.name}")

    console.print(f"\n{created} queued, {duplicate} already present")


@app.command()
def work(
    once: bool = typer.Option(False, "--once", help="Drain and exit, instead of waiting."),
    worker_id: str = typer.Option(None, help="Defaults to host-pid."),
):
    """Run the extraction worker. Start several at once — they will not collide."""
    wid = worker_id or _default_actor("worker")
    console.print(f"[bold]{wid}[/bold] — {'draining' if once else 'waiting for work'}\n")
    colours = {
        "auto_approved": "green",
        "pending_review": "yellow",
        "incomplete": "magenta",
        "submitted": "dim",
        "extraction_failed": "red",
    }
    try:
        for result in extraction_service.run(wid, once=once):
            colour = colours.get(result["status"], "white")
            console.print(
                f"[{colour}]{result['status']:<18}[/{colour}] {result['id'][:8]}"
                + (f"  [red]{result['error']}[/red]" if result.get("error") else "")
            )
            for reason in result.get("reasons", [])[:3]:
                console.print(f"    [dim]{reason}[/dim]")
    except KeyboardInterrupt:
        console.print("\n[dim]stopped[/dim]")


@app.command()
def review(reviewer: str = typer.Option(None, help="Defaults to host-pid.")):
    """Claim the next review task and correct it."""
    rid = reviewer or _default_actor("reviewer")
    claim = repo.claim_next_for_review(rid)
    if claim is None:
        console.print("[dim]nothing waiting for review[/dim]")
        return

    extracted = claim["extracted"]
    flagged = fields_needing_review(extracted)

    console.print(f"\n[bold]{Path(claim['storage_uri']).name}[/bold]")
    console.print(f"[dim]{claim['id']}  ·  lease {LEASE_SECONDS}s  ·  reviewer {rid}[/dim]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("field")
    table.add_column("extracted value")
    table.add_column("conf", justify="right")
    table.add_column("why", style="dim")
    for key in flagged:
        field = extracted[key]
        why = "always escalated" if key in ALWAYS_ESCALATE else f"below {CONFIDENCE_THRESHOLD}"
        table.add_row(key, str(field["value"]), f"{field['confidence']:.2f}", why)
    console.print(table)

    console.print(
        "\n[dim]Enter = accept as-is · new value = correct it · [b]blank[/b] = "
        "field is empty on the form[/dim]\n"
    )

    events: list[dict] = []
    confirmed_blank_mandatory = False
    for key in flagged:
        old = extracted[key]["value"]
        answer = typer.prompt(f"  {key} [{old}]", default="", show_default=False)

        if answer == "":
            events.append({"field_key": key, "event_type": "confirmed", "old_value": old,
                           "new_value": old})
        elif answer.strip().lower() == "blank":
            extracted[key] = {"value": None, "confidence": 1.0, "source": "blank"}
            events.append({"field_key": key, "event_type": "confirmed_blank",
                           "old_value": old, "new_value": None})
            if key in MANDATORY_FIELDS:
                confirmed_blank_mandatory = True
        else:
            extracted[key] = {"value": answer, "confidence": 1.0, "source": "human"}
            events.append({"field_key": key, "event_type": "corrected",
                           "old_value": old, "new_value": answer})

    # A mandatory field the reviewer confirms is empty is not a review failure.
    # The information is not on the form, so it goes back to the claimant.
    status = "incomplete" if confirmed_blank_mandatory else "approved"
    repo.complete_review(claim["id"], extracted, events, rid, status)

    corrected = sum(1 for e in events if e["event_type"] == "corrected")
    console.print(f"\n[green]{status}[/green] — {corrected} corrected, {len(events)} reviewed")


@app.command()
def reap():
    """Return abandoned work to its repo. Run this on a schedule."""
    revived = repo.reap_expired()
    if not revived:
        console.print("[dim]no expired leases[/dim]")
        return
    for row in revived:
        console.print(f"[yellow]reclaimed[/yellow] {str(row['id'])[:8]} -> {row['status']}")


@app.command()
def status(stuck_after: str = typer.Option("1 hour", help="Age at which a claim counts as stuck.")):
    """Where every claim is, and whether anything is stuck."""
    counts = repo.status_counts()
    if not counts:
        console.print("[dim]no claims[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("status")
    table.add_column("claims", justify="right")
    for row in counts:
        table.add_row(row["status"], str(row["n"]))
    console.print(table)

    stuck = repo.stuck_claims(stuck_after)
    if stuck:
        console.print(f"\n[red]{len(stuck)} stuck (no movement in {stuck_after})[/red]")
        for row in stuck[:10]:
            console.print(f"  {str(row['id'])[:8]}  {row['status']}  attempt {row['attempt_count']}")
    else:
        console.print(f"\n[green]nothing stuck[/green] [dim](threshold {stuck_after})[/dim]")


@app.command()
def history(claim_id: str):
    """Every recorded event for one claim — the model's answer and the human's."""
    events = repo.field_history(claim_id)
    if not events:
        console.print("[dim]no events[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    for column in ("field", "event", "from", "to", "conf", "actor"):
        table.add_column(column)
    for e in events:
        table.add_row(
            e["field_key"], e["event_type"], str(e["old_value"] or ""),
            str(e["new_value"] or ""),
            f"{e['confidence']:.2f}" if e["confidence"] is not None else "",
            e["actor"],
        )
    console.print(table)


if __name__ == "__main__":
    app()
