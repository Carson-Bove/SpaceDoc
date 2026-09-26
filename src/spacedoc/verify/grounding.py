"""Claim-versus-source grounding checks (hallucination layer L4).

The default backend asks Bespoke-MiniCheck (served by Ollama) whether a passage supports
a claim. It is a separate model from the orchestrator, so the two don't share one prompt's
blind spots.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from spacedoc.llm.client import LLM


@dataclass
class GroundingVerdict:
    supported: bool
    raw: str


class GroundingChecker(Protocol):
    name: str

    def check(self, claim: str, passage: str) -> GroundingVerdict: ...


class MiniCheckChecker:
    """Bespoke-MiniCheck prompt format: 'Document: ...\\nClaim: ...' -> 'Yes' / 'No'."""

    name = "bespoke-minicheck"

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def check(self, claim: str, passage: str) -> GroundingVerdict:
        prompt = f"Document: {passage}\nClaim: {claim}"
        raw = self.llm.chat([{"role": "user", "content": prompt}], temperature=0.0).text.strip()
        return GroundingVerdict(supported=raw.lower().startswith("yes"), raw=raw)


class LexicalOverlapChecker:
    """DEMO / TEST ONLY. Calls a claim supported when most of its content words appear in
    the passage. This is not a real verifier: it cannot detect negation or changed meaning.
    It exists so the pipeline can run without a model (demo mode, unit tests)."""

    name = "lexical-overlap (demo only)"

    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold

    @staticmethod
    def _words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}

    def check(self, claim: str, passage: str) -> GroundingVerdict:
        words = self._words(claim)
        if not words:
            return GroundingVerdict(False, "no content words")
        overlap = len(words & self._words(passage)) / len(words)
        return GroundingVerdict(overlap >= self.threshold, f"overlap={overlap:.2f}")
