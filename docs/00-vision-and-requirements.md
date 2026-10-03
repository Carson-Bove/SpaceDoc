# 00 — Vision & Requirements

## 1. Problem

On the ISS, a sick astronaut can talk to a flight surgeon with almost no delay, and emergency return to Earth is measured in hours [[R6](references.md#r6)]. That safety net thins out as missions go further:

- **Lunar missions:** the round-trip light time is only ~2.6 s, but getting back to Earth takes days.
- **Mars:** one-way delays range from ~3 to ~23 minutes [[R9](references.md#r9)], so a round trip near Mars can take up to ~50 minutes [[R7](references.md#r7)]. Communication can also be interrupted altogether (blackouts), and bandwidth is limited [[R7](references.md#r7)]. There is no evacuation at all.

The crew must therefore manage medical events autonomously. Care is led by a Crew Medical Officer (CMO), who is often not a physician [[R5](references.md#r5)]; CMO medical training is measured in tens of hours: about 40 hours in NASA's 2017 evidence report [[R7](references.md#r7)] and a minimum of 80 hours according to a 2020 CPR guideline [[R9](references.md#r9)].

NASA's evidence report on in-flight medical conditions lists the lack of computed medical decision support for exploration missions as an open gap [[R7](references.md#r7)]. On the AI side, conversational diagnostic systems have been evaluated in OSCE-style studies with patient actors [[R1](references.md#r1)]. SpaceDoc builds on these ideas in the open. It emphasizes four things: device-level models (minis), an explicit hallucination-prevention layer, long-term per-crewmember monitoring, and role-adaptive communication. NASA and industry work on medical assistants that we could not yet read in full is listed in the [research backlog](research-backlog.md).

## 2. Users (personas)

| Persona | Medical literacy | Typical needs | Authority |
|---|---|---|---|
| **CMO** (trained crew, often a non-physician) | Moderate to high | Differentials, protocols, dosing support, documentation | Can administer and authorize treatment within protocol |
| **Physician-astronaut** (if aboard) | Expert | Terse clinical decision support, evidence, second opinion | Full |
| **Crewmember / patient** | Varies (engineer, geologist, pilot) | Symptom intake, self-care guidance, understanding their own data | Own data only |
| **Assisting crewmember** (e.g. engineer helping in an emergency) | Low to moderate | Clear step-by-step instructions under stress | Acts under CMO direction |
| **Commander** | Varies | Fitness-for-duty summaries and mission-impact estimates, *without* private details | Operational summaries only |
| **Earth flight surgeon** (asynchronous) | Expert | Concise case packets (SBAR), raw data, audit trail | Advisory, time-delayed |

## 3. Mission tiers (environment as a first-class variable)

| Tier | Example | Gravity | One-way comm delay | Evacuation to definitive care | Resupply |
|---|---|---|---|---|---|
| **T1 LEO** | ISS | microgravity (~0 g) | < 1 s (relay satellite latency) | hours | regular |
| **T2 Cislunar** | Gateway, Orion | ~0 g | ~1.3 s | days | rare |
| **T3 Lunar surface** | Artemis | 0.17 g (1/6) | ~1.3 s, with relay gaps possible | days | rare |
| **T4 Deep-space transit** | Earth–Mars cruise | ~0 g | minutes → up to ~23 min | none (months) | none |
| **T5 Mars surface** | Mars base | 0.38 g (3/8) | ~3–23 min; blackouts possible | none | none |

The evacuation and resupply values are approximate and for design only. NASA-STD-3001 Volume 1 once defined graded **Levels of Care**. Since Revision B (2022) these have been replaced by **Health and Medical Care** technical requirements. Under these, the onboard medical capability is set from an evidence-based probabilistic risk assessment and the mission parameters, including mission duration and expected return time to Earth, and must include a means of providing autonomous medical care [[R5](references.md#r5)]. SpaceDoc's autonomy settings should scale with the tier in the same way.

## 4. Requirements

Requirement IDs are referenced from the architecture ([01](01-architecture.md)) and validation ([08](08-validation-framework.md)) docs, so each requirement traces to a component and a test.

### 4.1 Functional (FR)

| ID | Requirement |
|---|---|
| FR-01 | Answer general medical questions with source citations. |
| FR-02 | Conduct structured symptom intake (history of present illness, review of systems) adapted to the user. |
| FR-03 | Produce a ranked differential diagnosis with reasoning, supporting and refuting evidence, and suggested discriminating tests that are **feasible aboard**. |
| FR-04 | Provide treatment plans limited to the **onboard formulary and equipment**, with alternatives when items are depleted or expired. |
| FR-05 | Guide emergency response with pre-validated, environment-adapted protocols (e.g. microgravity CPR positioning). |
| FR-06 | Ingest device outputs through the SpaceDoc mini contract and request new measurements when needed. |
| FR-07 | Maintain a longitudinal crew health record: encounters, observations, medications, procedures, baselines. |
| FR-08 | Continuously monitor vitals and trends against personal baselines and raise tiered alerts. |
| FR-09 | Identify the user and adapt vocabulary and detail to their role and medical literacy. |
| FR-10 | Generate delay-tolerant handoff packets (SBAR plus data) for Earth support, and ingest their replies. |
| FR-11 | Track formulary inventory, expiry dates and consumable use. |
| FR-12 | Draft documentation (encounter notes) for CMO review and sign-off. |
| FR-13 | Explain its reasoning and sources on request ("why?"). |
| FR-14 | Support voice interaction for hands-busy situations. |

### 4.2 Safety (SR)

| ID | Requirement |
|---|---|
| SR-01 | Every factual medical claim shown to a user must be traceable to a source in the knowledge base or the patient record. |
| SR-02 | All numeric clinical values (doses, rates, thresholds, scores) must come from deterministic, tested code or validated tables, never from free LLM generation. |
| SR-03 | Never recommend a drug, device, test or procedure that is unavailable or infeasible in the current environment without flagging it explicitly as such. |
| SR-04 | When confidence or support is insufficient, abstain and say so, and state what information would resolve the uncertainty. |
| SR-05 | High-risk actions (invasive procedures, controlled or high-alert medications) require explicit human confirmation by an authorized role. |
| SR-06 | Emergency protocols must be deterministic and pre-validated. The LLM may explain or navigate them but not alter their steps. |
| SR-07 | Device-model (mini) findings must carry calibrated confidence, a signal-quality index and an out-of-distribution flag. Low-quality findings must not be presented as diagnostic. |
| SR-08 | Record every input, retrieval, tool call, model version and output in a tamper-evident audit log. |
| SR-09 | Role adaptation must not change clinical content. The simplified text must be verified against the canonical answer. |
| SR-10 | Degrade gracefully. If the LLM is unavailable, protocols, records, monitoring and alarms keep working. |
| SR-11 | Treat retrieved documents and device data as data, not instructions (prompt-injection resistance). |
| SR-12 | Enforce privacy: medical details are visible only to authorized roles. |

### 4.3 Non-functional (NFR)

| ID | Requirement |
|---|---|
| NFR-01 | Runs fully offline on the reference dev hardware (16 GB Apple M4 laptop), and is portable to edge or flight hardware. |
| NFR-02 | Emergency protocol step display latency < 1 s (no LLM in the critical path). |
| NFR-03 | Conversational response: first token < 3 s and full verified answer < 30 s on reference hardware (targets to be measured in Phase 1). |
| NFR-04 | Knowledge base and models are updatable by the Earth uplink with versioning and rollback. |
| NFR-05 | All components are containerized or packaged reproducibly (same model, same output settings). |
| NFR-06 | Power- and thermal-aware: supports a low-power mode with smaller models. |
| NFR-07 | Explainable: every answer can show its sources and tool calls. |
| NFR-08 | Data model is interoperable with terrestrial EHR standards (FHIR-inspired). |

## 5. Out of scope (for now)

- Autonomous treatment without a human in the loop.
- Surgical guidance beyond published emergency procedures.
- Behavioral-health counseling as a primary function. It is flagged as future work that needs a specialist design.
- Certification for flight. Phase 0–3 target research and analog use.

---

## How this works in AI systems: what "agentic" means

A plain **LLM** is a text predictor: you give it text and it continues it. An **agent** wraps an LLM in a loop:

1. **Observe:** read the user's message plus relevant state (patient record, vitals, environment).
2. **Think:** the LLM decides what to do next.
3. **Act:** instead of only replying, the LLM can call **tools**, which are ordinary functions you write, such as `get_vitals(crew_id, hours=72)`, `search_knowledge("kidney stone microgravity")` or `calc_dose(drug, weight_kg)`.
4. The tool results are fed back in, and the loop repeats until the agent produces a final answer.

In engineering terms, the LLM is a **supervisory controller** and the tools are its **actuators and sensors**. Safety comes from two things: limiting which actuators it can reach, and checking its commands before they execute. That is exactly what the requirements above (SR-02, SR-05, SR-06) do.
