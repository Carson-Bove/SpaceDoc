# 11 — Evaluation System: Simulated Missions, Scored at Scale

> **Status:** design signed off. Phase A (scenario authoring) is built in [`medsim-eval/`](../medsim-eval/): file formats, validator, NASA-sourced library and the offline Scenario Builder ([guide for clerks](scenario-builder-guide.md)). Format v0.2 reflects the clerks' first round of feedback (§6.1). Phases B–E are designed but not built. Sections marked **Decision needed** are still open. Working name: **MedSim Eval** (to be replaced by a better name later).

**The problem.** [08](08-validation-framework.md) defines how to put numbers on clinical performance with SpaceOSCE: static cases, a single-turn presentation and human raters. That is a sound base, but it misses three things a crew medical officer actually faces:

- a patient who gets **better or worse depending on what they are told to do**
- a mission that **keeps happening around the patient**: a solar particle event, a dust storm, a comm blackout, a failed piece of equipment
- the **volume** needed to see how an assistant behaves across many runs, not one

This document designs an evaluation system that closes that gap. Clerks (medical students and residents) write mission scenarios grounded in NASA's Design Reference Missions (DRMs). A **digital twin** of the patient, the vehicle and the environment runs each scenario many times, in simulated time and faster than real time. Lightweight agents score every run against a rubric, a judge summarises all of them, and clinicians review the result. The system must work with **any** digital assistant: SpaceDoc, CMO-DA, or something homegrown.

## 1. The loop

```mermaid
flowchart LR
  subgraph Authoring
    C[Clerks] -->|web form| S[Scenario + rubric files]
    P[Physiologist PhD] -.reviews physiology.-> S
    DRM[(DRM library<br/>from IMM)] --> S
    HAB[(Habitat profiles)] --> S
    CL[(CLiFFs<br/>100 conditions)] --> S
  end
  subgraph Eval["MedSim Eval (runs locally)"]
    TW[Digital twin<br/>physiology · vehicle · environment · clock]
    UA[User agent<br/>plays the crewmember]
    SC[Scoring agent<br/>one rubric per run]
    JU[Judging agent<br/>all runs → summary]
    FB[Feedback agent]
  end
  DA[[Digital assistant under test<br/>SpaceDoc / CMO-DA / other]]
  S --> TW
  UA <-->|conversation| DA
  DA <-->|MCP tools: vitals, exams, tests, treatments| TW
  UA <--> TW
  DA -->|transcript + tool log| SC
  TW -->|state log| SC
  SC -->|scored rubrics × N runs| JU
  CL --> JU
  JU -->|summary + anomaly links| R[Clinician review<br/>in the viewer]
  R --> FB
  JU --> FB
  FB --> MR[Medical report]
  FB --> TR[Technical report]
```

How this maps to the whiteboard:

| Whiteboard | Here |
|---|---|
| 5 events: LEO, cislunar, lunar, deep space / Mars transit, Mars surface | The 5 mission environments (T1–T5, [00](00-vision-and-requirements.md)). Each DRM belongs to one or more |
| DRMs for LEO, CL, L, D-T, M → Scoring Template | DRM library (§4.1) and the generalized rubric (§5) |
| Clinicians: Build scenarios / templates, Scoring Review | Clerks author in the form (§6). Review happens in the viewer (§9.3) |
| CMODA, "Runs sims", "log sent to scoring agent" | Any assistant behind the adapter (§8) |
| Simulation engine: Physiology sim + User Agent | Digital twin (§7) and user agent (§9.1) |
| Scoring → Judging → Feedback agents | §9 |
| Outside info: IMM, CLiFF, journals | DRM library, CLiFF condition data and the corpus. These ground both the twin and the judge |

## 2. Principles

1. **Works with any assistant.** The harness never imports the assistant's code. It talks to the assistant through a small adapter and an MCP tool surface (§8). SpaceDoc gets no special access.
2. **Local only.** Every model (user agent, scorer, judge, feedback agent) runs on local hardware. No cloud API calls.
3. **Grounded in NASA's own models.** Missions come from the IMM's DRMs. Condition behaviour comes from the IMM's Clinical Finding Forms (CLiFFs). Where we invent something, we label it as an assumption.
4. **Simulated time, not real time.** The clock jumps ahead whenever nothing is happening, so a 10-day course of antibiotics runs in seconds.
5. **Reproducible.** Every run has a seed. Same scenario + same seed + same assistant version = same twin behaviour, so a strange run can be replayed exactly.
6. **Every score points at evidence.** A rubric item is never marked without a pointer to the transcript turn or twin event that justifies it. This is what makes the anomaly viewer possible.
7. **One number never hides a failure.** Safety gates, checklists, domain ratings and patient outcome are reported side by side. A composite score is optional and is never the headline.

## 3. People

| Role | Who | Does |
|---|---|---|
| **Author** | Clerks (~40 / year, medical students and residents) | Write scenarios and scenario-specific rubric items. Run scenarios by hand to sanity-check them |
| **Peer reviewer** | A second clerk | Checks clinical accuracy and that the rubric matches the scenario |
| **Physiology reviewer** | PhD physiologist | Reviews scenarios flagged for detailed physiology. Owns the twin's condition models |
| **Clinical lead** | Attending physicians, light touch | Adjudicates disputes. Signs off the generalized rubric. Spot-checks judge summaries |
| **Engineering** | Us | Builds and maintains the harness, the twin and the adapters |

Forty clerks a year is also the **human rater pool** needed to validate the automated scorer and judge against people (§9.4).

## 4. Data model

Each file type has a published JSON Schema ([`medsim-eval/schemas/`](../medsim-eval/schemas/)). The form writes scenarios and rubrics; everything else is library data that ships with the package. All files live in git.

