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
spacedoc consult --demo        # a scripted consult: questions, then a checked assessment
pytest -q                      # 125 tests
```

In the demo flank-pain answer, the verification layer should:

| Scripted mistake | What catches it |
|---|---|
| Invented statistic ("95% of cases") | `NUM-UNTRACED`: the number is not in the cited source |
| Claim the source doesn't make ("definitive cure") | The grounding check |
| Expired drug (tamsulosin) | `FORM-EXPIRED` |
| Evacuation on a deep-space mission | `ENV-EVACUATE` |
| Summary repeats the evacuation | `SUMMARY-TRIMMED`: the summary may only say what the checked answer below it says |
| Corrupted document with "ignore all previous instructions" | `INJECTION`: the document is excluded before the model sees it |

In the demo, the acetaminophen dose comes from the calculator, not the model: 15 mg/kg × 78 kg, capped at 1000 mg. The dose is flagged as not clinician-validated.

The flank-pain answer also has scripted thinking notes. Open **Model reasoning (for clinical review)** under the answer and press **Summarize** to see the review panel described in [Reviewing the model's reasoning](#reviewing-the-models-reasoning).

## 2. Run it with real models on the MacBook Air (16 GB)

### Install Ollama and pull models

If Ollama is not installed yet, install the macOS app from ollama.com. Then pull these models:

```bash
ollama pull qwen3:8b               # orchestrator: 8.2B, Q4_K_M, 5.2 GB
ollama pull qwen3-embedding:0.6b   # embeddings for retrieval: 639 MB
ollama pull bespoke-minicheck:7b   # grounding checker: 7.7B, Q4_K_M, 4.7 GB (Ollama swaps it in/out)
```

**Tags checked on ollama.com in Sept 2026.** All three tags exist, and these are the values in `spacedoc.toml`. Two details:
- Always pull `qwen3-embedding:0.6b` by its size tag. The bare `qwen3-embedding` (`latest`) is the 8B model (4.7 GB).
- `bespoke-minicheck:7b` is the same file as `bespoke-minicheck:latest`. Pinning the size tag keeps the checker from changing silently if `latest` moves.

Ollama tags do change. If a `pull` fails, search the Ollama library for the model and put the working tag in `spacedoc.toml`.

**Memory.** On 16 GB, Ollama holds only some models in memory at once and swaps the others in. Expect the first question after a switch to be slower. Close other large apps while testing.

### Context window and thinking

SpaceDoc talks to Ollama through its native API (`llm_backend = "ollama"`), not the OpenAI-compatible `/v1` endpoint. Only the native API lets each request set the context window and `top_k`. For llama.cpp or LM Studio, set `llm_backend = "openai"` and put `/v1` in `llm_base_url`.

**Context window.** Ollama's default context window is 4,096 tokens on machines with less than 24 GiB of VRAM ([Ollama docs: context length](https://github.com/ollama/ollama/blob/main/docs/context-length.mdx)). SpaceDoc's first pass (system prompt, formulary, six passages, patient record) measured about 3,300 tokens before the model writes anything, and the second pass about 4,000, so the default is too small. When a prompt does not fit, Ollama normally drops text from it without an error. SpaceDoc guards against this in three ways:
- It sets `num_ctx` on every request: `chat_num_ctx = 12288` for the orchestrator, `checker_num_ctx = 4096` for the grounding checker.
- Before each call it estimates the tokens needed (prompt + maximum answer). If six passages do not fit, it drops the lowest-ranked ones and records `CONTEXT-TRIM`. If the second pass does not fit, it keeps the first-pass answer without calculator references and records `FINALIZE-SKIPPED`.
- It asks Ollama to refuse an over-long prompt instead of shortening it (`truncate: false`, `shift: false`). Older Ollama versions ignore these fields, so SpaceDoc also compares the prompt tokens Ollama reports with the prompt's length. A refusal or a shortened prompt becomes a `MODEL-ERROR` abstention, never a silent answer from half a prompt.

`chat_num_ctx` must be larger than the prompt plus `draft_max_tokens`. If you lower it (for example to save memory), lower `draft_max_tokens` too, or SpaceDoc will drop passages to make room.

**Thinking.** Qwen3 can write private reasoning notes ("thinking") before its answer. SpaceDoc turns thinking on for the first pass (`think_draft = true`), where the model weighs the findings and the sources. It turns thinking off for the second pass (`think_finalize = false`), which only inserts calculator results. Qwen3's model card recommends different sampling for each mode and warns against greedy (temperature 0) decoding with thinking, which can cause endless repetition ([Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B)). `sampling_thinking` and `sampling_plain` in `spacedoc.toml` hold those settings. `seed = 42` makes runs more repeatable, though not exactly: GPU arithmetic and Ollama updates can still change the output.

Thinking costs time: `draft_max_tokens = 6144` leaves room for the notes plus the JSON answer. At 15–25 tokens/s on the MacBook Air, a long first pass can take 4–7 minutes, so `request_timeout_s = 900` allows each model call up to 15 minutes. If the model hits that limit, SpaceDoc records `OUTPUT-LIMIT` and retries once without the cut-off reply. The notes are never shown to the crew. They are saved in the audit log for clinical review (below).

**Search queries.** Qwen3-Embedding expects each search query to start with a one-sentence task instruction (passages are embedded without one). Its model card reports a 1–5% gain from instructions ([Qwen3-Embedding-0.6B model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)). The instruction is `embed_query_instruction` in `spacedoc.toml`. Changing it does not require re-ingesting the corpus.

### Build the knowledge base

The corpus manifest (`corpus/manifest.yaml`) lists open-access sources with URLs, licenses and hashes. Then:

```bash
spacedoc corpus fetch    # downloads into corpus/files/ (not committed to git)
spacedoc corpus ingest   # chunks + embeds into spacedoc.db
```

The manifest holds only sources that were read in full and whose license allows this use (US Government public domain or CC BY). Candidates that are still unread, or whose license is non-commercial or no-derivatives, are listed in [research-backlog.md](research-backlog.md). You can also add your own PDFs:
1. Put the file in `corpus/files/`.
2. Add an entry to `corpus/manifest.yaml` (see the field list in the file).
3. Run `spacedoc corpus ingest`.

### Use it

```bash
spacedoc serve                                  # GUI on http://127.0.0.1:8765
spacedoc ask "..." --tier T4 --patient me.yaml  # CLI
spacedoc audit verify                           # check the audit log hasn't been altered
```

### Run a consult

A consult is a short conversation: SpaceDoc asks one or two questions at a time to build a differential diagnosis, then gives the full checked assessment. The design is in [consult-mode-design.md](consult-mode-design.md).

**In the browser:** `spacedoc serve`, then choose the **Consult** tab. Pick who is using SpaceDoc and who the patient is, real or practice, and press **Start consult**.
- The **working list** on the left updates every turn and marks what is new or changed. It is labelled *not yet checked*, and everyone sees it.
- Yes/no questions have **Yes / No / Not sure** buttons, and exams have a **Result** box. Both fill in the answer box; nothing is sent until you press **Send** (or Cmd+Enter), so you can add detail first.
- A **red-flag card** pauses the consult. Choose **Checked assessment now**, or **Continue questions** if it is not an emergency.
- **Assess now**, **Consult record** (view or download the record) and **End consult** (saves the record to `audit/consults/`) are on the left.

**In Terminal:**

```bash
spacedoc consult --tier T1                  # asks who you are, who the patient is, real or practice
spacedoc consult --user C1 --patient C3 --practice --scenario SO-0104 --tier T1
spacedoc consult --deep-log ...             # thinking on every turn (slower), see below
```

- **Who's who.** The crew roster in `data/crew/roster.yaml` is **synthetic** (C1 is the CMO). Pick yourself and the patient by number or crew ID; `s` means you are the patient, `u` someone not on the roster. When you are not the patient, SpaceDoc phrases questions for you to ask them, and you type their answers.
- **Each turn** shows SpaceDoc's working list (labelled *not yet checked*), up to two questions with the reason for each, and any exams. Exams that need equipment not aboard, or that don't work in the environment, are marked ✗.
- **Quick answers.** When every question is yes/no, type `y`, `n` or `?` (one per question, e.g. `y n`).
- **Red flags.** Your words are checked against a draft list of urgent signs (`data/rules/red_flags.yaml`, **not yet clinician-reviewed**). A match pauses the consult and shows immediate steps; choose an immediate checked assessment or continue if it is not an emergency.
- **Commands:** `/assess` (assess now), `/record` (show the consult record so far), `/quit`. SpaceDoc also assesses on its own when it has enough, or after 8 rounds (`consult_max_rounds`).
- **Timing.** Each turn ends with a line like `⏱ 11.8 s (reading 1.2 s; writing 10.3 s, 182 tokens)`. When you quit, SpaceDoc prints the median turn time. The target is 10–15 s per turn; the first turn is slower while the model loads.
- **Deep log** (`--deep-log`) turns thinking on for every turn, so the record has full thinking notes. Turns get slower, so each one also shows `about N s without deep log (estimated)`: the writing time minus the share spent on the notes. Measure the real number with a normal run.
- **The consult record** is saved to `audit/consults/<consult id>.md` when you quit. It lists every turn, the working list as it changed, the reason for each question, red flags, exam checks, thinking notes (deep log), the assessment and the timings. Every turn is also in the audit log.

### Reviewing the model's reasoning

When thinking is on, each answer's notes are saved in the audit log with the answer. They are for clinicians reviewing SpaceDoc, not for the crew.
- **Web page.** Under an answer, open **Model reasoning (for clinical review)**. **Summarize** asks the orchestrator model to condense the notes into: findings weighed, diagnoses considered (favored, considered, ruled out), sources relied on, assumptions, uncertainties, and points for the reviewer. **Show full notes** shows the notes themselves. A summary is made once per answer and saved in the audit log (event `reasoning_summary`).
- **Evaluation reports.** `spacedoc eval run` adds a "Reasoning summaries (for clinical review)" section to `report.md`, one per answer that has notes. This costs one extra model call per answer; `--no-summaries` skips it. `spacedoc bench` never makes summaries.

The summary is labeled as unverified everywhere it appears. It is the model's own account of its reasoning, summarized by the same model. Neither the notes nor the summary are guaranteed to reflect how the answer was actually produced. Use them to spot reasoning worth questioning (the "points for the reviewer" list is built for this), not as evidence that an answer is right.

### Confirm the setup on the Mac

Run these once after pulling the models and building the knowledge base. Write down what you see; it is the baseline for later runs.

1. **Ollama version.** `ollama --version`. Record it with your results, since context and thinking behavior change between versions.
2. **Models present.** `ollama list` should show `qwen3:8b`, `qwen3-embedding:0.6b` and `bespoke-minicheck:7b`.
3. **Thinking supported.** Ask Ollama what the model can do:
   ```bash
   curl -s http://localhost:11434/api/show -d '{"model": "qwen3:8b"}' \
     | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("capabilities"), d.get("thinking"))'
   ```
   The capabilities list should include `thinking`.
4. **Count Ollama's truncation warnings before the test.** `grep -c "truncating input prompt" ~/.ollama/logs/server.log` (the Mac log location, per Ollama's troubleshooting guide; 0 if the log is new).
5. **Ask one real question.** `spacedoc ask "Sharp right flank pain that moves toward my groin" --tier T4`. The first run is slow while the models load.
6. **Context in use.** Straight after the answer, run `ollama ps`. The `CONTEXT` column should read 12288 for `qwen3:8b` (and 4096 for `bespoke-minicheck:7b` if it is still loaded). `PROCESSOR` should read `100% GPU`. A CPU share means the model did not fit in GPU memory; lower `chat_num_ctx` and `draft_max_tokens` together.
7. **No new truncation.** Repeat step 4. The count should not have gone up.
8. **No context findings.** The answer should have no `MODEL-ERROR`, `CONTEXT-TRIM`, `OUTPUT-LIMIT` or `FINALIZE-SKIPPED` notes. If it does, the note says which setting to change.
9. **Notes saved.** `spacedoc serve`, ask the same question, open **Model reasoning (for clinical review)** and press **Show full notes**. Notes should be there. If the panel says thinking was off, check step 3 and `think_draft`.
10. **Audit chain.** `spacedoc audit verify` should print `Audit chain intact.`

## 3. Choose the orchestrator model (desktop or Mac)

`spacedoc bench` runs the same cases through several models and prints a comparison table:

```bash
ollama pull gemma4:e4b    # example candidate: Q4_K_M, 9.6 GB
ollama pull medgemma:4b   # example candidate: MedGemma 1 (not 1.5), 4.3B, Q4_K_M, 3.3 GB
spacedoc bench qwen3:8b gemma4:e4b medgemma:4b --repeats 3
```

Both tags were confirmed on ollama.com in Sept 2026. `--thinking` controls the first pass: `config` (default, uses `think_draft`), `on`, `off`, or `both`, which runs each model twice so you can compare the modes. The Qwen3 report found that thinking slightly lowered some long-context scores [[R23](references.md#r23)], so measure it on SpaceDoc's cases rather than assume. Models that cannot think (such as `medgemma:4b`) are asked once with thinking, refuse, and are then run without it.

Things to know before benchmarking:
- `gemma4:e4b` is 9.6 GB even at 4-bit. On the 16 GB Mac it leaves no room for the grounding checker. On the desktop it is larger than the 8 GB of VRAM, so part of it runs from CPU RAM, which is slower. `gemma4:e4b-it-qat` (6.1 GB) is a smaller variant to try.
- `medgemma:4b` is MedGemma version 1. The Ollama library lists MedGemma 1.5 separately as `medgemma1.5:4b` (3.3 GB).

Output format:

| model | schema_adherence | claim_support_rate | dx_top3 | abstention_correct | harmful | latency_s | tokens_per_s |
|---|---|---|---|---|---|---|---|

- **schema_adherence:** how often the model's first reply was valid JSON for the answer schema.
- **claim_support_rate:** the share of sourced claims the grounding checker confirmed.

Both depend on the model *and* the corpus, so re-run the bench after changing either. With only 3 draft cases, treat the numbers as a smoke test, not a result. Meaningful comparisons need the clinician-approved case bank.

**Desktop (8 GB VRAM).** Install Ollama for Windows/Linux. An 8B model at 4-bit fits on the GPU, so the desktop is the faster machine for overnight `bench` and `eval run --repeats N` jobs. Point `llm_base_url` in `spacedoc.toml` at the desktop (for example `http://192.168.1.20:11434`) to run evaluations from the Mac against it. Ollama listens only on 127.0.0.1 by default; set `OLLAMA_HOST=0.0.0.0` on the desktop so it accepts connections from the Mac, and only on a network you trust.

