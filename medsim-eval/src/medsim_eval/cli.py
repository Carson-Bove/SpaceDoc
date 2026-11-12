"""Command-line interface: `medsim --help`."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from medsim_eval.models import FILE_TYPES
from medsim_eval.validate import DEFAULT_LIBRARY, validate

app = typer.Typer(
    help="MedSim Eval: simulation-based evaluation of crew medical assistants (research prototype).",
    no_args_is_help=True,
)

LibraryOpt = typer.Option(
    DEFAULT_LIBRARY,
    "--library",
    "-l",
    help="Library folder (DRMs, habitats, conditions, base rubrics)",
)


@app.command("validate")
def validate_cmd(
    paths: list[Path] = typer.Argument(..., help="Files or folders to check"),
    library: Path = LibraryOpt,
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors"),
) -> None:
    """Check scenario, rubric, DRM and habitat files against their schemas and each other."""
    issues = validate(paths, library)
    colours = {"error": typer.colors.RED, "warning": typer.colors.YELLOW, "info": None}
    for issue in issues:
        typer.secho(str(issue), fg=colours[issue.level])
    errors = sum(i.level == "error" for i in issues)
    warnings = sum(i.level == "warning" for i in issues)
    notes = len(issues) - errors - warnings
    typer.echo(f"{errors} error(s), {warnings} warning(s), {notes} note(s)")
    if errors or (strict and warnings):
        raise typer.Exit(1)


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def schema_documents() -> dict[str, dict]:
    """File name -> JSON Schema for every file type."""
    out = {}
    for suffix, model in FILE_TYPES.items():
        name = suffix.removeprefix(".").removesuffix(".json") + ".schema.json"
        out[name] = model.model_json_schema(by_alias=True)
    return out


@app.command("schema")
def schema_cmd(
    out: Path = typer.Option(SCHEMA_DIR, "--out", "-o", help="Folder to write into"),
) -> None:
    """Write the JSON Schema for every file type (for the authoring form and other tools)."""
    out.mkdir(parents=True, exist_ok=True)
    for name, doc in schema_documents().items():
        (out / name).write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        typer.echo(f"wrote {out / name}")


@app.command("migrate")
def migrate_cmd(
    paths: list[Path] = typer.Argument(..., help="v0.1 .scenario.json files or folders"),
    library: Path = LibraryOpt,
) -> None:
    """Convert v0.1 scenarios (and their rubrics) to v0.2 in place, keeping .v0.1.bak copies."""
    from medsim_eval.migrate import migrate_file
    from medsim_eval.validate import load_library

    lib, _ = load_library(library)
    latest = max(lib.base_rubrics, key=lambda r: tuple(int(x) for x in r.split("@")[1].split(".")))
    files = [f for p in paths for f in (sorted(p.rglob("*.scenario.json")) if p.is_dir() else [p])]
    for f in files:
        for line in migrate_file(f, lib, latest):
            typer.echo(line)
    typer.echo("Run `medsim validate` on the migrated files and fill in what the notes ask for.")


@app.command("build-form")
def build_form_cmd(
    out: Path = typer.Option(None, "--out", "-o", help="Where to write the HTML file"),
    library: Path = LibraryOpt,
) -> None:
    """Build the offline scenario-authoring form (one HTML file with the library inside)."""
    from medsim_eval.form import DEFAULT_OUT, build

    path = build(out or DEFAULT_OUT, library)
    typer.echo(f"wrote {path} ({path.stat().st_size // 1024} KB)")


@app.command("sheet")
def sheet_cmd(
    scenario: Path = typer.Argument(
        None, help="A .scenario.json file; leave out for a blank sheet for any scenario"
    ),
    out: Path = typer.Option(None, "--out", "-o", help="Where to write the PDF"),
    library: Path = LibraryOpt,
) -> None:
    """Write a printable scoring sheet (PDF) to fill in by pen while reading a run's transcript."""
    try:
        from medsim_eval.sheet import build_sheet
    except ImportError:
        typer.echo("The scoring sheet needs reportlab: pip install 'medsim-eval[pdf]'")
        raise typer.Exit(1) from None
    from medsim_eval.models import Scenario, ScenarioRubric
    from medsim_eval.validate import load, load_library

    lib, _ = load_library(library)
    sc = rb = None
    if scenario:
        sc, errs = load(scenario)
        rb, rerrs = load(scenario.parent / sc.rubric) if isinstance(sc, Scenario) else (None, [])
        if not isinstance(sc, Scenario) or not isinstance(rb, ScenarioRubric):
            for issue in errs + rerrs:
                typer.echo(str(issue))
            typer.echo("Fix the scenario and its rubric first (medsim validate).")
            raise typer.Exit(1)
        base = lib.base_rubrics.get(rb.base)
        if base is None:
            typer.echo(f"unknown base rubric {rb.base!r}")
            raise typer.Exit(1)
    else:
        base = max(
            lib.base_rubrics.values(),
            key=lambda b: tuple(int(x) for x in b.version.split(".")),
        )
    default = f"{sc.scenario_id}-scoring-sheet.pdf" if sc else "scoring-sheet-blank.pdf"
    path = build_sheet(out or Path(default), base, sc, rb, lib.conditions, lib.crew)
    typer.echo(f"wrote {path}")


