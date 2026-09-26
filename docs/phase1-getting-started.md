# Phase 1 — Getting Started

Phase 1 is a thin, working slice of SpaceDoc:
- Ask a medical question.
- SpaceDoc retrieves sources, drafts a structured answer, runs calculators for any numbers, and verifies every claim.
- It shows the result in a local web page.
- It is measured by the SpaceOSCE harness.

> **Research prototype. Not for clinical use.** The formulary, feasibility rules and example cases in this repository are engineering drafts that have not been reviewed by clinicians.

## 1. Try it without a model (demo mode)

Demo mode replaces the language model with a scripted stand-in and uses three short **synthetic** texts as the knowledge base. The scripted answers contain deliberate mistakes, so you can watch the verification layer catch them.

```bash
git clone https://github.com/Carson-Bove/SpaceDoc.git && cd SpaceDoc
git checkout claude/upbeat-dijkstra-629dkj
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

spacedoc serve --demo          # open http://127.0.0.1:8765 and press "Ask SpaceDoc"
spacedoc ask --demo "Sharp right flank pain that moves toward my groin"
spacedoc eval run --demo       # runs the 3 example cases, writes eval_runs/<time>/report.md
pytest -q                      # 54 tests
```

In the demo flank-pain answer, the verification layer should:

| Scripted mistake | What catches it |
|---|---|
| Invented statistic ("95% of cases") | `NUM-UNTRACED`: the number is not in the cited source |
| Claim the source doesn't make ("definitive cure") | The grounding check |
| Expired drug (tamsulosin) | `FORM-EXPIRED` |
| Evacuation on a deep-space mission | `ENV-EVACUATE` |
| Corrupted document with "ignore all previous instructions" | `INJECTION`: the document is excluded before the model sees it |

In the demo, the acetaminophen dose comes from the calculator, not the model: 15 mg/kg × 78 kg, capped at 1000 mg. The dose is flagged as not clinician-validated.

## 2. Run it with real models on the MacBook Air (16 GB)

### Install Ollama and pull models

Install Ollama from ollama.com (macOS app). Then pull these models:

```bash
ollama pull qwen3:8b               # orchestrator (≈5 GB)
ollama pull qwen3-embedding:0.6b   # embeddings for retrieval
ollama pull bespoke-minicheck      # grounding checker (7B; Ollama swaps it in/out)
```

**Check the exact tags.** Ollama tags change. I could not reach ollama.com from the build environment to confirm these. If a `pull` fails, search the Ollama library for the model and put the working tag in `spacedoc.toml`.

**Memory.** On 16 GB, Ollama holds only some models in memory at once and swaps the others in. Expect the first question after a switch to be slower. Close other large apps while testing.

### Build the knowledge base

The corpus manifest (`corpus/manifest.yaml`) lists open-access sources with URLs, licenses and hashes. Then:

```bash
spacedoc corpus fetch    # downloads into corpus/files/ (not committed to git)
spacedoc corpus ingest   # chunks + embeds into spacedoc.db
```

Until the manifest is filled in (see [research-backlog.md](research-backlog.md)), you can add your own PDFs:
1. Put the file in `corpus/files/`.
2. Add an entry to `corpus/manifest.yaml` (see the field list in the file).
3. Run `spacedoc corpus ingest`.

### Use it

```bash
spacedoc serve                                  # GUI on http://127.0.0.1:8765
spacedoc ask "..." --tier T4 --patient me.yaml  # CLI
spacedoc audit verify                           # check the audit log hasn't been altered
```

## 3. Choose the orchestrator model (desktop or Mac)

`spacedoc bench` runs the same cases through several models and prints a comparison table:

```bash
ollama pull gemma4:e4b   # example candidates; check tags in the Ollama library
ollama pull medgemma:4b
spacedoc bench qwen3:8b gemma4:e4b medgemma:4b --repeats 3
```

Output format:

| model | schema_adherence | claim_support_rate | dx_top3 | abstention_correct | harmful | latency_s | tokens_per_s |
|---|---|---|---|---|---|---|---|

- **schema_adherence:** how often the model's first reply was valid JSON for the answer schema.
- **claim_support_rate:** the share of sourced claims the grounding checker confirmed.

Both depend on the model *and* the corpus, so re-run the bench after changing either. With only 3 draft cases, treat the numbers as a smoke test, not a result. Meaningful comparisons need the clinician-approved case bank.

**Desktop (8 GB VRAM).** Install Ollama for Windows/Linux. An 8B model at 4-bit fits on the GPU, so the desktop is the faster machine for overnight `bench` and `eval run --repeats N` jobs. Point `llm_base_url` in `spacedoc.toml` at the desktop to run evaluations from the Mac against it.

## 4. How a question flows through the code

```
question ─► kb/retrieve.py      hybrid search: keyword (FTS5/BM25) + vector (cosine), fused by RRF
         ─► verify/rules.py     screen passages for injected instructions; renumber S1..Sn
         ─► agent/orchestrator  pass 1: model drafts a DraftAnswer (JSON schema) + calculator requests
         ─► tools/calculators   deterministic doses/scores; weight always from the record
         ─► agent/orchestrator  pass 2: model finalizes, referencing calc_ids
         ─► verify/pipeline.py  cite-or-drop → grounding check → numbers → formulary/equipment/
                                environment rules → risk gating → abstain decision
         ─► audit/log.py        hash-chained record of everything above
         ─► web/ or render/     display with badges, citations and "why this answer"
```

---

## How this works in AI systems: the pieces you just ran

- **Structured output.** Ollama receives the answer's JSON schema and constrains generation to match it. SpaceDoc still validates the reply with Pydantic and retries once, because small models occasionally produce schema-valid JSON with the wrong meaning. `schema_adherence` in the bench measures how often the first try parses.
- **Reciprocal-rank fusion (RRF).** Keyword search scores (BM25) and vector scores (cosine) are on different scales, so adding them is meaningless. RRF ignores the scores and only uses each result's *rank*: every list contributes `1/(60 + rank)`. A passage ranked well by both methods rises to the top. The constant 60 damps the influence of any single list.
- **Why two passes?** Letting the model call tools mid-sentence (native tool calling) is flexible but hard to audit. Phase 1 uses a fixed loop instead: draft, run the requested calculators in code, then finalize. It's less clever, but every step is deterministic and logged, which is what a safety case needs.
- **Grounding checker.** Bespoke-MiniCheck is trained for one job: given a document and a sentence, answer whether the document supports the sentence. It is a different model from the orchestrator, which gives the independence that makes a second check worth having.
