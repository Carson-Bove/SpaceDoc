"""Command-line interface: `spacedoc --help`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

from spacedoc.config import load_settings

app = typer.Typer(
    help="SpaceDoc Phase 1 (research prototype, not for clinical use).", no_args_is_help=True
)
eval_app = typer.Typer(help="SpaceOSCE evaluation.", no_args_is_help=True)
corpus_app = typer.Typer(help="Knowledge-base corpus.", no_args_is_help=True)
audit_app = typer.Typer(help="Audit log.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")
app.add_typer(corpus_app, name="corpus")
app.add_typer(audit_app, name="audit")

ConfigOpt = typer.Option(None, "--config", "-c", help="Path to spacedoc.toml")


def warn_about_models(settings) -> None:
    """Say up front if a model is missing, instead of failing deep inside an answer."""
    from spacedoc.system import check_models

    for line in check_models(settings).problems():
        typer.secho(f"WARNING: {line}", fg=typer.colors.RED, err=True)


@corpus_app.command("fetch")
def corpus_fetch(config: Path = ConfigOpt) -> None:
    """Download the files listed in corpus/manifest.yaml into corpus/files/."""
    from spacedoc.kb.fetch import fetch_corpus

    s = load_settings(config)
    for line in fetch_corpus(s.corpus_dir / "manifest.yaml", s.corpus_dir / "files"):
        typer.echo(line)


@corpus_app.command("ingest")
def corpus_ingest(config: Path = ConfigOpt) -> None:
    """Chunk and embed every source in the manifest into the knowledge store."""
    from spacedoc.kb.store import KnowledgeStore
    from spacedoc.llm.client import LLMError, connect
    from spacedoc.system import ingest_manifest

    s = load_settings(config)
    store = KnowledgeStore(s.db_path)
    embedder = connect(
        s.llm_backend, s.llm_base_url, s.chat_model, s.embed_model, s.request_timeout_s
    )
    try:
        n = ingest_manifest(
            store, embedder, s.corpus_dir / "manifest.yaml", s.corpus_dir / "files", s.embed_model
        )
    except LLMError as e:
        typer.echo(f"Embedding failed: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"Ingested {n} chunks. Store now holds {store.count()} chunks:")
    for source_id, title, count in store.sources():
        typer.echo(f"  {source_id:<32} {count:>5}  {title}")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    demo: bool = typer.Option(False, help="Scripted demo mode (no model needed)"),
    consult_model: str = typer.Option(
        None, help="Model for consult question turns, e.g. qwen3:4b (default from spacedoc.toml)"
    ),
    config: Path = ConfigOpt,
) -> None:
    """Start the consult page at http://127.0.0.1:8765."""
    import uvicorn

    from spacedoc.system import build_system
    from spacedoc.web.app import create_app

    settings = load_settings(config)
    if consult_model:
        settings.consult_model = consult_model
    if not demo:
        warn_about_models(settings)
    system = build_system(settings, demo=demo)
    typer.echo(f"SpaceDoc {'DEMO ' if demo else ''}GUI on http://{host}:{port}")
    uvicorn.run(create_app(system), host=host, port=port, log_level="warning")


@app.command()
def consult(
    user: str = typer.Option(None, help="Crew ID of the person typing (asked if omitted)"),
    patient: str = typer.Option(
        None, help="Patient: a crew ID, 'self' or 'unlisted' (asked if omitted)"
    ),
    tier: str = typer.Option(None, help="Environment tier T1-T5"),
    practice: bool = typer.Option(
        None, "--practice/--real", help="Practice or real session (asked if omitted)"
    ),
    scenario: str = typer.Option(None, help="Scenario ID, for practice sessions"),
    deep_log: bool = typer.Option(
        False, help="Thinking on every turn (slower); each turn also shows the time without it"
    ),
    model: str = typer.Option(
        None, help="Model for question turns, e.g. qwen3:4b (default: consult_model or chat_model)"
    ),
    demo: bool = typer.Option(False, help="Scripted demo mode (no model needed)"),
    config: Path = ConfigOpt,
) -> None:
    """Start a consult: SpaceDoc asks questions to build a differential, then assesses."""
    from spacedoc.consult.cli import run_consult
    from spacedoc.system import build_system

    settings = load_settings(config)
    if model:
        settings.consult_model = model
    if not demo:
        warn_about_models(settings)
    system = build_system(settings, demo=demo)
    run_consult(system, user, patient, tier, practice, scenario, deep_log)


@eval_app.command("run")
def eval_run(
    cases_dir: Path = typer.Option(Path("cases"), help="Directory of case YAML files"),
    repeats: int = 1,
    demo: bool = False,
    summaries: bool = typer.Option(
        True, help="Add reasoning summaries for clinical review (one extra model call per answer)"
    ),
    config: Path = ConfigOpt,
) -> None:
    """Run SpaceDoc over the case bank and write eval_runs/<timestamp>/report.md."""
    from spacedoc.eval.cases import load_cases
    from spacedoc.eval.runner import run_cases, write_report
    from spacedoc.system import build_system

    s = load_settings(config)
    system = build_system(s, demo=demo)
    cases = load_cases(cases_dir)
    rows = run_cases(system, cases, repeats, summaries=summaries)
    label = "demo" if demo else s.chat_model
    out = (
        Path("eval_runs")
        / f"{datetime.now():%Y%m%d-%H%M%S}-{label.replace(':', '_').replace(' ', '_')}"
    )
    path = write_report(rows, out, label)
    typer.echo(path.read_text())
    typer.echo(f"Full results: {out / 'results.json'}")


@app.command()
def bench(
    models: list[str] = typer.Argument(..., help="Ollama model tags to compare"),
    cases_dir: Path = typer.Option(Path("cases"), help="Directory of case YAML files"),
    repeats: int = 1,
    thinking: str = typer.Option(
        "config",
        help="Thinking for the first pass: config, on, off, or both (runs each model twice)",
    ),
    config: Path = ConfigOpt,
) -> None:
    """Compare candidate orchestrator models on the same cases."""
    from spacedoc.eval.bench import bench_markdown, bench_models
    from spacedoc.eval.cases import load_cases

    table = bench_models(
        load_settings(config), models, load_cases(cases_dir), repeats, thinking=thinking
    )
    typer.echo(bench_markdown(table))


@app.command("env")
def env_show(config: Path = ConfigOpt) -> None:
    """List the environment tier presets."""
    from spacedoc.env.context import list_tiers

    for e in list_tiers(load_settings(config).data_dir):
        typer.echo(e.summary())


@audit_app.command("verify")
def audit_verify(path: Path = typer.Option(None), config: Path = ConfigOpt) -> None:
    """Check the audit log's hash chain for tampering."""
    from spacedoc.audit.log import AuditLog

    ok, bad = AuditLog(path or load_settings(config).audit_path).verify()
    typer.echo("Audit chain intact." if ok else f"Audit chain BROKEN at entry {bad}.")
    raise typer.Exit(0 if ok else 1)


@app.command()
def calc(
    name: str,
    args_json: str = "{}",
    weight_kg: float = typer.Option(None),
    config: Path = ConfigOpt,
) -> None:
    """Run a calculator directly, e.g. spacedoc calc weight_based_dose '{"drug":"ibuprofen"}' --weight-kg 70"""
    from spacedoc.tools.calculators import run_calculator
    from spacedoc.tools.formulary import Formulary

    s = load_settings(config)
    r = run_calculator(
        name,
        json.loads(args_json),
        Formulary.load("example-transit", s.data_dir),
        {"weight_kg": weight_kg} if weight_kg else None,
    )
    typer.echo(r.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