SCENARIO_FILES: dict[str, Path] = {}


def _load_scenarios(paths: list[Path], library: Path):
    """Valid scenarios from files or folders (e.g. scenarios/inbox); report and skip the rest."""
    from medsim_eval.models import Scenario
    from medsim_eval.validate import load

    files = [f for p in paths for f in (sorted(p.rglob("*.scenario.json")) if p.is_dir() else [p])]
    out = []
    for f in files:
        errors = [i for i in validate([f], library) if i.level == "error"]
        model, _ = load(f)
        if errors or not isinstance(model, Scenario):
            typer.echo(f"skipping {f}: {len(errors)} error(s); run `medsim validate {f}`")
            continue
        out.append(model)
        SCENARIO_FILES[model.scenario_id] = f
    return out


@app.command("plan")
def plan_cmd(
    paths: list[Path] = typer.Argument(..., help="Scenario files or folders"),
    library: Path = LibraryOpt,
    seed: int = typer.Option(0, help="Base seed"),
) -> None:
    """Show the runs each scenario gets: environments x best and worst course, plus CLiFF odds."""
    from medsim_eval.run.plan import plan_runs
    from medsim_eval.validate import load_library

    lib, _ = load_library(library)
    for sc in _load_scenarios(paths, library):
        runs = plan_runs(sc, lib, seed)
        typer.echo(f"{sc.scenario_id}: {len(runs)} runs")
        for r in runs:
            typer.echo(
                f"  {r.run_id:<16} {r.env} {r.env_name:<26} course {r.course:<6} seed {r.seed}"
            )


@app.command("run")
def run_cmd(
    paths: list[Path] = typer.Argument(..., help="Scenario files or folders, e.g. scenarios/inbox"),
    assistant: str = typer.Option(
        "spacedoc", help="spacedoc, or scripted (a stand-in for testing)"
    ),
    crewmember: str = typer.Option(
        "facts", help="facts (a local model picks which scenario facts were asked for) or rules"
    ),
    model: str = typer.Option("llama3.2:3b", help="Ollama model that picks the facts"),
    ollama_url: str = typer.Option("http://localhost:11434", help="Ollama server"),
    spacedoc_config: Path = typer.Option(
        None, help="SpaceDoc's spacedoc.toml (default: the repo's)"
    ),
    spacedoc_demo: bool = typer.Option(False, help="Run SpaceDoc in its scripted demo mode"),
    script: Path = typer.Option(None, help="Reply script (JSON list) for --assistant scripted"),
    runs: int = typer.Option(None, help="Only the first N runs of each scenario"),
    out: Path = typer.Option(Path("runs"), help="Output folder"),
    seed: int = typer.Option(0, help="Base seed"),
    max_turns: int = typer.Option(12, help="Consult turns before follow-ups start"),
    max_followups: int = typer.Option(3, help="Follow-up reports after the consult"),
    rechecks: bool = typer.Option(
        False, help="Also report back at re-check times the assistant asks for"
    ),
    library: Path = LibraryOpt,
) -> None:
    """Run scenarios against an assistant and log every run (Phase B)."""
    from medsim_eval.run.adapters import make_assistant
    from medsim_eval.run.crewmember import FactCrewmember, RuleCrewmember, RuleExtractor
    from medsim_eval.run.llm import OllamaLLM
    from medsim_eval.run.runner import RunConfig, run_batch
    from medsim_eval.validate import load_library

    lib, _ = load_library(library)
    scenarios = _load_scenarios(paths, library)
    if not scenarios:
        typer.echo("no valid scenarios to run")
        raise typer.Exit(1)
    if crewmember == "facts":
        llm = OllamaLLM(model, ollama_url)
        problem = llm.check()
        if problem:
            typer.echo(problem)
            raise typer.Exit(1)

        def make_crew(persona, spec):
            return FactCrewmember(persona, llm, spec.seed)

    elif crewmember == "rules":

        def make_crew(persona, spec):
            return RuleCrewmember(persona)

    else:
        typer.echo(f"unknown crewmember {crewmember!r} (facts or rules)")
        raise typer.Exit(1)
    options = (
        {"config": spacedoc_config, "demo": spacedoc_demo}
        if assistant == "spacedoc"
        else {"script": script}
    )
    batch = run_batch(
        scenarios,
        lib,
        make_assistant(assistant, **options),
        make_crew,
        RuleExtractor(),
        out,
        RunConfig(max_turns=max_turns, max_followups=max_followups, honor_rechecks=rechecks),
        only=runs,
        base_seed=seed,
        progress=typer.echo,
        files=SCENARIO_FILES,
    )
    typer.echo(f"wrote {batch}")


