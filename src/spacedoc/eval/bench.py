"""Compare candidate orchestrator models on the same cases (docs/02 §4 selection method)."""

from __future__ import annotations

import dataclasses
from typing import Any

from spacedoc.config import Settings
from spacedoc.eval.cases import Case
from spacedoc.eval.metrics import aggregate
from spacedoc.eval.runner import run_cases
from spacedoc.system import build_system


def bench_models(
    settings: Settings, models: list[str], cases: list[Case], repeats: int = 1
) -> list[dict[str, Any]]:
    table = []
    for model in models:
        s = dataclasses.replace(settings, chat_model=model)
        system = build_system(s)
        rows = run_cases(system, cases, repeats)
        calls = sum(r["answer"]["timings"].get("llm_calls", 0) for r in rows)
        fails = sum(r["answer"]["timings"].get("parse_failures", 0) for r in rows)
        tps = [r["answer"]["timings"].get("tokens_per_s") for r in rows]
        tps = [t for t in tps if t]
        agg = aggregate(rows)
        table.append(
            {
                "model": model,
                "schema_adherence": (1 - fails / calls) if calls else None,
                "claim_support_rate": agg["claim_support_rate"],
                "dx_top3": agg["dx_top3"],
                "abstention_correct": agg["abstention_correct"],
                "harmful": agg["harmful"],
                "latency_s": agg["latency_s"],
                "tokens_per_s": sum(tps) / len(tps) if tps else None,
            }
        )
    return table


def bench_markdown(table: list[dict[str, Any]]) -> str:
    cols = [
        "model",
        "schema_adherence",
        "claim_support_rate",
        "dx_top3",
        "abstention_correct",
        "harmful",
        "latency_s",
        "tokens_per_s",
    ]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in table:
        cells = []
        for c in cols:
            v = row[c]
            cells.append("–" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