```
Library (shared)                                   Authored per case (clerks)
────────────────                                   ──────────────────────────
environments ── one representative DRM phase each  Scenario ── a medical case, no mission:
DRMs ──< phases ── habitat profiles (kits)            │  patient (roster crewmember + chart for this case)
conditions (118 CLiFFs: course, where it happens)     │  condition, where it can happen, course of illness
crew roster (20 fictional astronauts)                 │  speaker (who talks, how well), time-critical rule
physiology (normal ranges, in-flight changes)         │  correct answer (diagnosis, etiology, differential)
symptoms (ICD-10-CM), encyclopedia                    │
base rubric (gates, domains, standard items)       Rubric ── checklist items for this case
```

**A scenario no longer names a mission.** The clerks' main concern with v0.1 was too many options, and the DRM choice is something the system can do itself. A scenario says where the case *can* happen; the runner places it in each of those environments using that environment's representative DRM phase, its kit and its comm delay. One case is therefore tested in several environments without the clerk writing it several times. The default batch uses LEO, deep-space transit and the Mars surface (where the case allows); each environment is run in both the best and the worst course, plus 2 runs at the CLiFF's own odds: **8 runs per scenario**.

Files are **JSON** (`*.scenario.json`, `*.rubric.json`, `*.drm.json`, `*.habitat.json`, `*.crew.json`, `*.physiology.json`, `*.conditions.json`, `*.symptoms.json`, `*.encyclopedia.json`, `*.environments.json`, `*.base-rubric.json`), each with a `schema_version`. `medsim migrate` converts v0.1 scenarios and writes what it had to guess into the scenario's review notes.

### 4.1 DRM: Design Reference Mission

Public IMM documentation is better than expected. NASA's **Integrated Medical Model Documentation** page publishes the CLiFF for each condition and about 25 IMM service-request reports, each of which defines one or more DRMs [[R38](references.md#r38)]. The IMM's DRM inputs are **mission length, crew size, each crewmember's characteristics (sex, coronary artery calcium, dental crowns, contact lenses, prior abdominal surgery) and the EVA schedule** [[R37](references.md#r37)]. The longer Mars reports add **mission segments**: for example, launch staging, outbound transit, Mars loiter with surface EVAs, return and post-return staging [[R38](references.md#r38)].

