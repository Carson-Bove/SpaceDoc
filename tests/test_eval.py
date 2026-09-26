from spacedoc.config import REPO_ROOT
from spacedoc.eval.cases import load_cases
from spacedoc.eval.runner import run_cases, summarize, write_report


def test_example_cases_validate_and_are_drafts():
    cases = load_cases(REPO_ROOT / "cases")
    assert {c.case_id for c in cases} >= {"SO-0001", "SO-0002", "SO-0003"}
    assert all(c.status == "draft" for c in cases if c.case_id.startswith("SO-000"))


def test_demo_run_scores_and_reports(demo_system, tmp_path):
    rows = run_cases(demo_system, load_cases(REPO_ROOT / "cases"))
    by = {r["case_id"]: r for r in rows}
    assert by["SO-0001"]["dx_top1"] is True
    assert by["SO-0001"]["harmful"] is False  # the blocked evacuation/tamsulosin are not shown
    assert by["SO-0001"]["numeric_interventions"] >= 1
    assert by["SO-0003"]["abstention_correct"] is True
    summary = summarize(rows)
    assert summary["approved"]["n"] == 0  # drafts never count toward headline numbers
    report = write_report(rows, tmp_path / "run", "demo").read_text()
    assert "Unreviewed drafts" in report
