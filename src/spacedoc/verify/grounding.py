"""Claim-versus-source grounding checks (hallucination layer L4).

The default backend asks Bespoke-MiniCheck (served by Ollama) whether a passage supports
a claim. It is a separate model from the orchestrator, so the two don't share one prompt's
blind spots.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from spacedoc.llm.client import LLM, GenParams

# Abbreviations that end in a period but do not end a sentence.
_ABBREV = {
    "e.g",
    "i.e",
    "etc",
    "vs",
    "approx",
    "dr",
    "fig",
    "cf",
    "st",
    "mr",
    "mrs",
    "ms",
    "u.s",
    "al",
    "min",
    "max",
    "resp",
    "incl",
}


def split_sentences(text: str) -> list[str]:
    """Split a claim into sentences (MiniCheck checks one sentence at a time).

    Conservative: a break needs ., ! or ? followed by whitespace and a capital letter, digit
    or opening bracket, and the word before the period must not be a known abbreviation.
    Decimals such as "2.5" never split.
    """
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"])", text.strip())
    sentences: list[str] = []
    for part in parts:
        last_word = sentences[-1].rsplit(" ", 1)[-1].rstrip(".").lower() if sentences else ""
        if sentences and last_word in _ABBREV:
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return [s for s in sentences if s]


@dataclass
class GroundingVerdict:
    supported: bool
    raw: str
    probability: float | None = None  # P("Yes") when the server returns log-probabilities


def yes_probability(top: list[tuple[str, float]] | None) -> float | None:
    """P(Yes) from the first output token's alternatives, normalised over Yes and No."""
    if not top:
        return None
    yes = sum(math.exp(lp) for tok, lp in top if tok.strip().lower() == "yes")
    no = sum(math.exp(lp) for tok, lp in top if tok.strip().lower() == "no")
    if yes + no == 0:
        return None
    return yes / (yes + no)


class GroundingChecker(Protocol):
    name: str

    def check(self, claim: str, passage: str) -> GroundingVerdict: ...


class MiniCheckChecker:
    """Bespoke-MiniCheck prompt format: 'Document: ...\\nClaim: ...' -> 'Yes' / 'No'."""

    name = "bespoke-minicheck"

    def __init__(self, llm: LLM, num_ctx: int | None = None) -> None:
        self.llm = llm
        # The model's own system prompt (in its Ollama Modelfile) asks for "Yes" or "No".
        # Log-probabilities give P(Yes) on the Ollama backend; other servers may ignore it.
        self.params = GenParams(temperature=0.0, max_tokens=8, num_ctx=num_ctx, logprobs=5)

    def check(self, claim: str, passage: str) -> GroundingVerdict:
        prompt = f"Document: {passage}\nClaim: {claim}"
        result = self.llm.chat([{"role": "user", "content": prompt}], params=self.params)
        raw = result.text.strip()
        prob = yes_probability(result.top_logprobs)
        if prob is not None:
            raw = f"{raw} (P(yes)={prob:.2f})"
        return GroundingVerdict(supported=raw.lower().startswith("yes"), raw=raw, probability=prob)


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
