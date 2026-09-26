"""Plain-text rendering of a verified answer (clinical register; role adaptation is Phase 3)."""

from __future__ import annotations

from spacedoc.answer.schema import VerifiedAnswer

_BADGE = {
    "supported": "✓",
    "reasoning": "~",
    "unsupported": "✗",
    "removed": "✗",
    "contradicted": "✗",
}
_ACTION = {"ok": "OK", "requires_confirmation": "CONFIRM", "blocked": "BLOCKED"}


def render_text(v: VerifiedAnswer, show_removed: bool = True) -> str:
    out = [f"Environment: {v.environment}", ""]
    if v.abstained:
        out += [f"⚠ SpaceDoc cannot give a reliable answer: {v.abstain_reason}"]
        if v.missing_info:
            out += ["What would help:"] + [f"  - {m}" for m in v.missing_info]
        out.append("")
    out += [v.summary, ""]
    shown = v.shown_claims
    if shown:
        out.append("Findings (✓ supported by the cited source, ~ model reasoning):")
        for c in shown:
            cites = f" [{', '.join(c.claim.citations)}]" if c.claim.citations else ""
            out.append(f"  {_BADGE[c.status]} {c.claim.text}{cites}")
        out.append("")
    if v.differential:
        out.append("Differential:")
        for d in v.differential:
            out.append(f"  - {d.condition} ({d.likelihood})")
        out.append("")
    if v.actions:
        out.append("Actions:")
        for a in v.actions:
            out.append(f"  [{_ACTION[a.status]}] {a.action.text} ({a.action.risk_tier})")
            if a.calc_text:
                out.append(f"      calculator: {a.calc_text}")
            for r in a.reasons:
                out.append(f"      - {r}")
        out.append("")
    removed = [c for c in v.claims if not c.shown]
    if show_removed and removed:
        out.append("Removed by verification:")
        for c in removed:
            out.append(f"  ✗ {c.claim.text} — {c.detail}")
        out.append("")
    notes = [f for f in v.findings if f.target in {"answer"} or f.target.startswith("S")]
    for f in notes:
        out.append(f"Note [{f.rule_id}]: {f.message}")
    if v.passages:
        out.append("Sources:")
        for p in v.passages:
            page = f", p.{p.page}" if p.page else ""
            out.append(f"  [{p.cid}] {p.title}{page}")
    out.append(f"Uncertainty: {v.uncertainty}" + (f" · audit {v.audit_id}" if v.audit_id else ""))
    return "\n".join(out)
