"""Command-line interface for The Midnight Archive.

Run ``python -m midnight_archive --help`` for the command list. Global options
(``--root``, ``--verbose``) must come before the command.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from midnight_archive import __version__
from midnight_archive.analytics import latest_stats, record_stats
from midnight_archive.config import Settings
from midnight_archive.database import STATUSES, Database
from midnight_archive.doctor import all_required_passed, check_environment
from midnight_archive.errors import NotFoundError, PipelineError, TmaError, ValidationRejected
from midnight_archive.logging_utils import configure_logging, get_logger
from midnight_archive.models import (
    NarrationMetadata,
    QualityReport,
    RenderMetadata,
    Script,
    Storyboard,
    TechnicalReport,
)
from midnight_archive.pipeline import Pipeline, StageResult
from midnight_archive.quality_check import QC_MAXIMA, evaluate, rubric_rows
from midnight_archive.schemas import export_schemas
from midnight_archive.script_editor import Issue, metrics, preflight
from midnight_archive.story_generator import create_concept_video, generate_ideas, select_idea
from midnight_archive.storyboard import metrics as storyboard_metrics
from midnight_archive.storyboard import summary as storyboard_summary
from midnight_archive.utils import read_json

Handler = Callable[[argparse.Namespace, Settings, Database, Console], int]
COMMANDS: dict[str, Handler] = {}

CATEGORY_LABELS = {
    "psychological_horror": "horror",
    "mystery": "mystery",
    "mind_bending": "mind-bending",
}


def category_label(value: str) -> str:
    return CATEGORY_LABELS.get(value, value)


def short_time(value: object) -> str:
    """Compact UTC timestamp for tables: ``2026-11-14 18:30``."""

    text = str(value or "-")
    return text.replace("T", " ")[:16]


def command(name: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        COMMANDS[name] = handler
        return handler

    return register


# --------------------------------------------------------------------------- helpers
def _resolve(settings: Settings, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else settings.root / path


def _load_payload(settings: Settings, raw: str) -> dict[str, Any]:
    path = _resolve(settings, raw)
    if not path.is_file():
        raise NotFoundError(f"File not found: {path}")
    try:
        payload = read_json(path)
    except json.JSONDecodeError as exc:
        raise ValidationRejected(f"{path.name} is not valid JSON: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValidationRejected(f"{path.name} is not UTF-8 text: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationRejected(f"{path.name} must contain a JSON object")
    return payload


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _print_issues(console: Console, issues: list[Issue]) -> None:
    for issue in issues:
        colour = {"error": "red", "warning": "yellow"}.get(issue.level, "cyan")
        console.print(f"  [{colour}]{issue.level}[/{colour}] {issue.code}: {issue.message}")


def _print_video_banner(console: Console, video: sqlite3.Row) -> None:
    console.print(
        f"[bold]{video['id']}[/bold]  {video['title']}\n"
        f"status: [bold cyan]{video['status']}[/bold cyan]   category: {video['category']}"
    )


def _script_from_video(video: sqlite3.Row) -> Script:
    if not video["script_json"]:
        raise PipelineError(f"{video['id']} has no script yet. Import one with import-script.")
    return Script.model_validate(json.loads(str(video["script_json"])))


def _storyboard_from_video(video: sqlite3.Row) -> Storyboard:
    if not video["storyboard_json"]:
        raise PipelineError(
            f"{video['id']} has no storyboard yet. Import one with import-storyboard."
        )
    return Storyboard.model_validate(json.loads(str(video["storyboard_json"])))


# --------------------------------------------------------------------------- commands
@command("doctor")
def cmd_doctor(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    checks = check_environment(settings)
    table = Table(title=f"{settings.name} - environment", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_column("Detail", overflow="fold")
    for check in checks:
        if check.ok:
            result = "[green]OK[/green]"
        elif check.required:
            result = "[red]MISSING[/red]"
        else:
            result = "[yellow]WARN[/yellow]"
        table.add_row(check.name, result, check.detail)
    console.print(table)
    if all_required_passed(checks):
        console.print("[green]Environment ready for production.[/green]")
        return 0
    console.print("[red]Required components are missing. Fix the rows marked MISSING.[/red]")
    return 1


@command("init")
def cmd_init(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    created = settings.ensure_layout()
    schemas = export_schemas(settings)
    console.print(f"Project root: [bold]{settings.root}[/bold]")
    console.print(f"Database: {settings.relative(settings.db_path)}")
    console.print(f"Created {len(created)} folder(s); database schema is ready.")
    console.print(f"Exported {len(schemas)} JSON schema(s) to schemas/")
    return 0


@command("ideas")
def cmd_ideas(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    if args.list:
        rows = db.list_ideas(limit=args.limit)
        if args.json_output:
            _emit_json([dict(row) for row in rows])
            return 0
        if not rows:
            console.print("No ideas stored yet. Run: python -m midnight_archive ideas")
            return 0
        table = Table(title="Idea bank (best first)")
        table.add_column("ID", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Category")
        table.add_column("Title", overflow="fold")
        table.add_column("Hook", overflow="fold")
        for row in rows:
            table.add_row(
                str(row["id"]),
                f"{float(row['total']):.1f}",
                category_label(str(row["category"])),
                str(row["title"]),
                str(row["hook"]),
            )
        console.print(table)
        return 0

    result = generate_ideas(
        settings,
        db,
        count=args.count,
        label=args.label,
        seed=args.seed,
        provider_name=args.provider,
        allow_paid=args.allow_paid_api,
    )
    if args.json_output:
        _emit_json(
            {
                "session_id": result.session_id,
                "file": settings.relative(result.file),
                "stored": [idea.model_dump(mode="json") for idea in result.stored],
                "skipped_duplicates": result.skipped_duplicates,
            }
        )
        return 0

    console.print(
        f"[green]Generated {len(result.stored)} ideas[/green] in session {result.session_id}"
    )
    console.print(f"Saved to {settings.relative(result.file)}")
    if result.skipped_duplicates:
        console.print(f"Skipped {result.skipped_duplicates} duplicate/blank candidate(s).")

    table = Table(title="New ideas, ranked")
    table.add_column("ID", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Category")
    table.add_column("Title", overflow="fold")
    table.add_column("Hook", overflow="fold")
    for idea in sorted(result.stored, key=lambda item: item.total, reverse=True):
        table.add_row(
            idea.id, f"{idea.total:.1f}", category_label(idea.category), idea.title, idea.hook
        )
    console.print(table)
    best = max(result.stored, key=lambda item: item.total)
    console.print(
        f"Next: [bold]python -m midnight_archive select --idea {best.id}[/bold]"
    )
    return 0


@command("select")
def cmd_select(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    if args.idea:
        idea = db.get_idea(args.idea)
        minimum = float(settings.get("ideas.min_total_score", 55))
        if float(idea["total"]) < minimum and not args.force:
            raise PipelineError(
                f"{args.idea} scored {float(idea['total']):.1f}/100, below the {minimum:.0f} "
                "selection floor. Use --force if you still want it."
            )
        video = select_idea(db, args.idea, title_override=args.title)
    else:
        video = db.require_video(args.video)
        if video["status"] != "IDEA":
            raise PipelineError(
                f"{video['id']} is {video['status']}; only an IDEA video can be selected."
            )
        video = db.transition(
            video["id"], "SELECTED", actor="human", reason="manual selection"
        )
    _print_video_banner(console, video)
    console.print(
        "Next: author the script JSON, then run "
        f"[bold]import-script --video {video['id']} --file <script.json>[/bold]"
    )
    return 0


@command("new")
def cmd_new(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    video = create_concept_video(
        db,
        title=args.title,
        category=args.category,
        premise=args.premise,
    )
    if args.select:
        video = db.transition(video["id"], "SELECTED", actor="human", reason="created selected")
    _print_video_banner(console, video)
    if video["status"] == "IDEA":
        console.print(f"Next: [bold]python -m midnight_archive select --video {video['id']}[/bold]")
    return 0


@command("import-script")
def cmd_import_script(
    args: argparse.Namespace, settings: Settings, db: Database, console: Console
) -> int:
    payload = _load_payload(settings, args.file)
    result = Pipeline(settings, db).import_script(args.video, payload)
    _report_import(console, settings, result, "SCRIPTED")
    if result.path:
        script = _script_from_video(result.video)
        data = metrics(script, settings)
        console.print(
            f"Script: {data.word_count} words, ~{data.estimated_duration:.1f}s, "
            f"{data.beat_count} beats."
        )
        console.print(
            f"Next: [bold]import-storyboard --video {args.video} --file <storyboard.json>[/bold]"
        )
    if result.warnings:
        console.print("[yellow]Editorial warnings:[/yellow]")
        _print_issues(console, result.warnings)
    return 0


@command("import-storyboard")
def cmd_import_storyboard(
    args: argparse.Namespace, settings: Settings, db: Database, console: Console
) -> int:
    payload = _load_payload(settings, args.file)
    result = Pipeline(settings, db).import_storyboard(args.video, payload)
    _report_import(console, settings, result, "STORYBOARD_READY")
    if result.path:
        video = result.video
        storyboard = _storyboard_from_video(video)
        script = _script_from_video(video)
        data = storyboard_metrics(storyboard, script, settings)
        console.print(
            f"Storyboard: {data.scene_count} scenes, {data.total_duration:.1f}s "
            f"(script estimate {data.estimated_script_duration:.1f}s)."
        )
    if result.warnings:
        console.print("[yellow]Storyboard warnings:[/yellow]")
        _print_issues(console, result.warnings)
    return 0


def _report_import(console: Console, settings: Settings, result: StageResult, target: str) -> None:
    if result.replay:
        console.print("[yellow]Idempotent replay:[/yellow] " + "; ".join(result.notes))
        return
    console.print(f"[green]{result.video['id']} -> {target}[/green]")
    if result.path:
        console.print(f"Artifact: {settings.relative(result.path)}")
    for note in result.notes:
        console.print(f"note: {note}")


@command("review")
def cmd_review(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    video = db.require_video(args.video)
    script = _script_from_video(video)
    result = preflight(script, settings)
    data = metrics(script, settings)
    if args.json_output:
        _emit_json(
            {
                "video_id": video["id"],
                "preflight_score": result.score,
                "breakdown": result.breakdown,
                "metrics": data.as_dict(),
                "notes": result.notes,
            }
        )
        return 0

    _print_video_banner(console, video)
    table = Table(title=f"Script preflight (automatic, not final QC): {result.score}/100")
    table.add_column("Criterion")
    table.add_column("Score", justify="right")
    table.add_column("Max", justify="right")
    maxima = {"hook": 30, "pacing": 25, "suspense": 20, "ending": 15, "compliance": 10}
    for name, score in result.breakdown.items():
        table.add_row(name, str(score), str(maxima[name]))
    console.print(table)
    console.print(
        f"{data.word_count} words | ~{data.estimated_duration:.1f}s | "
        f"{data.beat_count} beats | longest sentence {data.longest_sentence_words} words"
    )
    for note in result.notes:
        console.print(f"- {note}")
    return 0


@command("assets")
def cmd_assets(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    result = Pipeline(settings, db).prepare_assets(args.video)
    console.print(f"[green]{result.video['id']} assets ready[/green] -> ASSETS_READY")
    for note in result.notes:
        console.print(f"  {note}")
    if result.path:
        console.print(f"Asset plan: {settings.relative(result.path)}")
    return 0


@command("narrate")
def cmd_narrate(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    result = Pipeline(settings, db).narrate(args.video)
    console.print(f"[green]{result.video['id']} narration ready[/green] -> AUDIO_READY")
    for note in result.notes:
        console.print(f"  {note}")
    return 0


@command("render")
def cmd_render(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    result = Pipeline(settings, db).render_video(args.video)
    console.print(f"[green]{result.video['id']} rendered[/green] -> RENDERED")
    for note in result.notes:
        console.print(f"  {note}")
    if result.path:
        console.print(f"MP4: [bold]{settings.relative(result.path)}[/bold]")
    console.print(
        f"Next: [bold]qc-check --video {args.video}[/bold], then author the creative QC report."
    )
    return 0


@command("produce")
def cmd_produce(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    """Run the deterministic production stages up to RENDERED; never auto-approve."""

    pipeline = Pipeline(settings, db)
    video = db.require_video(args.video)
    stages = [
        ("STORYBOARD_READY", "assets", pipeline.prepare_assets),
        ("ASSETS_READY", "narration", pipeline.narrate),
        ("AUDIO_READY", "render", pipeline.render_video),
    ]
    for expected_status, label, operation in stages:
        video = db.require_video(args.video)
        if video["status"] != expected_status:
            continue
        console.print(f"[bold]{label}[/bold] ...")
        result = operation(args.video)
        for note in result.notes:
            console.print(f"  {note}")
        video = result.video
    video = db.require_video(args.video)
    if video["status"] == "RENDERED":
        rendered = pipeline.rendered_files(args.video)
        if rendered:
            console.print(f"MP4: [bold]{settings.relative(rendered[-1])}[/bold]")
        console.print(
            f"Next: [bold]qc-check --video {args.video}[/bold], then author and record the creative QC."
        )
        return 0
    console.print(f"Stopped at {video['status']}.")
    return 0


@command("qc-check")
def cmd_qc_check(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    result = Pipeline(settings, db).technical_qc(args.video)
    report = result.technical
    assert isinstance(report, TechnicalReport)
    if args.json_output:
        _emit_json(report.model_dump(mode="json"))
        return 0 if report.passed else 2
    table = Table(title=f"Technical QC: {'PASS' if report.passed else 'FAIL'}")
    table.add_column("Check", style="bold")
    table.add_column("Result", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    for check in report.checks:
        table.add_row(
            check.name,
            "[green]PASS[/green]" if check.passed else "[red]FAIL[/red]",
            check.detail,
        )
    console.print(table)
    passed = sum(1 for check in report.checks if check.passed)
    console.print(f"{passed}/{len(report.checks)} checks passed. Report: {settings.relative(result.path)}")
    if not report.passed:
        console.print("[red]Technical QC blocks creative review until these are fixed.[/red]")
        return 2
    console.print(
        f"Technical validity is not a creative score. Next: author a QC report, then "
        f"[bold]qc --video {args.video} --file <report.json>[/bold]"
    )
    return 0


@command("qc")
def cmd_qc(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    payload = _load_payload(settings, args.file)
    result = Pipeline(settings, db).record_quality(args.video, payload)
    decision = result.decision
    assert decision is not None
    report = QualityReport.model_validate(payload)
    table = Table(title=f"Quality control: {decision.total}/100")
    table.add_column("Section")
    table.add_column("Score", justify="right")
    table.add_column("Max", justify="right")
    values = {
        "hook": report.scores.hook,
        "originality": report.scores.originality,
        "coherence": report.scores.coherence,
        "suspense": report.scores.suspense,
        "ending": report.scores.ending,
        "voice": report.scores.voice,
        "visual_consistency": report.scores.visual_consistency,
        "subtitle_sync": report.scores.subtitle_sync,
        "audio_mix": report.scores.audio_mix,
    }
    for name, maximum in rubric_rows():
        table.add_row(name, str(values[name]), str(maximum))
    console.print(table)
    console.print(f"Verdict: [bold]{decision.verdict.upper()}[/bold] (gate {decision.minimum}/100)")
    for failure in decision.failures:
        console.print(f"  [red]- {failure}[/red]")
    if decision.passed:
        console.print(
            f"Next: after your own review, [bold]approve --video {args.video} --reviewer <name>[/bold]"
        )
        return 0
    console.print("Video rejected. Fix the issues and re-run QC on a new render.")
    return 2


@command("approve")
def cmd_approve(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    result = Pipeline(settings, db).approve(args.video, reviewer=args.reviewer)
    console.print(f"[green]{result.video['id']} approved[/green] -> APPROVED")
    for note in result.notes:
        console.print(note)
    console.print(
        "Next: publish manually on Instagram, then record the URL: "
        f"[bold]publish --video {args.video} --url <reel-url>[/bold]"
    )
    return 0


@command("publish")
def cmd_publish(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    hashtags = [tag.strip() for tag in (args.hashtags or "").split(",") if tag.strip()]
    result = Pipeline(settings, db).publish(
        args.video,
        url=args.url,
        platform=args.platform,
        caption=args.caption,
        hashtags=hashtags,
    )
    console.print(f"[green]{result.video['id']} marked PUBLISHED[/green] on {args.platform}")
    for note in result.notes:
        console.print(note)
    return 0


@command("show")
def cmd_show(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    video = db.require_video(args.video)
    history = db.status_history(video["id"])
    artifacts = db.list_artifacts(video["id"])
    publications = db.list_publications(video["id"])
    qc_row = db.latest_quality_report(video["id"])

    script: Script | None = None
    storyboard: Storyboard | None = None
    if video["script_json"]:
        try:
            script = Script.model_validate(json.loads(str(video["script_json"])))
        except ValidationError:  # pragma: no cover - stored data is validated
            script = None
    if video["storyboard_json"]:
        try:
            storyboard = Storyboard.model_validate(json.loads(str(video["storyboard_json"])))
        except ValidationError:  # pragma: no cover
            storyboard = None

    if args.json_output:
        _emit_json(
            {
                "video": dict(video),
                "history": [dict(row) for row in history],
                "artifacts": [dict(row) for row in artifacts],
                "publications": [dict(row) for row in publications],
                "qc": dict(qc_row) if qc_row else None,
                "script_metrics": metrics(script, settings).as_dict() if script else None,
                "preflight": preflight(script, settings).__dict__ if script else None,
            }
        )
        return 0

    _print_video_banner(console, video)
    info = Table(show_header=False, box=None)
    info.add_column("Field", style="bold")
    info.add_column("Value", overflow="fold")
    info.add_row("Created", str(video["created_at"]))
    info.add_row("Updated", str(video["updated_at"]))
    if video["approved_at"]:
        info.add_row("Approved", str(video["approved_at"]))
    if video["published_at"]:
        info.add_row("Published", str(video["published_at"]))
    if video["latest_qc_total"] is not None:
        info.add_row("Latest QC", f"{video['latest_qc_total']}/100 ({video['latest_qc_verdict']})")
    console.print(info)

    if script:
        data = metrics(script, settings)
        console.print(
            f"[bold]Script[/bold] {data.word_count} words | ~{data.estimated_duration:.1f}s | "
            f"{data.beat_count} beats | hook {data.hook_words} words"
        )
        console.print(f"  {script.narration[0].text}")
        console.print(f"  ... {script.final_line}")
    if storyboard:
        console.print(f"[bold]Storyboard[/bold] {storyboard_summary(storyboard)}")

    if history:
        table = Table(title="Status history")
        table.add_column("When", overflow="fold")
        table.add_column("From", overflow="fold")
        table.add_column("To", style="bold", overflow="fold")
        table.add_column("Actor", overflow="fold")
        table.add_column("Reason", overflow="fold")
        for row in history:
            table.add_row(
                short_time(row["created_at"]),
                str(row["from_status"] or "-"),
                str(row["to_status"]),
                str(row["actor"]),
                str(row["reason"] or ""),
            )
        console.print(table)

    if artifacts:
        table = Table(title="Artifacts")
        table.add_column("Kind")
        table.add_column("v", justify="right")
        table.add_column("Path", overflow="fold")
        table.add_column("SHA-256", overflow="fold")
        for row in artifacts:
            table.add_row(str(row["kind"]), str(row["version"]), str(row["path"]), str(row["sha256"])[:12])
        console.print(table)

    if publications:
        table = Table(title="Publications")
        table.add_column("Platform")
        table.add_column("URL", overflow="fold")
        table.add_column("When")
        for row in publications:
            table.add_row(str(row["platform"]), str(row["url"]), str(row["published_at"]))
        console.print(table)
    return 0


@command("list")
def cmd_list(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    videos = db.list_videos(status=args.status, limit=args.limit)
    if not videos:
        console.print("No videos yet. Create one with: python -m midnight_archive ideas")
        return 0
    table = Table(title="Videos")
    table.add_column("ID", style="bold", no_wrap=True)
    table.add_column("Status", overflow="fold", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("QC", justify="right")
    table.add_column("Updated", overflow="fold")
    for video in videos:
        qc = "-" if video["latest_qc_total"] is None else f"{video['latest_qc_total']:.0f}"
        table.add_row(
            str(video["id"]),
            str(video["status"]),
            str(video["title"]),
            qc,
            short_time(video["updated_at"]),
        )
    console.print(table)
    return 0


@command("export-schemas")
def cmd_export_schemas(
    args: argparse.Namespace, settings: Settings, db: Database, console: Console
) -> int:
    paths = export_schemas(settings)
    for path in paths:
        console.print(settings.relative(path))
    return 0


@command("stats")
def cmd_stats(args: argparse.Namespace, settings: Settings, db: Database, console: Console) -> int:
    if args.stats_command == "add":
        record_stats(
            db,
            args.video,
            views=args.views,
            likes=args.likes,
            comments=args.comments,
            shares=args.shares,
            saves=args.saves,
            platform=args.platform,
            notes=args.notes,
        )
        console.print(f"[green]Recorded stats for {args.video}[/green]")
        return 0

    records = latest_stats(db, video_id=args.video, limit=args.limit)
    if not records:
        console.print("No stats recorded yet. Use: stats add --video TMA-0001 --views 1200 ...")
        return 0
    table = Table(title="Performance (manually entered)")
    table.add_column("Video", style="bold")
    table.add_column("Platform")
    table.add_column("Captured")
    table.add_column("Views", justify="right")
    table.add_column("Likes", justify="right")
    table.add_column("Comments", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Saves", justify="right")
    table.add_column("Engagement", justify="right")
    for record in records:
        table.add_row(
            record.video_id,
            record.platform,
            record.captured_at,
            f"{record.views:,}",
            f"{record.likes:,}",
            f"{record.comments:,}",
            f"{record.shares:,}",
            f"{record.saves:,}",
            f"{record.engagement_rate:.2f}%",
        )
    console.print(table)
    return 0


# ----------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m midnight_archive",
        description="The Midnight Archive - faceless storytelling production studio.",
    )
    parser.add_argument("--root", help="project folder (default: cwd or TMA_HOME)")
    parser.add_argument("--verbose", action="store_true", help="debug logging to logs/midnight.log")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check Python, FFmpeg, folders and database")
    sub.add_parser("init", help="create folders, database and JSON schemas")

    ideas = sub.add_parser("ideas", help="generate a batch of scored story ideas")
    ideas.add_argument("--count", type=int, default=None, help="number of ideas (default from config)")
    ideas.add_argument("--label", help="name this ideation session")
    ideas.add_argument("--seed", type=int, help="deterministic seed for the offline generator")
    ideas.add_argument(
        "--provider", choices=["offline", "openai_compatible"], default=None, help="idea provider"
    )
    ideas.add_argument(
        "--allow-paid-api",
        action="store_true",
        help="required along with TMA_ALLOW_PAID_API=1 before any paid API call",
    )
    ideas.add_argument("--list", action="store_true", help="list stored ideas instead of generating")
    ideas.add_argument("--limit", type=int, default=25, help="rows to list")
    ideas.add_argument("--json", action="store_true", dest="json_output")

    select = sub.add_parser("select", help="select an idea or manual concept and start a video")
    group = select.add_mutually_exclusive_group(required=True)
    group.add_argument("--idea", help="idea id, e.g. IDEA-0007")
    group.add_argument("--video", help="manual video id in IDEA status")
    select.add_argument("--title", help="override the registered title when selecting an idea")
    select.add_argument("--force", action="store_true", help="select an idea below the score floor")

    new = sub.add_parser("new", help="register a hand-picked concept")
    new.add_argument("--title", required=True)
    new.add_argument(
        "--category",
        required=True,
        choices=["psychological_horror", "mystery", "mind_bending"],
    )
    new.add_argument("--premise")
    new.add_argument("--select", action="store_true", help="immediately move to SELECTED")

    script = sub.add_parser("import-script", help="validate and attach a script JSON")
    script.add_argument("--video", required=True)
    script.add_argument("--file", required=True)

    storyboard = sub.add_parser("import-storyboard", help="validate and attach a storyboard JSON")
    storyboard.add_argument("--video", required=True)
    storyboard.add_argument("--file", required=True)

    review = sub.add_parser("review", help="automatic script preflight score")
    review.add_argument("--video", required=True)
    review.add_argument("--json", action="store_true", dest="json_output")

    assets = sub.add_parser("assets", help="prepare and register images, score, SFX and fonts")
    assets.add_argument("--video", required=True)

    narrate = sub.add_parser("narrate", help="synthesize narration, align subtitles and mix audio")
    narrate.add_argument("--video", required=True)

    render = sub.add_parser("render", help="render the MP4 from AUDIO_READY artifacts")
    render.add_argument("--video", required=True)

    produce = sub.add_parser("produce", help="run assets -> narration -> render, stopping at RENDERED")
    produce.add_argument("--video", required=True)

    technical = sub.add_parser("qc-check", help="inspect the rendered MP4 with FFprobe/FFmpeg")
    technical.add_argument("--video", required=True)
    technical.add_argument("--json", action="store_true", dest="json_output")

    qc = sub.add_parser("qc", help="record a creative QC report and apply the 80/100 gate")
    qc.add_argument("--video", required=True)
    qc.add_argument("--file", required=True)

    approve = sub.add_parser("approve", help="human approval of a QC-passed video")
    approve.add_argument("--video", required=True)
    approve.add_argument("--reviewer", default="owner")

    publish = sub.add_parser("publish", help="mark an approved video as published")
    publish.add_argument("--video", required=True)
    publish.add_argument("--url", required=True)
    publish.add_argument("--platform", default="instagram")
    publish.add_argument("--caption")
    publish.add_argument("--hashtags", help="comma-separated")

    show = sub.add_parser("show", help="show one video and its full audit trail")
    show.add_argument("--video", required=True)
    show.add_argument("--json", action="store_true", dest="json_output")

    listing = sub.add_parser("list", help="list videos")
    listing.add_argument("--status", choices=list(STATUSES))
    listing.add_argument("--limit", type=int, default=50)

    sub.add_parser("export-schemas", help="rewrite schemas/ from the Pydantic models")

    stats = sub.add_parser("stats", help="record or view manual performance numbers")
    stats_sub = stats.add_subparsers(dest="stats_command", required=True)
    stats_add = stats_sub.add_parser("add")
    stats_add.add_argument("--video", required=True)
    stats_add.add_argument("--views", type=int, default=0)
    stats_add.add_argument("--likes", type=int, default=0)
    stats_add.add_argument("--comments", type=int, default=0)
    stats_add.add_argument("--shares", type=int, default=0)
    stats_add.add_argument("--saves", type=int, default=0)
    stats_add.add_argument("--platform", default="instagram")
    stats_add.add_argument("--notes")
    stats_show = stats_sub.add_parser("show")
    stats_show.add_argument("--video")
    stats_show.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()

    try:
        settings = Settings.load(args.root)
    except TmaError as exc:
        console.print(f"[bold red]error:[/bold red] {exc}")
        return 1

    configure_logging(settings, verbose=args.verbose)
    logger = get_logger("cli")

    try:
        settings.ensure_layout()
        db = Database(settings.db_path)
    except (TmaError, OSError, sqlite3.Error) as exc:
        console.print(f"[bold red]error:[/bold red] cannot open project database: {exc}")
        return 1

    try:
        handler = COMMANDS[args.command]
        return int(handler(args, settings, db, console))
    except ValidationRejected as exc:
        console.print(f"[bold red]Validation rejected:[/bold red] {exc}")
        for issue in exc.issues:
            console.print(f"  [yellow]-[/yellow] {issue}")
        return 2
    except TmaError as exc:
        console.print(f"[bold red]error:[/bold red] {exc}")
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        console.print("[yellow]Interrupted.[/yellow]")
        return 130
    except Exception as exc:  # noqa: BLE001 - last-resort reporting
        logger.exception("Unhandled error in command %s", args.command)
        console.print(
            f"[bold red]Unexpected error:[/bold red] {type(exc).__name__}: {exc}\n"
            "Details were written to logs/midnight.log"
        )
        return 1
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