## 4. How a question flows through the code

```
question ─► kb/retrieve.py      hybrid search: keyword (FTS5/BM25) + vector (cosine), fused by RRF;
                                the query gets the embedding model's task instruction
         ─► verify/rules.py     screen passages for injected instructions; renumber S1..Sn
         ─► agent/orchestrator  fit passages to the context window; pass 1 (thinking on): model
                                drafts a DraftAnswer (JSON schema) + calculator requests
         ─► tools/calculators   deterministic doses/scores; weight always from the record
         ─► agent/orchestrator  pass 2 (thinking off): model finalizes, referencing calc_ids
         ─► verify/pipeline.py  cite-or-drop → numbers → grounding, one sentence at a time
                                (sources, or the patient record for patient claims) →
                                formulary/equipment/environment rules → risk gating →
                                abstain decision → summary check
         ─► audit/log.py        hash-chained record of everything above, plus the thinking notes
         ─► web/ or render/     display with badges, citations and "why this answer"
         ─► review/summary.py   on request: reasoning summary for clinical review
```

---

## How this works in AI systems: the pieces you just ran

- **Structured output.** Ollama receives the answer's JSON schema and constrains generation to match it. SpaceDoc still validates the reply with Pydantic and retries once, because small models occasionally produce schema-valid JSON with the wrong meaning. `schema_adherence` in the bench measures how often the first try parses.
- **Reciprocal-rank fusion (RRF).** Keyword search scores (BM25) and vector scores (cosine) are on different scales, so adding them is meaningless. RRF ignores the scores and only uses each result's *rank*: every list contributes `1/(60 + rank)`. A passage ranked well by both methods rises to the top. The constant 60 damps the influence of any single list.
- **Why two passes?** Letting the model call tools mid-sentence (native tool calling) is flexible but hard to audit. Phase 1 uses a fixed loop instead: draft, run the requested calculators in code, then finalize. It's less clever, but every step is deterministic and logged, which is what a safety case needs.
- **Grounding checker.** Bespoke-MiniCheck's training details are on its model card; the original MiniCheck models it is named after are described in [R17](references.md#r17). It does one job: given a document and a sentence, answer whether the document supports the sentence. It is a different model from the orchestrator, which gives the independence that makes a second check worth having. Its model card says to split multi-sentence claims into sentences first, so SpaceDoc checks each sentence separately. A sentence that no single cited passage supports is checked once more against up to three cited passages together, because a claim may combine two sources. When Ollama returns token probabilities, the claim's detail shows P(yes), the checker's confidence.
- **Checking the summary.** The one- or two-sentence summary is read first, so it is checked last: each sentence must be supported by what is shown below it (shown claims, the differential, actions that are not blocked, the patient record), and its numbers must appear there. Unsupported sentences are removed (`SUMMARY-TRIMMED`). If nothing is left, a neutral sentence replaces the summary (`SUMMARY-REPLACED`).
- **Thinking.** A thinking model writes free-form notes before its answer, then the answer itself. Ollama returns them in separate fields, so the JSON schema constrains only the answer. Thinking usually helps multi-step reasoning, but it adds latency and tokens, and the notes are not a faithful record of the computation. SpaceDoc keeps them for review and never treats them as evidence.
