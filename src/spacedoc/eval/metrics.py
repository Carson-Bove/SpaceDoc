"""Automatic SpaceOSCE metrics (docs/08 §3.1). Human rubric scores are collected separately."""

from __future__ import annotations

import re
from typing import Any

from spacedoc.answer.schema import VerifiedAnswer
from spacedoc.eval.cases import Case, CheckItem


def _names(name: str, synonyms: dict[str, list[str]]) -> list[str]:
    return [name.lower(), *(s.lower() for s in synonyms.get(name, []))]


def _matches(candidate: str, name: str, synonyms: dict[str, list[str]]) -> bool:
    c = candidate.lower()
    return any(n in c or c in n for n in _names(name, synonyms))


def shown_text(v: VerifiedAnswer) -> str:
    """Everything the user would actually see (removed claims and blocked actions excluded)."""
    parts = [v.summary]
    parts += [c.claim.text for c in v.shown_claims]
    parts += [d.condition for d in v.differential]
    for a in v.actions:
        if a.status != "blocked":
            parts.append(a.action.text)
            if a.calc_text:
                parts.append(a.calc_text)
    return "\n".join(parts)


def _auto(items: list[CheckItem], text: str) -> tuple[list[str], list[str]]:
    hit, unscored = [], []
    for item in items:
        if not item.auto_patterns:
            unscored.append(item.id)
        elif any(re.search(p, text, flags=re.IGNORECASE) for p in item.auto_patterns):
            hit.append(item.id)
    return hit, unscored


def score_case(case: Case, v: VerifiedAnswer) -> dict[str, Any]:
    gt = case.ground_truth
    dx = [d.condition for d in v.differential] if not v.abstained else []
    text = shown_text(v)
    out: dict[str, Any] = {"case_id": case.case_id, "status": case.status, "abstained": v.abstained}

    if gt.primary_dx:
        out["dx_top1"] = bool(dx) and _matches(dx[0], gt.primary_dx, gt.synonyms)
        out["dx_top3"] = any(_matches(d, gt.primary_dx, gt.synonyms) for d in dx[:3])
    if gt.must_not_miss:
        covered = [
            m for m in gt.must_not_miss if any(n in text.lower() for n in _names(m, gt.synonyms))
        ]
        out["must_not_miss_coverage"] = len(covered) / len(gt.must_not_miss)

    hit, unscored = _auto(case.critical_actions, text)
    scored_items = [c for c in case.critical_actions if c.id not in unscored]
    if scored_items:
        out["critical_action_score"] = sum(c.weight for c in scored_items if c.id in hit) / sum(
            c.weight for c in scored_items
        )
    out["critical_actions_needing_rater"] = unscored

    harmful_hit, _ = _auto(case.harmful_actions, text)
    out["harmful_hits"] = harmful_hit
    out["harmful"] = bool(harmful_hit)

    out["abstention_correct"] = v.abstained == case.expected_abstain

    draft = v.draft
    cites = [c for cl in (draft.claims if draft else []) for c in cl.citations]
    valid = {p.cid for p in v.passages}
    out["citation_validity"] = (sum(c in valid for c in cites) / len(cites)) if cites else None
    sourced = [c for c in v.claims if c.claim.kind == "sourced"]
    out["claim_support_rate"] = (
        sum(c.status == "supported" for c in sourced) / len(sourced) if sourced else None
    )
    # Interventions: what the verification layer had to catch in this answer.
    out["numeric_interventions"] = sum(f.rule_id.startswith("NUM-") for f in v.findings)
    out["formulary_env_interventions"] = sum(
        f.severity == "block" and f.rule_id.split("-")[0] in {"FORM", "ENV", "EQUIP"}
        for f in v.findings
    )
    out["latency_s"] = v.timings.get("total_s")
    out["parse_failures"] = v.timings.get("parse_failures", 0)
    return out


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return None
        return sum(float(x) for x in vals) / len(vals)

    keys = [
        "dx_top1",
        "dx_top3",
        "must_not_miss_coverage",
        "critical_action_score",
        "harmful",
        "abstention_correct",
        "citation_validity",
        "claim_support_rate",
        "numeric_interventions",
        "formulary_env_interventions",
        "latency_s",
        "parse_failures",
    ]
    return {"n": len(rows), **{k: mean(k) for k in keys}}
