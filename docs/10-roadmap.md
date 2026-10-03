# 10 — Roadmap & Open Questions

Phases are gated by **exit criteria**, not dates. Each phase is also a learning milestone: the "You'll learn" rows map to the AI concepts in the other docs.

## Phase 0 — Design & research ✅ (this repo)
Architecture, requirements, research, validation design.

## Phase 1 — Thin vertical slice on the MacBook (in progress)

**Status:** the code is built and tested in demo mode. See [phase1-getting-started.md](phase1-getting-started.md).

| Done | Waiting on |
|---|---|
| Two-pass orchestrator, hybrid retrieval, verification pipeline, calculators, example formulary, 17 draft feasibility rules, audit log, GUI, CLI, SpaceOSCE schema + 3 draft cases, model bench, Ollama native API with context-window guards and thinking, reasoning summaries for clinical review, summary and patient-claim checks, consult mode M1 (`spacedoc consult`: questions toward a differential, red flags, exam checks, turn timing, consult record), 123 tests + CI, open-access corpus manifest (9 sources, hashes checked) | Real-model runs on the Mac (`spacedoc bench`); corpus ingest with real embeddings (`spacedoc corpus ingest`); clinician review of rules, formulary and cases; ~30 approved cases |

**Goal:** one question type (general medical Q&A plus a simple differential) working end-to-end, *with* the verification layer, measured by a first harness.

| Work item | Components |
|---|---|
| Local LLM server behind an OpenAI-compatible API; benchmark 3–4 candidate models | [02](02-local-inference.md) |
| Ingest ~30–50 tier-B/C documents (NASA-STD-3001, HRP evidence reports, open guidelines) with metadata; hybrid retrieval + reranker | C-03, [04](04-knowledge-and-training.md) |
| Environment context object; 20–30 feasibility rules | C-12, L6 |
| Canonical JSON answer + cite-or-drop + MiniCheck verification | C-02, C-11 (L1, L2, L4) |
| Minimal formulary table and 3–5 calculators with unit tests | C-06, C-07 |
| Command-line / simple web chat; audit log | C-01, C-13 |
| SpaceOSCE v0: 30 cases written with your clinicians; runner + automatic metrics | [08](08-validation-framework.md) |

**Exit criteria:**
- Numeric integrity 100%
- Zero unflagged environment or formulary violations on the case set
- Measured claim-support rate and Dx top-3 baseline
- Latency measured on the M4

**You'll learn:** LLM serving, quantization tradeoffs, embeddings and RAG, structured output, tool calling, evaluation basics.

## Phase 2 — Records, monitoring & the first mini
| Work item | Components |
|---|---|
| Crew health record schema; synthetic crew with preflight baselines | C-08 |
| Vitals simulator (normal adaptation + injected anomalies); EWMA/CUSUM trend monitor; alert tiers | C-09 |
| MQTT device bus + mini contract v0.1 | C-10, [05](05-spacedoc-minis.md) |
| First mini (recommended: **ECG rhythm** on PTB-XL + MIT-BIH, trained on the desktop GPU) with SQI, OOD, calibration | Mini |
| Uncertainty layer: self-consistency, conformal sets for the differential | L5 |

**Exit criteria:**
- The mini meets its AUROC and ECE targets, with correct SQI gating.
- The trend monitor detects injected drifts within a target delay at an acceptable false-alarm rate.

**You'll learn:** CNN training, calibration, OOD detection, time-series anomaly detection, MQTT and IoT patterns.

## Phase 3 — Interaction & clinical validation
| Work item | Components |
|---|---|
| Role profiles, renderer + re-verification | C-01, [07](07-adaptive-interaction.md) |
| Protocol engine with 5–10 emergency protocols in microgravity and partial-g variants (clinician-authored) | C-05 |
| Rater app with blinding and κ/ICC computation | [08](08-validation-framework.md) §5 |
| SpaceOSCE v1 (~150+ cases, locked held-out split) | |
| Crossover study: residents/students with vs without SpaceDoc | [08](08-validation-framework.md) §4 |

**Exit criteria:**
- Inter-rater reliability ≥ target
- Statistically supported decision-support benefit, or clear learnings if not
- Harmful-recommendation rate at or below the pre-registered target

**You'll learn:** human-AI evaluation design, reliability statistics, conversational UX, prompt engineering at scale.

## Phase 4 — Hardening & analog deployment
- Containerized deployment (e.g. Podman) on edge hardware; power, thermal and fault-injection testing
- Safety case v1, FMEA review, IEC 62304-style documentation
- Earth-link packetizer and blackout mode
- Analog mission partnership (MDRS / HERA / CHAPEA-class); proposal (e.g. a TRISH or SBIR call)

---

## Open questions

### For your clinicians
1. Which **20–30 conditions** should SpaceOSCE v0 cover first? Suggestion: the most frequent in-flight conditions plus 5 must-not-miss emergencies.
2. What **harmful-action "never events"** should fail a case automatically?
3. What **rubric anchors** (1–5 definitions) can the team agree on for each global axis?
4. What **protocol set** is highest priority for emergency mode (e.g. cardiac arrest, anaphylaxis, airway obstruction, severe bleeding, toxic exposure, eye injury)?
5. Which **physiological trends** matter most to the physiologists for long-duration monitoring, and what baseline data exists?

### For you (project decisions)
1. **Licensing:** an open-source license for SpaceDoc (e.g. Apache 2.0) vs keeping it closed for a future product?
2. **Textbook access:** can you or your institution license space-medicine textbooks for the knowledge base?
3. **Mission formulary:** use the public ISS formulary information as a starting "standard transit kit", or define a hypothetical exploration kit with clinicians?
4. **Partnerships:** reach out to TRISH / NASA ExMC / analog operators early (Phase 1–2) or after first results?
5. **Institutional review:** if the clinician studies go beyond internal testing (e.g. publishable research with human participants), IRB review will likely be needed. Your CITI training is a first step.