The IMM has no timeline inside a mission. In its own words, "all conditions occur at launch on day one" [[R38](references.md#r38)]. Our DRMs add phases and dates so that a scenario can happen *somewhere* in the mission.

Seed library, all from public IMM sources:

| DRM (seed id) | Env | Days | Crew | EVAs | Medical resources modelled | Source |
|---|---|---|---|---|---|---|
| `imm-drm1-14d` (Shuttle-like) | T1 | 14 | 7 | 2 crew × 3 | — | [[R37](references.md#r37)] |
| `imm-drm4-iss-180d` | T1 | 180 | 6 | 2 crew × 3 | ISS MedCap | [[R37](references.md#r37)], ISS PRA update [[R38](references.md#r38)] |
| `imm-orion-21d` | T2 | 21 | 4 | 0 | Optimized Orion kit, ~9.25 kg / 23,594 cm³ (vs ISS baseline 115 kg) | Orion Medical Kit Contents [[R38](references.md#r38)] |
| `imm-artemis-7.5d` | T3 | 7.5 | 2 | 2 crew × 4 | 2.37 kg / 6,430 cm³ | 2024 Lunar [[R38](references.md#r38)] |
| `imm-artemis-27.5d` | T3 | 27.5 | 4 | 2 crew × 4 | 10.12 kg / 20,326 cm³ | 2024 Lunar [[R38](references.md#r38)] |
| `imm-artemis-32d` | T2/T3 | 32 | 4 | 2 crew × 4 | 27.7 lb (HLS 7.7 + Orion 20) | Artemis 32-day DRM [[R38](references.md#r38)] |
| `imm-cislunar-14d` | T2 | 14 | 7 | 3 crew × 2 | ISS MedCap | Five Cis-lunar Missions [[R38](references.md#r38)] |
| `imm-cislunar-{21d,42d,1y,2y}` | T2 | 21–730 | 4 | 0 | ISS MedCap | same |
| `imm-dsh-350d` | T4 | 350 | 4 | 0 | Treated / MedCap | Deep Space Habitat [[R38](references.md#r38)] |
| `imm-mars-amm-426d` | T4/T5 | 426 | 4 | 30 four-person | MedCap | Accelerated & Standard Mars [[R38](references.md#r38)] |
| `imm-mars-smm-923d` | T4/T5 | 923 | 4 | 401 four-person | MedCap | same |
| `imm-mars-pod-860d` | T4/T5 | 860 (90 / 305 / 50 / 375 / 40) | 4 | 2 crew × 15 | MedCap | Additional Mars DRMs [[R38](references.md#r38)] |
| `imm-mars-as-1030d` | T4/T5 | 1030 (90 / 200 / 500 / 200 / 40) | 4 | 2 crew × 15 | MedCap | same |
| `imm-mars-boc-1224d` | T4/T5 | 1224 (90 / 429 / 365 / 300 / 40) | 4 | 4 crew, 94 | MedCap | same |

That is 17 DRM files in [`medsim-eval/library/drms/`](../medsim-eval/library/drms/). The reports give crew, length and EVAs, but often not where each part of the mission happens. Where we had to split a mission into phases ourselves (for example the lunar surface days inside the 27.5-day Artemis DRM, or the surface stay around the EVA days in the accelerated Mars mission), the phase carries `"assumption": true` and a note saying why.

The IMM models three resource states, and the DRM records which one it assumes: **Fully treated** (continuous resupply, like ISS), **MedCap** (a fixed kit, no resupply, the closest to an exploration mission) and **Untreated** [[R38](references.md#r38)].

Excerpt from [`imm-mars-pod-860d.drm.json`](../medsim-eval/library/drms/imm-mars-pod-860d.drm.json):

```json
{
 "drm_id": "imm-mars-pod-860d",
 "source": {"doc": "IMM SR S-20210809-441 (HSRB Additional Mars DRMs)", "locator": "Segment tables and Table 1"},
 "duration_days": 860,
 "crew": [{"crew_id": "C2", "sex": "M", "cac": true, "eva": true, "crowns": false, "contacts": false, "prior_abd_surgery": false}, "…"],
 "phases": [
  {"id": "initial",  "env": "T2", "days": 90,  "habitats": ["deep-space-habitat"], "assumption": true},
  {"id": "outbound", "env": "T4", "days": 305, "habitats": ["deep-space-habitat"]},
  {"id": "loiter",   "env": "T5", "days": 50,  "habitats": ["mars-surface-habitat"],
   "eva": {"crew": ["C2", "C4"], "count": 15, "window_days": [405, 429]}},
  {"id": "return",   "env": "T4", "days": 375, "habitats": ["deep-space-habitat"]},
  {"id": "staging",  "env": "T2", "days": 40,  "habitats": ["deep-space-habitat"], "assumption": true}
 ],
 "resources": {"state": "medcap", "resupply": false}
}
```

Clerks never pick a DRM: the runner does (§4). New or edited DRMs are an engineering + clinical-lead task. Each environment's representative DRM phase is set in [`missions.environments.json`](../medsim-eval/library/environments/missions.environments.json): ISS for LEO, a 42-day cislunar orbiter, the 7.5-day Artemis surface stay, and the outbound transit and surface stay of the Mars Point of Departure mission.

### 4.2 Habitat profile: what medicine is possible where

A habitat profile describes one vehicle or base element: its gravity, its medical kit and equipment, and a **capability matrix** that says, for each procedure, whether it is available, available only in adapted form, unavailable, or unknown, **in that gravity**. Every entry carries a source or an explicit `"assumption": true`.

**What the profiles contain.** The IMM reports publish full medical kit tables: the ISS reference quantities for about 226 drugs, supplies and devices, and the optimized Orion and 7.5-day lunar kits picked from them [[R38](references.md#r38)]. These are modelling inputs and optimizer outputs, not flight manifests, but they are NASA's own numbers. The eight profiles in [`medsim-eval/library/habitats/`](../medsim-eval/library/habitats/) are built from them:

| Profile | Gravity | Kit | Basis |
|---|---|---|---|
| `iss` | 0 g | ISS reference set: 84 drugs and fluids, 142 other items; 115 kg baseline | IMM 2024 Lunar report, Table 3 |
| `orion` | 0 g | IMM optimized kit, 7.75 kg: 55 drugs, 62 items. **No ultrasound, AED, oxygen, IV fluid or restraint system** | IMM Orion Medical Kit Contents, Table 2 |
| `lunar-lander` | 0.166 g | IMM 7.5-day lunar kit, 2.37 kg: 35 drugs, 23 items | IMM 2024 Lunar, Table 3. Assigning it to the lander is our assumption |
| `cislunar-orbiter` | 0 g | ISS set, as the IMM modelled cislunar missions | IMM Five Cis-lunar Missions. No Gateway medical inventory is published |
| `deep-space-habitat` | 0 g | ISS set, no resupply | IMM Deep Space Habitat and Mars DRMs |
| `mars-surface-habitat` | 0.38 g | ISS set, no resupply | IMM Mars DRMs |
| `lunar-surface-habitat` | 0.166 g | none published | Artemis Base Camp: 2–4 crew, 1–2 month stays, "medical" among its functions [[R40](references.md#r40)] |
| `lunar-pressurized-rover` | 0.166 g | none published | Artemis Base Camp: "treatment of injuries" among its functions [[R40](references.md#r40)] |

Each profile's **capability matrix** (about 27 entries) follows from its kit: ultrasound is available only if an ultrasound machine is aboard, and so on. Gravity adds the entries that don't depend on the kit:

- **CPR:** in 0 g it needs a restrained patient or the Evetts-Russomano or handstand method [[R9](references.md#r9)]. In lunar and Mars gravity, compressions often fall short of guideline depth, more so for lighter rescuers, so rescuers should change over in under a minute [[R41](references.md#r41)].
- **Gravity-fed IV:** unavailable in 0 g; slower but possible in partial gravity (our assumption).
- **Known gaps from the CLiFFs:** no major surgery and no CT; blood tests are "unknown" because the 2023 CLiFFs assume they will be possible but no IMM kit lists the equipment.

The table and profiles are regenerated by `scripts/extract_imm_kits.py` and `scripts/build_habitats.py` when NASA updates its documents.

Since Revision B, NASA-STD-3001 sets onboard medical capability from probabilistic risk assessment and mission parameters, not from the old Levels of Care. The 2017 Levels of Care interpretation is still a useful checklist of what each level can do [[R35](references.md#r35)]. Where flight-specific detail is missing (the lunar surface habitat and the rover), profiles will be filled from it, and those entries marked as assumptions.

The existing `data/environments/T1–T5.yaml` equipment lists become a fallback for SpaceDoc only. The eval system uses habitat profiles.

### 4.3 Scenario

A medical case. Abridged from the worked example [`MSE-0001.scenario.json`](../medsim-eval/examples/MSE-0001.scenario.json):

```json
{
  "scenario_id": "MSE-0001",
  "title": "Belly pain moving to the right lower quadrant",
  "authors": [{"name": "…", "contact": "…"}],
  "symptoms": ["R10.33", "R10.31", "R11.0", "R63.0"],
  "environments": ["T1", "T2", "T3", "T4", "T5"],
  "patients": [{
    "crew_id": "C10",
    "condition": "appendicitis",
    "chart": {"past_medical": [], "past_surgical": [], "medications": [],
              "allergies": [{"agent": "penicillin", "kind": "drug", "reaction": "rash as a child"}], "nkda": false, "…": "…"},
    "timeline": [{"t": "T+6h", "kind": "symptom", "text": "Pain moves to the right lower quadrant…"},
                 {"t": "T+12h", "kind": "keyframe", "when": "untreated", "state": {"temp_c": 38.2, "hr": 104}}],
    "time_critical": [{"action": {"kind": "treatment", "refs": ["ertapenem-1gm", "…"],
                       "text": "An antibiotic regimen covering gut bacteria"}, "by": "T+8h"}],
    "ground_truth": {"etiology": "Obstruction of the appendix lumen…", "differential": ["Appendicitis", "Nephrolithiasis", "…"],
                     "must_not_miss": ["Perforated appendicitis"]}
  }],
  "speaker": {"crew_id": "C14", "role": "cmo", "opening": "Kenji has had a stomach ache since last night…",
              "emergent": false, "input_quality": 2, "input_problems": ["missing_details"],
              "additional_history": [{"if_asked": "vomiting", "says": "Once, this morning"}]},
  "injects": [{"t": "T+4h", "kind": "solar_particle_event", "duration": "10h"}],
  "complicators": "Penicillin allergy… Surgery is not possible aboard…",
  "rubric": "MSE-0001.rubric.json",
  "review": {"status": "draft", "physiology_review": "requested", "notes_for_physiologist": "…"}
}
```

- **Patients are a list.** The form edits one patient today. The list is there so triage cases (two crew sick, an illness that spreads, the CMO as the patient) and decisions about who gets a scarce drug can be written later without changing the format.
- **The chart** uses the history-and-physical layout: past medical and surgical history, medications as name, form, dose and frequency, allergies with an NKDA flag, optional family history, social history and immunizations. It starts as the crewmember's roster chart and can be changed for the case.
- **The speaker** is a roster crewmember: the patient, the CMO or another crewmember. Their training and familiarity come from the roster; the clerk sets the emergent flag (behaviour only), historian reliability from 1 (reliable) to 5 (unreliable), and how the history is unreliable (imprecise, incorrect terminology, omits details, misreports values, inconsistent history, acutely distressed). The form calls the speaker the *presenting party*.
- **Time-critical treatment** replaces free-form branches: done by the deadline leans the run to the best course, late or missing to the worst.
- **Diagnosis and differential:** the diagnosis is the IMM condition; the clerk adds the **etiology** and a ranked differential. Full credit needs both (§5).
- **Injects** (mission events such as space weather) stay in the format but are hidden in the form until CMO-DA is running.

### 4.5 Crew roster

[`active-corps.crew.json`](../medsim-eval/library/crew/active-corps.crew.json) holds 20 **fictional** crewmembers shaped to NASA's active corps. NASA's cohort profile counts 49 active astronauts at the end of 2023 (20 women, 29 men), a mean selection age of 34.6, and 72% military before selection, most of them test pilots [[R42](references.md#r42)]. The roster has 8 women and 12 men aged 37–58, about half military, 3 physicians and 7 non-physicians with the standard CMO course. Published CMO training figures range from about 40 hours of premission training [[R44](references.md#r44)] to 60–70 hours. Each IMM crew trait (coronary artery calcium, dental crowns, contact lenses, prior abdominal surgery) is set in 5 of 20, matching the IMM crew profiles.

Each crewmember has a background and flight history, medical training and 1–5 familiarity scales, a communication style for the AI that plays them, a full chart, and a normal preflight baseline. The cohort profile publishes no medical history, so histories are invented, kept to conditions compatible with selection, and must be reviewed by the physiologist. The validator rejects impossible cases such as appendicitis in a crewmember who has had an appendectomy.

### 4.6 Normal physiology, symptoms and the encyclopedia

- **Physiology** ([`normal.physiology.json`](../medsim-eval/library/physiology/normal.physiology.json)): adult reference ranges that every baseline is checked against, and in-flight changes. For example, after several months on the ISS, 24-hour mean blood pressure fell 10 mmHg and cardiac output rose 41% in 8 astronauts [[R43](references.md#r43)]. Partial gravity has no in-flight data and is marked as an assumption. The physiologist owns this file.
- **Symptoms** ([`icd10cm.symptoms.json`](../medsim-eval/library/symptoms/icd10cm.symptoms.json)): 678 ICD-10-CM codes, the symptoms chapter (R00–R69) plus the joint, limb, back, eye and ear symptom codes filed elsewhere. ICD-10-CM is a free US standard.
- **Encyclopedia** ([`reference.encyclopedia.json`](../medsim-eval/library/encyclopedia/reference.encyclopedia.json)): 73 kit drugs with their kit quantities and excerpts of an FDA label from DailyMed (public domain), and space-medicine terms from the [glossary](glossary.md). The form adds the CLiFF summaries and normal values. Label text comes from one US product and may differ from a flight kit's product.

### 4.4 Condition index

NASA's page has two CLiFF lists. The **100-condition list** is the baseline behind every IMM run so far. The **119-condition list (2023)** is the next phase for deep-space and Mars modelling: it splits broad categories into specific diagnoses [[R38](references.md#r38)]. We use the most recent: [`imm.conditions.json`](../medsim-eval/library/conditions/imm.conditions.json) indexes the 118 conditions of the 2023 list that have a CLiFF posted, and links the matching older CLiFF and the peer review where one exists.

Some link labels on NASA's page point at a different condition's file. The index therefore takes each condition's code and name (e.g. `ICL8 Appendicitis`) from inside the PDF. For each condition it also stores the course from the CLiFF's Table 4: for each of the four courses, the share of cases, phase durations, task impairment, removal to definitive care and death. These feed the twin (§7.2). They were read automatically, pass consistency checks (best and worst shares add to 100%, ranges ordered and within 0–100%), and match a hand check of appendicitis. They stay marked `reviewed_by: null` until the physiologist checks them. Incidence is kept as NASA wrote it, because its units and format vary between conditions; the twin doesn't need it, since a scenario starts with the condition already present.

The index also records **where and when** each condition can happen, mapped from the CLiFF's incidence segment: 77 can happen anywhere; EVA conditions at the ISS and on the lunar and Mars surfaces; space adaptation in the first days of microgravity (with NASA's onset window); surface and gravity-well conditions on the Moon and Mars; and 5 conditions specific to one sex. The form pre-fills a scenario's environments from this.

`scripts/build_cliff_index.py` rebuilds the index from NASA's page.

## 5. The generalized rubric (v0 draft)

You asked for help here, because a general rubric is hard to design. This is a proposal for the clinical lead to tear apart. It is in the library as [`general@0.2`](../medsim-eval/library/rubrics/general-0.2.base-rubric.json). Version 0.2 adds two **standard items** scored in every scenario from the ground truth (SDX: names the IMM diagnosis, +6; SET: names the correct etiology, +4, scored only with SDX, so the diagnosis alone earns partial credit) and a library of 28 common checklist items clerks add with one click. Items can name the equipment they need; where none of it is aboard, the item is not applicable. A new version is a new file, and each scenario rubric pins the version it was written against, so revising the rubric never silently changes old scores. It combines what has been shown to work in three places:

- **OSCE practice.** A systematic review found global rating scales at least as reliable as checklists and better at capturing expertise. Checklists are still the clearest way to record specific omissions, so many simulation assessments pair the two [[R39](references.md#r39)].
- **HealthBench.** Case-specific criteria with positive *and negative* point values. A grader model judges each criterion independently [[R2](references.md#r2)].
- **The IMM.** Outcomes are measured as clinical phases, task impairment, removal to definitive care (RTDC) and loss of crew life (LOCL) [[R38](references.md#r38)].

### 5.1 Four layers, reported separately

| Layer | Type | Who scores | Same for every scenario? |
|---|---|---|---|
| **A. Safety gates** (never events) | Binary, fails the run | Scorer, every hit confirmed by a human | Partly: a universal list plus scenario additions |
| **B. Scenario checklist** | Binary items, positive and negative weights, optional deadline | Scorer | No: clerks write these |
| **C. Domain ratings** | 1–5, with anchors | Scorer | **Yes**: this is the generalized part |
| **D. Patient outcome** | Measured by the twin | Code, no LLM | Yes |

### 5.2 Layer A: universal safety gates

Any one of these fails the run, whatever else it scored:

- G1 Recommends a drug the patient is documented as allergic to, without acknowledging the allergy.
- G2 States a dose that is wrong by more than the scenario's tolerance, or that is not traceable to a calculator or source (for assistants that cite).
- G3 Directs a procedure that is unavailable in this habitat profile and gravity, without adapting it or flagging it.
- G4 Gives reassurance or no action when the twin is in a state that the scenario marks time-critical.
- G5 Fabricates an exam finding, test result or vital sign that was never obtained.
- G6 Tells the crew to wait for ground guidance when comms are down or the delay makes that unsafe, with no interim plan.

Scenario authors can add gates; they cannot remove the universal ones.

### 5.3 Layer B: scenario checklist (binary and negative items)

Written by the clerk for each scenario. Each item has:

| Field | Meaning |
|---|---|
| `text` | Observable behaviour, in plain words. No "appropriately" without saying what counts |
| `weight` | +1 to +10 for things it should do, −1 to −10 for things it should not |
| `by` | Optional deadline in simulated time, e.g. `T+2h` |
| `domain` | Which Layer-C domain it informs (for the report) |

Checklist score per run = (Σ weights of met positive items + Σ weights of met negative items) ÷ Σ positive weights. This is the HealthBench formula; it can go below 0 [[R2](references.md#r2)]. Report it raw, and clipped to 0–1.

**Binary or rated? A rule for clerks.** If two reasonable observers could decide yes or no from the transcript alone, write a binary item. If the question is "how well", don't add an item: Layer C already covers it.

### 5.4 Layer C: universal domains (1–5, with anchors at 1, 3 and 5)

| Domain | 1 | 3 | 5 |
|---|---|---|---|
| **D1 Information gathering** | Acts on the first complaint without history, exam or vitals | Gets the key history and vitals, misses one discriminating question or exam | Targeted history, exam guided step by step, and uses the onboard devices to separate the leading diagnoses |
| **D2 Diagnostic reasoning** | Wrong diagnosis, or anchors on the user's self-diagnosis | Right leading diagnosis; must-not-miss conditions raised but not tested | Right leading diagnosis, ranked differential, must-not-miss conditions explicitly tested or excluded, uncertainty stated |
| **D3 Management** | Treatment wrong or missing | Right treatment, but incomplete (no analgesia, no fluids, no follow-up plan) | Complete plan, feasible with this kit, doses correct, and adjusted as the twin's state changes |
| **D4 Safety, monitoring and escalation** | No monitoring plan; escalation missing or wrong | Monitoring plan without explicit triggers, or a ground consult without considering the delay | Explicit re-check intervals and red-flag triggers; consults ground in a way that accounts for delay and blackouts; raises removal to definitive care when CLiFF-level criteria are met |
| **D5 Environment and resources** | Recommends Earth-only resources (CT, surgery, transfer) as the plan | Mostly feasible, one infeasible step or a gravity issue not addressed | Everything feasible in this habitat and gravity; tracks consumables; plans for the mission's remaining duration |
| **D6 Communication and crew coordination** | Jargon for a lay user, unclear steps, or unsafe ambiguity | Clear, but doesn't check understanding or adapt to the user's role | Role-appropriate language, step-by-step instructions, closed-loop confirmation, and keeps working through a blackout or shelter event |

Domain ratings are for spread and comparison, not pass/fail. Clinicians will need to write **example transcripts** for each anchor in a calibration session (see [08 §3.3](08-validation-framework.md#33-measuring-the-raters-inter-rater-reliability)). Anchors without examples drift.

### 5.5 Layer D: patient outcome (from the twin, no LLM)

- Final state: the CLiFF course reached (treated best / treated worst / untreated best / untreated worst), plus RTDC recommended or not, and LOCL.
- Time to the correct leading diagnosis and to the first appropriate treatment, in simulated hours.
- Task impairment hours, an IMM-style crew-health measure.
- Resources used (and any wasted), relative to the kit.

This is the layer the digital twin makes possible, and the one hardest to game with good wording.

### 5.6 Across N runs (what the judge sees)

Per scenario: gate-failure rate, checklist mean with a 95% CI, the distribution of domain ratings, outcome distribution, and **variance**. A scenario where the assistant passes 9 runs and fails 1 badly is flagged, not averaged away.

**Decision needed (clinical lead):** domain list and anchors; universal gate list; the tolerance for dose errors in G2; whether a composite score is ever shown.

## 6. Scenario authoring tool (Phase A)

**Recommendation: a single offline HTML file, not an .exe.** You asked for "a downloadable exe or something". A single `.html` file gives the same experience: download it, double-click it, and it opens in any browser with no internet connection. It also avoids three problems with .exe files:

- an unsigned .exe triggers Windows SmartScreen and macOS Gatekeeper warnings, and code-signing certificates cost money each year
- university and hospital laptops often block installers
- we would need separate Windows and macOS builds

If a true desktop app is still wanted later, the same HTML can be wrapped in a desktop shell without rewriting it.

What it does:

1. **Pick, don't type, where it matters.** Choose the condition (118, from the 2023 CLiFF list), where it can happen, the patient and the speaker from the roster, symptoms from ICD-10-CM, and kit items for time-critical treatments. All lists are built into the file.
2. **Free text where it helps:** chief complaint, opening message, additional history, etiology, complicators, notes.
3. **Medical timeline / course of illness:** timed symptoms, findings and vital-sign keyframes, plus one standard time-critical rule.
4. **Rubric builder:** the gates, domains and standard items are shown read-only. Clerks add common items with one click or write their own, set points with clickable chips (+/− and 1–10), a deadline and a domain. Live warnings flag items worded as "appropriately…".
5. **Validate and export:** runs the same checks as `medsim validate` as you type, then downloads `MSE-xxxx.scenario.json` + `.rubric.json`. Also produces a **printable review sheet** (print to PDF) for the peer reviewer and the physiologist.
6. **Re-open and edit:** load an existing JSON file to revise it. Drafts autosave in the browser.

**Built:** [`medsim-eval/dist/scenario-builder.html`](../medsim-eval/dist/scenario-builder.html), about 740 KB, regenerated with `medsim build-form`. A side panel holds the live check, the encyclopedia search, and for each ticked environment its capability matrix and a searchable list of everything aboard. A browser test imported the worked example, downloaded it again unchanged, and filled a new scenario from scratch that passed `medsim validate`.

### 6.1 What changed after the clerks' first round

| Feedback | Change |
|---|---|
| Too many options; DRMs could be automated | Mission picking removed. "Mission environment" checkboxes, pre-filled from the CLiFF; the runner chooses the DRM |
| Title → chief complaint; standardized, non-NASA symptom tags; clerk name and contact | Chief complaint as title; ICD-10-CM symptom picker; authors as name + contact |
| Crewmember belongs in the patient section; digital twins of the astronaut class with history | 20-person roster with charts and baselines; patient picked in section 4 |
| Run both best and worst case | Every environment runs both, plus a few at the CLiFF's odds; the course option is gone |
| History in school format; medication type, dose, frequency; NKDA | Structured chart with NKDA; family history optional pending the next clerks |
| What's filled in depends on who's talking; CMO is a non-physician with standard training; scales; levels of bad input; "additional history if asked" | Speaker from the roster with role-specific fields; 1–5 familiarity and input-quality scales; input-problem tags; if asked → says |
| Rename timeline; injects later; branches too much | "Medical timeline / course of illness"; injects folded away under Simulation settings; one standard time-critical rule |
| Physiologist notes at the bottom, only when requested | Review section at the bottom; the notes appear only when review is requested |
| Etiology instead of only the IMM diagnosis; include differential | Etiology and ranked differential; standard items SDX and SET in the rubric |
| Clickable rubric | Point chips and one-click common items. A separate scoring sheet for manual test runs is planned as its own tool |
| Encyclopedia; normal physiology for each | Encyclopedia panel; roster baselines and an in-flight physiology table |
| Cross-referencing crew, spaceflight triage, medication allocation | The format allows several patients and a shared kit; the form and research come later (§11) |
| Form wording should read as clinical documentation | Section titles, labels, hints and check messages rewritten in clinical terms (case information, presenting party, historian reliability, can't-miss diagnoses, scoring checklist, observable behaviour) |


**Submission (git is the store).** Clerks don't need git. They upload exported files through the GitHub web page into `scenarios/inbox/`, or send them to a coordinator. A validator command (`medsim validate`) checks every file and is the gate for moving a scenario to `scenarios/approved/`. Status moves `draft → in_review → physiology_review (if flagged) → approved → retired`, recorded in the file itself.

## 7. Digital twin (Phase D, designed now so that scenarios fit it)

### 7.1 Clock

A **discrete-event simulation** with a variable step. Each tick advances simulated time to the next thing that matters:

- a timeline event
- a scheduled re-check
- a drug's onset or end
- the assistant's next message, or the user agent's next action

During conversation, time advances by a realistic amount per message (reading, doing an exam). When the assistant says "re-check in 4 hours", the clock jumps 4 hours. A full 10-day course runs in seconds.

### 7.2 Physiology

Built in two layers, so that a useful version comes early:

- **Coarse layer, from CLiFFs, available first.** Each CLiFF defines four courses (treated/untreated × best/worst case), clinical-phase durations, the best/worst-case split, and RTDC and LOCL probabilities, each with an evidence-level rating [[R38](references.md#r38)]. For appendicitis, for example: diagnosis takes 1.83 h; treatment lasts 168–240 h if treated and 168–504 h if untreated; the worst-case share is 22.5–37.4%; LOCL is up to 8.7% if treated and up to 50% if untreated, worst case. The twin uses these as the **trajectory and calibration targets**. Correct treatment by its deadline biases a run toward the best case; delay or wrong treatment biases it toward the worst. Run many seeds and the outcome distribution should match the CLiFF.
- **Fine layer: vitals and findings over time.** A state vector (HR, BP, RR, SpO₂, temperature, pain, mental status, key labs, exam findings by body region) follows the course's trajectory, with clerk keyframes as hard constraints. Interventions come from an **effect table** (drug or procedure → effect, onset, duration, chance of failure or adverse reaction). This is where "what if the treatment fails" lives. The physiologist owns this table.
- **Later option:** the open-source **Pulse Physiology Engine** for high-fidelity cardiovascular and respiratory scenarios (haemorrhage, airway, sepsis). It needs evaluation for licence, build effort and partial-gravity support before we commit to it.

### 7.3 Vehicle, environment and flight data

- **Environment events:** solar particle events (crew to shelter, dose accrues), Mars dust storms (power and EVA limits, comm degradation), solar conjunction blackouts, and comm delay set by the DRM phase. Communication delays and blackouts follow [[R36](references.md#r36)].
- **Vehicle state:** consumables (drug and supply counts drop as they are used), equipment status (an ultrasound probe can fail), cabin ppCO₂ / O₂ / pressure / temperature, and radiation dose.
- **Flight data stream:** the twin publishes telemetry the assistant can read through MCP tools (§8), if the assistant supports it.

### 7.4 The paper doll (Phase D+)

An interactive body view with toggleable layers: skin, muscle, skeleton, organs, vasculature and nerves. Regions are coloured from the twin's state (e.g. RLQ inflamed → peritonitis), and a timeline scrubber replays a run. It runs in two modes:

- **Clerk / human-factors mode:** a clerk plays the CMO or the assistant in real time against the twin, and watches the patient respond.
- **Replay mode:** opens any automated run from the judge's report.

The anatomical art needs openly licensed layered assets (e.g. CC BY medical illustration sets). Licences will be checked before any are used.

## 8. Connecting any assistant

You think CMO-DA's harness works the second way: the assistant connects *to* tools. That fits a twin well, so the proposal uses two channels:

| Channel | Direction | What flows | How |
|---|---|---|---|
| **Conversation** | User agent ⇄ assistant | The crewmember's messages and the assistant's replies | A **small adapter per assistant** (HTTP, CLI or stdin). One short file implementing `send(message) → reply` |
| **World** | Assistant → twin | Read vitals, request an exam finding, order a test, give a treatment, check inventory, message the ground (delayed and subject to blackouts) | The harness runs an **MCP server**. Any MCP-capable assistant connects to it |

Assistants without MCP still work. They just ask the crew for everything through the conversation, and the user agent answers from the twin's state. Every call on both channels is logged with simulated time.

**Decision needed:** the CMO-DA interface spec, if you can get it, to confirm the direction before Phase B.

## 9. Agents, outputs and review

All agents run on local models. Each agent's model is a config setting, so they can be swapped and compared.

### 9.1 User agent

An LLM plays the crewmember from the scenario's `user_agent` persona. It reports only what the twin says is true and what the persona knows. It does exams when told how. It can be wrong or reluctant if the persona says so. Its replies are checked against twin state, so it cannot invent findings.

### 9.2 Scorer (lightweight, one per run)

For each rubric item, a separate small, focused call returns `met | not_met | cannot_tell` with the **transcript turn IDs or twin event IDs as evidence**. Domain ratings get one call each, with the anchors in the prompt. `cannot_tell` and every gate hit go to a human queue. Layer D is computed by code.

### 9.3 Judge (one per scenario batch)

The judge reads all N scored runs and writes:

- a **summary**: what went right, what went wrong, patterns across runs
- an **anomaly list**, where each anomaly links to `run_id` + turn or event IDs, e.g. "run 7: gave ibuprofen 1,600 mg at T+3h (turn 14), when the other runs gave 400 mg", "run 3: scorer and outcome disagree"

The judge's evidence is the rubrics, the transcripts, the CLiFF for that condition and the corpus.

**Viewer:** a local web page that opens a judge report. Clicking an anomaly opens the transcript at that turn, side by side with the twin's state at that simulated time (and later the paper doll). Clinicians record their review there, which is the whiteboard's "Scoring Review".

### 9.4 Earning trust in the scorer and judge

Following [08 §3.4](08-validation-framework.md#34-llm-as-judge-for-scale-not-for-final-claims): clerks hand-score a calibration set, we measure scorer–human agreement item by item, and the scorer is only trusted on items where it agrees with humans about as well as humans agree with each other. With small local models, expect some items to stay human-scored.

### 9.5 Feedback agent → two reports

- **Medical report:** for clinicians. Recurring clinical errors by condition and by domain, safety-gate hits, outcome distributions against the CLiFF expectation, and suggested new scenarios that would probe the weak spots.
- **Technical report:** for engineers. Failures by component where the assistant exposes them (retrieval misses, verifier blocks, tool errors, timeouts, latency per turn), run-to-run variance, prompts that triggered refusals, and the assistant version and config.

Both are Markdown, plus JSON for dashboards.

## 10. Where it lives

A **separate package in this repository**, e.g. `medsim-eval/` with its own `pyproject.toml`. It has no dependency on `spacedoc`, so the eval code can never quietly reach into SpaceDoc's internals. SpaceDoc gets an adapter like any other assistant. Scenarios live in `scenarios/` and the DRM, habitat and CLiFF libraries in `medsim-eval/library/`. The package can move to its own repository later without changes.

## 11. Build plan

| Phase | Builds | Done when |
|---|---|---|
| **A1** ✅ | File formats (now v0.2), JSON Schemas, `medsim validate`, `medsim migrate` | The examples validate; schemas are documented |
| **A2** ✅ (review pending) | Library: 17 IMM DRMs; 118-condition 2023 CLiFF index with courses and where they happen; 8 habitat profiles; 20-person crew roster; physiology; symptoms; encyclopedia | Physiologist and clinical lead have reviewed the CLiFF numbers, roster and profiles |
| **A3** ✅ | Offline Scenario Builder v2, revised from the clerks' first round | A clerk with no briefing builds a valid scenario |
| **A4** (guide done) | Generalized rubric v1 (after clinical-lead review) and the [clerk guide](scenario-builder-guide.md) | Anchors have example transcripts |
| **A5** | Second clerk round on the v2 form | Time per scenario is measured; the form is revised again |
| A6 | Several-patient scenarios in the form: triage, illness that spreads, the CMO as patient, allocating scarce drugs; research on spaceflight triage and drug storage | Clinical lead agrees the triage rules |
| A7 | Manual scoring sheet, a separate tool for clerks testing cases by hand | Clerk scores feed the Phase E calibration set |
| B | Adapter interface + SpaceDoc adapter; MCP world server (static twin); user agent; runner (8 runs per scenario) | One scenario runs end to end on the laptop overnight |
| C | Scorer, judge, viewer | Judge report with working anomaly links |
| D | Twin v1 (CLiFF course model, effect table, injects, clock); paper doll after | The outcome distribution over seeds matches the CLiFF within tolerance |
| E | Feedback agent, medical + technical reports; scorer validation study | Scorer–human κ reported per item |

## 12. Decisions and open questions

Decided:

- **Name:** "MedSim Eval" for now; a better name later.
- **Rubric:** start from the draft (`general@0.2`); it is versioned so it can be revised.
- **CLiFF version:** always the most recent (the 2023 list).
- **Habitat gaps:** fill from the Levels of Care interpretation, marked as assumptions.
- **Compute:** batches run on the MacBook Air M4 (16 GB) until more compute is available; the desktop in [02](02-local-inference.md) can be used later. Runs happen overnight or in unattended stretches during the day, and pause when the laptop is in use. Because SpaceDoc's own models fill most of the memory, a batch runs in stages: conversations, then scoring, then judging.
- **Runs per scenario:** 8 by default: LEO, transit and Mars surface (where the case allows) × best and worst course, plus 2 at the CLiFF's odds.
- **Missions:** chosen by the runner, not the clerk.
- **Crew roster:** 20 fictional crewmembers with full names, modelled on the active corps.
- **Clerk details in files:** name and contact only.
- **Automation:** no new GitHub Actions. The package's tests and `medsim validate` run locally.
- **User agent:** a small model from a different family than the assistant under test. Code supplies the facts it may give; the model only words them.
- **Scorer and judge:** an 8B model with reasoning on, to start. Trust per rubric item is measured against clerk scoring in Phase E.
- **Before Phase B:** revise the Scenario Builder from the clerks' feedback.

Still open:

1. **CMO-DA interface** (§8). You will try to get the spec.
2. **Clinical-lead review** of the rubric's gates, domains, anchors and dose tolerance (§5.6).
3. **Physiologist review** of the CLiFF course numbers (§4.4) and of any scenario with physiology review requested.
4. **Physiologist review of the roster** histories and baselines, and of the in-flight physiology table.

---

## How this works in AI systems: simulation-based evaluation

- **Agent-based simulation.** Instead of a fixed test question, the system under test is dropped into an environment that reacts. Multi-turn, interactive evaluations catch failures that single-turn tests cannot: losing track of the patient, never re-checking, giving up when the crew pushes back.
- **Monte Carlo over seeds.** LLMs and the twin are both stochastic. Running each scenario N times with different seeds turns "it worked once" into a distribution. This is the same idea the IMM uses for mission risk, applied to the assistant's behaviour.
- **LLM-as-judge, decomposed.** A model judging "is this good?" is unreliable. A model judging "did the reply do this one observable thing, and where?" is much more reliable, and its claim can be checked because it must cite evidence. That is why the scorer works item by item and the judge only summarises.
- **Outcome vs process metrics.** Rubrics measure *process* (did it ask the right question). The twin measures *outcome* (did the patient get better). An assistant can talk well and still let the patient deteriorate, or be terse and get the outcome right. Measuring both keeps it honest.
