"""Typer CLI for airsim-plan.

Sub-commands mirror the four steps of the pipeline:

    plan      Compile a Manifest from an NL instruction (Step 1+2).
    validate  Validate a Manifest JSON file.
    show      Pretty-print a Manifest JSON file.
    prompt    Print the tactical system prompt that would be injected.
    takeoff   Just arm + takeoff (Step 4, without running the loop).
    run       Full hand-off: compile (optional), takeoff, run airsim-loop.
    interactive  REPL: compile, edit, save, launch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

try:
    import typer
except Exception as exc:  # pragma: no cover
    raise RuntimeError("typer is required: pip install typer") from exc

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from .. import __version__
from ..bridge import AirSimBridge, BridgeError, LoopRunner
from ..missions import MissionPlanner, PlannerError, load_manifest
from ..missions.manifest import MissionManifest


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Ground-station Mission Planner for the airsim-loop / airsim-plan stack.",
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"airsim-plan {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """airsim-plan root options."""


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _print_manifest(manifest: MissionManifest) -> None:
    console.print(
        Panel.fit(
            Syntax(manifest.to_json(), "json", theme="monokai", word_wrap=True),
            title=f"Manifest · {manifest.mission_id}",
            border_style="cyan",
        )
    )


# --------------------------------------------------------------------------- #
# Commands                                                                    #
# --------------------------------------------------------------------------- #
@app.command("plan")
def plan_cmd(
    instruction: str = typer.Option(
        ...,
        "--instruction",
        "-i",
        help="Natural-language mission description.",
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        "-o",
        help="Where to write the manifest. Defaults to MISSION_DIR/<id>.json.",
    ),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help="Also print the tactical system prompt that would be injected.",
    ),
) -> None:
    """Compile a Manifest from an NL instruction."""
    planner = MissionPlanner()
    try:
        if out is not None:
            manifest, path = planner.compile_and_save(instruction, filename=out.name)
        else:
            manifest = planner.compile(instruction)
            from ..missions.manifest import save_manifest

            path = save_manifest(
                manifest,
                planner.settings.mission_dir / f"{manifest.mission_id.lower()}.json",
            )
    except PlannerError as exc:
        console.print(f"[red]planner error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]manifest saved to[/green] {path}")
    _print_manifest(manifest)
    if print_prompt and manifest.tactical_system_prompt:
        console.print(
            Panel(
                manifest.tactical_system_prompt,
                title=f"tactical_system_prompt · {manifest.mission_id}",
                border_style="magenta",
            )
        )


@app.command("validate")
def validate_cmd(
    manifest_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Validate a Manifest JSON file."""
    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        console.print(f"[red]invalid manifest:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]OK[/green] {manifest_path} ({manifest.mission_id})")


