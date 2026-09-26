# SpaceDoc

**A local, offline-capable medical assistant for crews that are too far from Earth to call a doctor.**

SpaceDoc supports the Crew Medical Officer (CMO) and the rest of the crew on long-duration and non-terran missions (lunar surface, deep-space transit, Mars), where communication delay and the lack of evacuation options make Earth-based medical support slow or unavailable.

> **Status:** Phase 1 in progress. There is a working prototype you can run locally (demo mode needs no model); see [Getting started](docs/phase1-getting-started.md).
>
> **Not for clinical use.** SpaceDoc is a research prototype. Nothing in this repository has been validated for diagnosing or treating anyone.

## What SpaceDoc does

| Capability | Summary |
|---|---|
| Medical Q&A | Answers general medical questions, grounded in cited sources |
| Diagnostic support | Builds a ranked differential diagnosis and explains why |
| Emergency protocols | Walks the crew through validated, environment-adapted checklists |
| Equipment integration | Uses onboard devices through **SpaceDoc minis**, small device-level neural nets (e.g. on an ECG) that pre-interpret signals |
| Crew health records | Maintains a longitudinal record for each crewmember |
| Long-term monitoring | Tracks vitals and trends against each person's own baseline and flags drift early |
| Role-aware communication | Speaks clinically to the CMO and explains plainly to an engineer, without changing the medical facts |
| Hallucination prevention | A layered verification system: no uncited claims, no numbers from the LLM, no drugs or tests that aren't possible aboard |
| Environment awareness | Microgravity, 1/6 g, 3/8 g, communication delay, onboard formulary and equipment are first-class inputs |

## Documentation map

| # | Document | What it covers |
|---|---|---|
| 00 | [Vision & requirements](docs/00-vision-and-requirements.md) | Users, mission tiers, numbered requirements |
| 01 | [Architecture](docs/01-architecture.md) | System components, data flow, the key design principles |
| 02 | [Local inference](docs/02-local-inference.md) | Running it on a MacBook Air / desktop PC; model choices; memory math |
| 03 | [Hallucination prevention](docs/03-hallucination-prevention.md) | The defense-in-depth verification stack |
| 04 | [Knowledge & training](docs/04-knowledge-and-training.md) | Corpus, RAG versus fine-tuning, the aerospace-medicine context model |
| 05 | [SpaceDoc minis](docs/05-spacedoc-minis.md) | Generic device-model contract, candidate devices, datasets |
| 06 | [Records & monitoring](docs/06-records-and-monitoring.md) | Crew health record, baselines, trend detection, alerting |
| 07 | [Adaptive interaction](docs/07-adaptive-interaction.md) | Roles, language adaptation, emergency mode, Earth handoff |
| 08 | [Validation framework](docs/08-validation-framework.md) | How to *quantify* performance: SpaceOSCE, rubrics, rater reliability |
| 09 | [Safety & regulatory](docs/09-safety-and-regulatory.md) | Hazard analysis, FDA/IEC/NASA standards, analog missions, funding |
| 10 | [Roadmap](docs/10-roadmap.md) | Phased plan and open questions |
| — | [Getting started (Phase 1)](docs/phase1-getting-started.md) | Install, demo mode, real models, bench |
| — | [SpaceOSCE authoring guide](docs/spaceosce-authoring-guide.md) | For clinicians writing evaluation cases |
| — | [Glossary](docs/glossary.md) · [References](docs/references.md) · [Research backlog](docs/research-backlog.md) | Terms, sources, and sources awaiting full-text review |

Each document ends with a **"How this works in AI systems"** section. These explain the underlying AI or ML concept for an engineer who is new to machine learning.

## Design principles

1. **The LLM is never the source of truth.** It reasons and writes. Facts come from cited sources, numbers from deterministic code, and patient data from the record.
2. **Emergencies run on checklists, not improvisation.** Time-critical care follows pre-validated protocols. The AI helps navigate them; it does not invent them.
3. **Every claim is checked before the user sees it.** When the system can't support an answer, it says so.
4. **Environment is a first-class input.** A correct answer on Earth can be wrong on Mars.
5. **Same facts, different words.** How much a user understands changes the presentation, never the medical content.
6. **Runs offline, on modest hardware.**

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
spacedoc serve --demo      # http://127.0.0.1:8765, scripted demo, no model needed
pytest -q
```
