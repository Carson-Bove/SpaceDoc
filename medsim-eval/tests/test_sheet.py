"""The printable scoring sheet: blank and pre-filled sheets build, and bad input is refused."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from medsim_eval.cli import app

pytest.importorskip("reportlab")
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("args", [[], [str(EXAMPLES / "MSE-0001.scenario.json")]])
def test_sheet_builds(tmp_path, args):
    out = tmp_path / "sheet.pdf"
    result = CliRunner().invoke(app, ["sheet", *args, "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_bytes().startswith(b"%PDF") and out.stat().st_size > 5000


def test_sheet_refuses_a_broken_scenario(tmp_path):
    bad = tmp_path / "MSE-0009.scenario.json"
    bad.write_text("{}")
    result = CliRunner().invoke(app, ["sheet", str(bad), "-o", str(tmp_path / "x.pdf")])
    assert result.exit_code == 1
    assert "medsim validate" in result.output
