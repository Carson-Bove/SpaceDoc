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
    for issue in issues:
        typer.secho(
            str(issue), fg=typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        )
    errors = sum(i.level == "error" for i in issues)
    warnings = len(issues) - errors
    typer.echo(f"{errors} error(s), {warnings} warning(s)")
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


@app.command("build-form")
def build_form_cmd(
    out: Path = typer.Option(None, "--out", "-o", help="Where to write the HTML file"),
    library: Path = LibraryOpt,
) -> None:
    """Build the offline scenario-authoring form (one HTML file with the library inside)."""
    from medsim_eval.form import DEFAULT_OUT, build

    path = build(out or DEFAULT_OUT, library)
    typer.echo(f"wrote {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    app()
