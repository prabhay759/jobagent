"""
JobAgent CLI
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from jobagent.logging_config import setup_logging

console = Console()


@click.group()
@click.option("--config", default="config/config.yaml", help="Path to config.yaml")
@click.option("--profile", default="config/profile.yaml", help="Path to profile.yaml")
@click.option("--log-level", default="INFO", help="Logging level")
@click.pass_context
def main(ctx: click.Context, config: str, profile: str, log_level: str) -> None:
    """🤖 JobAgent — AI-powered job application agent."""
    setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["profile"] = profile


# ─── Setup ────────────────────────────────────────────────────

@main.command()
def setup() -> None:
    """Interactive first-time setup wizard."""
    import shutil

    console.print("\n[bold cyan]🤖 JobAgent Setup Wizard[/bold cyan]\n")

    for src, dst in [
        ("config/config.example.yaml", "config/config.yaml"),
        ("config/profile.example.yaml", "config/profile.yaml"),
    ]:
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if not dst_path.exists():
            shutil.copy(src, dst_path)
            console.print(f"[green]✓[/green] Created [bold]{dst}[/bold] from template")
        else:
            console.print(f"[yellow]→[/yellow] {dst} already exists")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [cyan]config/config.yaml[/cyan] — add your API keys & search criteria")
    console.print("  2. Edit [cyan]config/profile.yaml[/cyan] — fill in your professional profile")
    console.print("  3. Run [cyan]jobagent scan[/cyan] to start the agent")
    console.print("  4. Run [cyan]jobagent dashboard[/cyan] to open the web UI\n")


# ─── Scan ─────────────────────────────────────────────────────

@main.command()
@click.pass_context
def scan(ctx: click.Context) -> None:
    """Scan LinkedIn and run the full application pipeline."""
    from jobagent.pipeline import Pipeline
    from jobagent.settings import load_settings

    settings = load_settings(ctx.obj["config"])
    with open(ctx.obj["profile"]) as f:
        profile = yaml.safe_load(f)

    pipeline = Pipeline(settings, profile)
    console.print("[bold cyan]🔍 Starting scan…[/bold cyan]")
    asyncio.run(pipeline.run())
    console.print(f"\n[cyan]API usage:[/cyan] {pipeline.ai.usage.summary()}")


# ─── Dashboard ────────────────────────────────────────────────

@main.command()
@click.pass_context
def dashboard(ctx: click.Context) -> None:
    """Start the web dashboard."""
    from jobagent.dashboard.server import run_server

    run_server(ctx.obj["config"], ctx.obj["profile"])


# ─── Apply (single URL) ───────────────────────────────────────

@main.command()
@click.argument("url")
@click.pass_context
def apply(ctx: click.Context, url: str) -> None:
    """Process a single job URL through the full pipeline."""
    from jobagent.pipeline import Pipeline
    from jobagent.settings import load_settings

    settings = load_settings(ctx.obj["config"])
    with open(ctx.obj["profile"]) as f:
        profile = yaml.safe_load(f)

    pipeline = Pipeline(settings, profile)

    async def _run():
        job = await pipeline.scanner.get_details(url)
        console.print(f"[bold]{job.get('title')}[/bold] @ {job.get('company')}")
        pipeline.tracker.upsert_job(job)
        await pipeline.process_job(job)

    asyncio.run(_run())


# ─── Chat ─────────────────────────────────────────────────────

@main.command()
@click.argument("job_id")
@click.pass_context
def chat(ctx: click.Context, job_id: str) -> None:
    """Interactive chat about a specific job."""
    from jobagent.pipeline import Pipeline
    from jobagent.settings import load_settings

    settings = load_settings(ctx.obj["config"])
    with open(ctx.obj["profile"]) as f:
        profile = yaml.safe_load(f)

    pipeline = Pipeline(settings, profile)
    job = pipeline.tracker.get_job(job_id)
    if not job:
        console.print(f"[red]Job {job_id!r} not found.[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]💬 Chatting about:[/bold cyan] {job['title']} @ {job['company']}")
    console.print("[dim]Type 'exit' to quit.[/dim]\n")

    while True:
        try:
            msg = console.input("[bold]You:[/bold] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not msg or msg.lower() in ("exit", "quit"):
            break
        response = pipeline.chat(job_id, msg)
        console.print(f"[cyan]Agent:[/cyan] {response}\n")


# ─── Stats ────────────────────────────────────────────────────

@main.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show pipeline statistics."""
    from jobagent.db.tracker import JobTracker
    from jobagent.settings import load_settings

    settings = load_settings(ctx.obj["config"])
    tracker = JobTracker(settings.database.path)
    data = tracker.get_stats()

    table = Table(title="📊 JobAgent Stats", box=box.ROUNDED)
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right", style="bold")

    status_labels = {
        "total": "Total jobs", "discovered": "Discovered", "analyzed": "Analyzed",
        "pending_approval": "Pending approval", "ready_to_apply": "Ready to apply",
        "applied": "Applied", "interviewing": "Interviewing",
        "offer": "Offer 🎉", "rejected": "Rejected", "skipped": "Skipped",
        "apply_failed": "Apply failed", "easy_apply_count": "Easy Apply jobs",
        "avg_score": "Avg. match score",
    }
    for key, label in status_labels.items():
        table.add_row(label, str(data.get(key, 0)))

    console.print(table)


if __name__ == "__main__":
    main()
