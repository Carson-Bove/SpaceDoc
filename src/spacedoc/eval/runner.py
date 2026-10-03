"""Run SpaceDoc over a case bank and write a report (docs/08 §5 "Runner")."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from spacedoc.eval.cases import Case
from spacedoc.eval.metrics import aggregate, score_case
from spacedoc.llm.client import LLMError
from spacedoc.review.summary import LABEL, NoReasoning, StoredSummary, summary_markdown
from spacedoc.system import System


def run_cases(
    system: System, cases: list[Case], repeats: int = 1, summaries: bool = True
) -> list[dict[str, Any]]:
    """Run every case. With `summaries`, also make a reasoning summary for clinical review
    whenever the model produced thinking notes (one extra model call per answer)."""
    rows = []
    for case in cases:
        if case.status == "retired":
            continue
        env = system.environment(
            case.environment.tier,
            mission_day=case.environment.mission_day,
            link_available=case.environment.link_available,
        )
        for r in range(repeats):
            v = system.orchestrator.ask(case.presentation, env, case.patient, case.user_role)
            row = score_case(case, v)
            row["repeat"] = r
            row["audit_id"] = v.audit_id
            row["answer"] = v.model_dump(mode="json", exclude={"draft"})
            if summaries and system.reviewer and v.reasoning_available and v.audit_id:
                try:
                    stored = system.reviewer.summarize(v.audit_id)
                    row["reasoning_summary"] = stored.model_dump()
                except (LLMError, NoReasoning) as e:
                    row["reasoning_summary_error"] = str(e)
            rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    approved = [r for r in rows if r["status"] == "approved"]
    drafts = [r for r in rows if r["status"] == "draft"]
    return {"approved": aggregate(approved), "unreviewed_drafts": aggregate(drafts)}


def _fmt(x) -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.2f}"
    return str(x)


def write_report(rows: list[dict[str, Any]], out_dir: Path, label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    (out_dir / "results.json").write_text(
        json.dumps({"label": label, "summary": summary, "rows": rows}, indent=2, default=str)
    )
    lines = [
        f"# SpaceOSCE run: {label}",
        "",
        f"Generated {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    lines += [
        "Headline numbers use **approved** cases only. Draft cases have not been reviewed by a",
        "clinician and are reported separately for development.",
        "",
        "| Metric | Approved | Unreviewed drafts |",
        "|---|---|---|",
    ]
    for key in summary["approved"]:
        lines.append(
            f"| {key} | {_fmt(summary['approved'][key])} | {_fmt(summary['unreviewed_drafts'][key])} |"
        )
    lines += [
        "",
        "## Per case",
        "",
        "| Case | Status | Top-3 Dx | Harmful | Abstain OK | Support | Latency s |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case_id']} | {r['status']} | {_fmt(r.get('dx_top3'))} | {_fmt(r['harmful'])} | "
            f"{_fmt(r['abstention_correct'])} | {_fmt(r.get('claim_support_rate'))} | {_fmt(r.get('latency_s'))} |"
        )
    reviewed = [r for r in rows if r.get("reasoning_summary") or r.get("reasoning_summary_error")]
    if reviewed:
        lines += [
            "",
            "## Reasoning summaries (for clinical review)",
            "",
            f"_{LABEL}_",
        ]
        for r in reviewed:
            answer = r["answer"]
            lines += [
                "",
                f"### {r['case_id']} (repeat {r['repeat']}, {r.get('audit_id')})",
                "",
                f"**Answer summary:** {answer.get('summary')}",
                "",
            ]
            if r.get("reasoning_summary"):
                stored = StoredSummary.model_validate(r["reasoning_summary"])
                lines += summary_markdown(stored)[2:]  # the label is printed once above
            else:
                lines.append(f"Summary not available: {r['reasoning_summary_error']}")
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