@app.command("score")
def score_cmd(
    paths: list[Path] = typer.Argument(
        ..., help="A batch folder from `medsim run`, or run folders"
    ),
    model: str = typer.Option("qwen3:8b", help="Ollama model that scores"),
    ollama_url: str = typer.Option("http://localhost:11434", help="Ollama server"),
    num_ctx: int = typer.Option(12288, help="Context window; the transcript must fit"),
    think: bool = typer.Option(False, help="Let the model reason before each answer (slower)"),
    scenario: Path = typer.Option(
        None, help="The .scenario.json, for runs made before scenarios were saved with them"
    ),
    library: Path = LibraryOpt,
) -> None:
    """Score runs against the rubric, item by item, with the transcript lines as evidence."""
    from medsim_eval.models import Scenario, ScenarioRubric
    from medsim_eval.run.llm import OllamaLLM
    from medsim_eval.score import Scorer, score_markdown
    from medsim_eval.validate import load, load_library

    lib, _ = load_library(library)
    llm = OllamaLLM(model, ollama_url, num_ctx=num_ctx, timeout_s=1800, think=think)
    problem = llm.check()
    if problem:
        typer.echo(problem)
        raise typer.Exit(1)
    runs = sorted({r.parent for p in paths for r in p.rglob("run.json")})
    if not runs:
        typer.echo("no runs found (looked for run.json)")
        raise typer.Exit(1)
    scorer = Scorer(llm)
    for run_dir in runs:
        found = sorted(run_dir.parent.glob("*.scenario.json"))
        sc_path = scenario or (found[0] if found else None)
        sc, _ = load(sc_path) if sc_path else (None, [])
        rb, _ = load(sc_path.parent / sc.rubric) if isinstance(sc, Scenario) else (None, [])
        if not isinstance(sc, Scenario) or not isinstance(rb, ScenarioRubric):
            typer.echo(
                f"skipping {run_dir}: its scenario and rubric were not found; pass --scenario"
            )
            continue
        base = lib.base_rubrics.get(rb.base)
        if base is None:
            typer.echo(f"skipping {run_dir}: unknown base rubric {rb.base!r}")
            continue
        typer.echo(f"scoring {run_dir}")
        s = scorer.score(run_dir, sc, rb, base, lib)
        s["scorer"] = {"model": model, "think": think}
        (run_dir / "score.json").write_text(json.dumps(s, indent=1, ensure_ascii=False))
        (run_dir / "score.md").write_text(score_markdown(s))
        c = s["checklist"]
        typer.echo(
            f"  checklist {c['score']}; critical errors {s['critical_errors']['occurred'] or 'none'}; "
            f"{len(s['review'])} item(s) for a person to check"
        )


if __name__ == "__main__":
    app()