@app.command("show")
def show_cmd(
    manifest_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Pretty-print a Manifest JSON file."""
    manifest = load_manifest(manifest_path)
    _print_manifest(manifest)
    if manifest.tactical_system_prompt:
        console.print(
            Panel(
                manifest.tactical_system_prompt,
                title=f"tactical_system_prompt · {manifest.mission_id}",
                border_style="magenta",
            )
        )


@app.command("prompt")
def prompt_cmd(
    manifest_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Print only the tactical system prompt that would be injected."""
    manifest = load_manifest(manifest_path)
    if not manifest.tactical_system_prompt:
        console.print(
            "[yellow]manifest has no tactical_system_prompt "
            "(compile it through the planner to inject one).[/yellow]"
        )
        raise typer.Exit(code=2)
    sys.stdout.write(manifest.tactical_system_prompt)
    if not manifest.tactical_system_prompt.endswith("\n"):
        sys.stdout.write("\n")


@app.command("takeoff")
def takeoff_cmd(
    altitude: Optional[float] = typer.Option(
        None,
        "--altitude",
        "-a",
        help="Takeoff altitude (NED). Defaults to DEFAULT_TAKEOFF_ALT.",
    ),
) -> None:
    """Just arm + takeoff, no loop. Useful for sanity-checking AirSim."""
    bridge = AirSimBridge()
    try:
        bridge.hand_off(altitude=altitude)
    except BridgeError as exc:
        console.print(f"[red]takeoff failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        try:
            bridge.disconnect()
        except Exception:  # pragma: no cover
            pass


@app.command("run")
def run_cmd(
    manifest_path: Optional[Path] = typer.Option(
        None,
        "--manifest",
        "-m",
        help="Pre-compiled manifest. If omitted, compile from --instruction.",
    ),
    instruction: Optional[str] = typer.Option(
        None,
        "--instruction",
        "-i",
        help="NL instruction. Required when --manifest is omitted.",
    ),
    altitude: Optional[float] = typer.Option(
        None,
        "--altitude",
        "-a",
        help="Takeoff altitude (NED).",
    ),
    loop_path: Optional[Path] = typer.Option(
        None,
        "--loop-path",
        help="Path to airsim-loop main.py. Falls back to in-process import.",
    ),
    hz: float = typer.Option(0.5, "--hz", help="Loop frequency in Hz."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Skip LLM + AirSim, just resolve and validate.",
    ),
) -> None:
    """Full hand-off: compile (optional), takeoff, run airsim-loop."""
    manifest: Optional[MissionManifest] = None
    if manifest_path is not None:
        manifest = load_manifest(manifest_path)
    elif instruction is not None:
        planner = MissionPlanner()
        try:
            manifest = planner.compile(instruction)
            from ..missions.manifest import save_manifest

            save_manifest(
                manifest,
                planner.settings.mission_dir / f"{manifest.mission_id.lower()}.json",
            )
        except PlannerError as exc:
            console.print(f"[red]planner error:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    else:
        console.print("[red]either --manifest or --instruction is required[/red]")
        raise typer.Exit(code=2)

    if dry_run:
        _print_manifest(manifest)
        console.print("[yellow]dry-run, nothing else executed.[/yellow]")
        return

    runner = LoopRunner(manifest, loop_path=loop_path, loop_hz=hz)
    try:
        runner.run(takeoff_altitude=altitude)
    except LoopRunnerError as exc:
        console.print(f"[red]runner error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("interactive")
def interactive_cmd() -> None:
    """Tiny REPL: type instructions, see the manifest, launch when ready."""
    planner = MissionPlanner()
    console.print(
        Panel(
            "airsim-plan interactive\n"
            "  Type a mission instruction and press Enter.\n"
            "  Commands: :save, :launch, :quit",
            border_style="blue",
        )
    )
    manifest: Optional[MissionManifest] = None
    while True:
        try:
            raw = console.input("[bold cyan]mission>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nbye.")
            return
        text = raw.strip()
        if not text:
            continue
        if text in (":quit", ":q"):
            return
        if text == ":save":
            if manifest is None:
                console.print("[yellow]compile a mission first[/yellow]")
                continue
            _, path = planner.compile_and_save(
                "",  # ignored when manifest already compiled
            )
            console.print(f"saved to {path}")
            continue
        if text == ":launch":
            if manifest is None:
                console.print("[yellow]compile a mission first[/yellow]")
                continue
            runner = LoopRunner(manifest)
            runner.run()
            continue
        try:
            manifest = planner.compile(text)
        except PlannerError as exc:
            console.print(f"[red]{exc}[/red]")
            continue
        _print_manifest(manifest)


@app.command("dump-schema")
def dump_schema_cmd(
    out: Path = typer.Option(
        Path("manifest.schema.json"),
        "--out",
        "-o",
        help="Where to write the JSON Schema.",
    ),
) -> None:
    """Dump the bundled JSON Schema for the Manifest."""
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "manifest_schema.json"
    out.write_text(schema_path.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"[green]wrote {out}[/green]")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
