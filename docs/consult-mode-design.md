# Consult Mode — Design Proposal

> **Status: approved. M1 (terminal consult) and M2 (web page) are built, plus the changes from the first practice consult (§12). Next: equipment knowledge from the ISS inventory, and speed on the laptop.** Decision for M2: the working list is shown to every user, including a crewmember who is the patient. Decisions marked ✅ were agreed in discussion; the answers to the design's open questions are in [§11](#11-decisions-on-the-open-questions).

Phase 1 built a **one-shot** SpaceDoc: one message in, one checked answer out. That is not how a consult works. A clinician asks questions, narrows the possibilities, examines, and only then gives an assessment.

Consult mode makes SpaceDoc **semi-conversational**. It asks one or two questions at a time to build a differential diagnosis, and gives a fully checked assessment at the end. This brings forward FR-02 (structured symptom intake) from [00](00-vision-and-requirements.md) and the conversation design in [07 §4](07-adaptive-interaction.md#4-conversation-design).

## 1. Decisions so far

| # | Topic | Decision |
|---|---|---|
| 1 | Who uses it | ✅ Anyone. SpaceDoc identifies who it is talking to, and who the patient is, at the start of each consult |
| 2 | When questioning stops | ✅ SpaceDoc decides when it has enough (usually 3–6 rounds of 1–2 questions). The user can press **Assess now** at any time. A dangerous answer jumps straight to urgent guidance |
| 3 | Working differential | ✅ Shown during questioning, labelled "working list, not yet checked", with a one-line reason for each question. At the end, the **full reasoning log** is available |
| 4 | Exams and measurements | ✅ SpaceDoc can ask for exams or measurements, limited to equipment aboard. Later, SpaceDoc minis attached to the crewmember supply readings automatically |
| 5 | Answer input | ✅ Free text, plus quick buttons (yes / no / not sure) for simple questions |
| 6 | One-shot mode | ✅ Kept as **Quick question** for general questions. **Consult** is added for symptoms |
| 7 | Speed | ✅ 10–15 s per question turn on the MacBook Air. The final checked assessment may take longer |
| 8 | Thinking | ✅ Off for question turns (speed); on for the final assessment, which keeps the reasoning summaries for clinical review |
| 9 | Testing | ✅ Clinicians write scenarios and run them with each other (one plays the patient or CMO), SpaceDoc's performance is graded, and **practice sessions** feed a feedback loop |

## 2. A consult, start to finish

Illustration only, using the question that prompted this design. The clinical content is an example of the *shape* of a consult, not reviewed guidance.

```
SpaceDoc: Who is using SpaceDoc?            → [C1 · Commander · CMO]
          Who is the patient?               → [C3 · Flight engineer]
          Real or practice session?         → [Practice: scenario SO-0104]

CMO:      "C3 is feeling disoriented and having trouble focusing on close-up objects."

SpaceDoc: ⚠ Urgent-sign check (runs first, every turn):
          "Did the disorientation come on suddenly, or with weakness, numbness,
           trouble speaking, or a severe headache?"   [Yes] [No] [Not sure]
          Why: these point to an acute neurological problem that needs action now.

CMO:      "No, it's been building for about a week."

SpaceDoc: Working list (not yet checked):  vision change related to spaceflight · high
                                           space adaptation / motion sickness · moderate
                                           neurological cause · must not miss
          1. "Is the close-up blur in one eye or both?"
             Why: helps separate an eye cause from a brain cause.
          2. "Any headache, nausea, or changes when moving the head?"
          Exam: T1's equipment list has no vision chart or ophthalmoscope, so SpaceDoc
                says so rather than asking for them, and suggests what *is* aboard.
   ... 3–6 rounds ...
CMO:      [Assess now]  (or SpaceDoc says it has enough)

SpaceDoc: Checked assessment: ranked differential, sources, feasible tests and treatment,
          actions with their confirmation level.
          [View consult record]  → every turn, the working list as it changed, the reason
                                   for each question, the final thinking notes and summary.
```

## 3. Identification

At the start of every consult SpaceDoc asks two things:

1. **Who is using SpaceDoc?** Picked from the crew roster.
2. **Who is the patient?** "Myself", another crewmember from the roster, or "someone not listed".

**Phase 1 version (✅ agreed):** a pick-list from a synthetic crew roster (`data/crew/roster.yaml`: ID, role, medical training level, and a minimal record: allergies, medications, history, preflight baselines). There are no passwords. Real sign-in is a later-phase item.

**What identification changes:**

| | User is the CMO | User is another crewmember | User is the patient |
|---|---|---|---|
| Wording | Clinical terms | Plain language ([07](07-adaptive-interaction.md)) | Plain language |
| Exams it asks for | Any exam with equipment aboard | Simple ones it can talk them through | Self-checks only |
| Actions at R2 and above | CMO confirmation as now | Shown as "ask the CMO to confirm" | Same |
| Record used | The patient's | The patient's | Their own |

Every turn in the audit log records who said it.

## 4. Question turns (fast path)

A question turn must finish in 10–15 s, so it does only what is needed to pick the next questions.

**Steps, in order:**
1. **Urgent-sign rules** check the user's words and any readings against a red-flag list. These are deterministic and take under 0.1 s. A match stops questioning and shows the urgent card (§6).
2. **One model call** (Qwen3, thinking off, short JSON reply):
   - `urgent`: the model's own red-flag judgement, as a second net behind the rules.
   - `facts`: what this answer added (for example *onset: gradual, about 1 week*), each tied to the turn it came from.
   - `working_ddx`: 3–5 conditions with likelihood and a one-line reason.
   - `questions`: 1–2 questions, each with `why` and an answer type (yes/no, choice, free text, measurement).
   - `exam_requests`: exams or measurements, each naming the equipment it needs.
   - `ready_to_assess`: whether the model thinks it has enough.
3. **Checks on the reply:**
   - At most two questions.
   - Every exam request is checked against the equipment aboard, using the same rule as actions today. If equipment is missing, SpaceDoc says so.
   - Facts must quote or paraphrase something the user actually said.
4. **Log the turn** in the audit log and show it.

**Kept out of question turns, for speed:**
- **Source search.** Questions come from the model's general knowledge. That is acceptable for *asking* (a question can't state a false fact), and the working list is clearly marked as not checked. Sources are searched for the final assessment, where every statement is checked.
- **The grounding checker.** It is only loaded for the final assessment, so question turns never wait for Ollama to swap models.

**Device readings (later):** an exam request names a measurement (for example `blood_pressure`). When a SpaceDoc mini is attached to the patient (FR-06, Phase 2), the request is answered from the device automatically, and the reading is logged with its source. Phase 1 builds the request format with manual entry only, so devices can plug in later without redesign.

## 5. Final assessment (checked path)

When SpaceDoc has enough, or the user presses **Assess now**:
1. The consult is turned into a structured **case summary**: chief complaint, the facts gathered with the turn each came from, exam results, the patient record, and the environment.
2. The **existing Phase 1 pipeline** runs on the case summary. It does source search (now using the whole summary as the query, not just the first message), the first pass with thinking, calculators, and the full checking.
3. **Changes to checking:**
   - Patient claims are checked against **what the user actually said** in the consult, plus the record, not against the model's extracted facts. Extraction can be wrong; the user's words are the evidence.
   - The summary prompt asks the model to restate its own checked claims with no new facts. This fixes the over-strict summary check seen in the first real run.
4. After the assessment the user can keep going: ask "why?", add new information (which triggers a re-assessment), or close the consult.

## 6. What the user sees

- **Chat panel:** SpaceDoc's questions, each with its "why", and quick-reply buttons.
- **Working list panel:** the current differential, labelled *working list, not yet checked*. It updates every turn and highlights what changed.
- **Exam cards:** what to measure, how, which equipment, and a field for the result.
- **Urgent card (red flag):** shows at once, with the reason and the immediate steps from a clinician-reviewed list. It offers an immediate checked assessment. It also states the communication delay to the ground for the current mission tier. The full emergency protocol engine (C-05) is a later item, so Phase 1 shows only these reviewed steps.
- **Assess now** button, always visible.
- **Consult record (end of consult):**
  - Every turn: what was said, the facts extracted, the working list after the turn, and each question with its reason.
  - Exam results with their source (manual or device).
  - The final assessment, its thinking notes and the reasoning summary, and every verification finding.
  - Exportable as Markdown or JSON.

## 7. What is checked, and what isn't

| Item | Checked? | How it is shown |
|---|---|---|
| Questions and their "why" | No. They are questions, not statements of fact | Plain |
| Working differential | No. It is a hypothesis list | Labelled "working list, not yet checked" |
| Red flags | Yes: deterministic rules, plus the model as a second net | Urgent card |
| Exam requests | Equipment checked against what is aboard | Exam card |
| Facts extracted | Must trace to the user's words. The final patient claims are checked against the transcript | In the consult record |
| Final assessment | Fully checked, as in Phase 1 | As now |

## 8. Practice sessions and the feedback loop

**Starting a session.** Every consult starts as **Real** or **Practice**. Practice sessions:
- are tagged everywhere,
- never write to a crew record, and
- can be linked to a **scenario card**.

**Scenario cards** extend the SpaceOSCE case format ([08](08-validation-framework.md), [authoring guide](spaceosce-authoring-guide.md)). New fields:
- `opening`: what the person playing the patient or CMO says first.
- `script`: facts to reveal **only when asked** (onset, which eye, headache…).
- `must_ask`: the questions a good clinician would ask.
- `red_flags`: any that should trigger.
- The existing `ground_truth`, `critical_actions` and `harmful_actions`.

**SpaceDoc never sees the scenario card.** It sees only what the role-player types, exactly as in a real consult.

**Debrief.** At the end of a practice session, the expert (or a second, blinded rater) fills in a short form on the consult record:
- each question: *useful / not needed / leading or unsafe*;
- missed questions: picked from `must_ask`, plus free text;
- whether the correct diagnosis was in the final top 3, and at which turn it first appeared in the working list;
- each shown claim: *agree / disagree*;
- each action: *safe / unsafe / not feasible aboard*;
- the five 1–5 global ratings from [08 §3.2](08-validation-framework.md#32-rubric-scoring-clinician-raters), plus comments.

Feedback is saved in the audit log, linked to the consult, the scenario, and the exact SpaceDoc version (model, prompt version, rule-set version).

**How feedback improves SpaceDoc.** Every change is reviewed by a clinician, versioned and re-tested. SpaceDoc **never changes its own behavior from feedback automatically**. A system that learns live can learn the wrong lesson from one unusual session, and nobody could tell afterwards which version gave a recommendation. Feedback flows into:

| Feedback | Becomes |
|---|---|
| Missed questions | **Must-ask checklists** per complaint (e.g. *new vision change → onset, one or both eyes, headache…*). Clinician-approved. SpaceDoc is shown the checklist each turn, and before assessing it lists any items not yet asked |
| Claims marked *disagree* that passed the checker (or the reverse) | A labelled set to **calibrate the grounding checker** (its P(yes) threshold) or to decide whether to replace it |
| Actions marked *unsafe* or *not feasible* | New **feasibility and formulary rules** |
| "No source for this" | **Corpus gaps** to fill |
| Every graded scenario | A **regression case**: re-run after each change, so nothing gets worse without anyone noticing |
| All of the above, at scale | Later (Phase 3+): data for fine-tuning, only with enough reviewed examples |

**Scoreboard** (per SpaceDoc version):
- must-ask coverage;
- turns until the correct diagnosis enters the working list;
- correct diagnosis in the final top 3;
- harmful-action rate;
- claim agreement;
- time per turn;
- rater agreement (κ, ICC as in [08 §3.3](08-validation-framework.md#33-measuring-the-raters-inter-rater-reliability)).

## 9. Speed plan (10–15 s per question turn)

These are estimates to be measured in milestone M1, not results:

| Step | Estimate on the MacBook Air |
|---|---|
| Urgent-sign rules | < 0.1 s |
| Model reads the new turn (earlier turns already cached by Ollama) | ~1–3 s |
| Model writes ~150–250 tokens at 15–25 tokens/s | ~6–17 s |
| **Total** | **~8–20 s**; the first question can appear after a few seconds if the reply is streamed to the page |

**How to stay inside the target:**
- short replies;
- no source search and no checker in question turns;
- keep Qwen3 loaded between turns (Ollama `keep_alive`), with the conversation's start unchanged so Ollama can reuse it;
- stream the reply so the question shows as soon as it is written.

**If the 8B model can't make 15 s:** use a smaller model (e.g. `qwen3:4b`) for question turns and keep the 8B for the final assessment. Compare the two with practice scenarios before deciding.

The final assessment will still take minutes on the Mac (search, thinking, calculators, checking). NFR-03's target of under 30 s for a full checked answer is not reachable on this hardware with the current models. That should be recorded as a measured result, not hidden.

## 10. Build order

Each milestone ends with tests, docs, a push, and something you can try on the Mac.

| Milestone | What you can try |
|---|---|
| **M1 Core + timing** | `spacedoc consult` in Terminal: identification, question turns, working list, Assess now → checked assessment. **Measures turn time on the Mac** (decides 8B vs 4B) |
| **M2 Web consult** | Chat page: working-list panel, quick replies, exam cards with equipment check, urgent card, roster pick-list |
| **M3 Consult record** | End-of-consult log view and export; thinking notes and summary; the summary fix |
| **M4 Practice + feedback** | Real/practice switch, scenario-card format and authoring guide, debrief form, feedback storage, scoreboard report |
| **M5 Review loop** | Must-ask checklists, clinician review and versioning of checklists and rules, regression runner |
| Later | Device readings from minis (Phase 2), voice, SBAR handoff to the ground, emergency protocol engine |

**Code touched:**
- a new `consult/` package (session state, question turn, case summary);
- the orchestrator (assessment from a case summary);
- the verifier (patient claims checked against the transcript);
- the web app (consult endpoints and page);
- audit events (`consult_start`, `consult_turn`, `consult_assessment`, `feedback`);
- the CLI (`spacedoc consult`);
- the case format (scenario-card fields).

## 11. Decisions on the open questions

| # | Question | Decision |
|---|---|---|
| 1 | Identification | ✅ Roster pick-list, no password, synthetic 4-person crew for Phase 1 |
| 2 | Reasoning log for question turns | ✅ Structured reasoning by default. A **deep log** option turns thinking on for every turn. When it is on, each turn shows both its actual time and an estimate of the time **without** deep log, so speed can still be judged |
| 3 | Red flags | ✅ SpaceDoc drafts a starter list with immediate steps, marked *unreviewed*, for clinicians to correct |
| 4 | Feedback | ✅ Changes only through clinician-reviewed, versioned edits; never automatic |
| 5 | Scripted stand-in patient | ✅ Not yet. Human sessions only for now |
| 6 | Who types | ✅ One person per consult. When the user is not the patient, SpaceDoc phrases questions for them to ask the patient ("Ask C3 whether…") and they type the patient's answers |

**How the deep-log estimate works.** Ollama reports how long it spent loading the model, reading the prompt and writing the reply. With thinking on, the reply includes the thinking notes. The estimate removes the share of writing time spent on the notes (by their share of the reply's characters). It is labelled as an estimate; turns run without deep log show measured times.

## 12. After the first practice consult

A NASA-run practice scenario of acute radiation syndrome (prodrome, latent phase, then GI bleeding, skin changes and hair loss, deep-space transit) showed:

| Finding | Change |
|---|---|
| The model never considered radiation; it chose hemorrhagic fever and asked about "recent travel" | Consult prompt c2.0 puts spaceflight causes first and rules out travel and outside contacts. A draft **spaceflight must-not-miss list** (`data/rules/must_not_miss.yaml`) is matched in code against what has been said; matched conditions are sent to the model, added back to the working list if it leaves them out, and passed to the assessment. An **exposure check** (spacewalk, radiation alert, atmosphere, payloads and animals, medication, others affected) follows the first message |
| Oxygen saturation 85% → 75% and systolic blood pressure 70 → 60 did not stop routine questions | **Vital-sign alerts** (`data/rules/vital_signs.yaml`, draft thresholds) read measurements from what is typed and pause the consult before the model is asked. Reversed readings such as 40/60 are flagged for recheck |
| "How do I use this urine dipstick" was ignored | Each turn starts with a **reply** to the user (labelled not checked) that acknowledges and answers. Equipment instructions come only from reviewed guides (Step 3) |
| Turns took 80–105 s: 600–770 tokens at about 8.4 tokens/s | The turn no longer copies the user's message into a facts list; lengths and counts are capped in the schema; **consult_model** allows a smaller model for question turns (e.g. `qwen3:4b`) to compare; the checker unloads a minute after use to free memory |
| The grounding checker was not installed, so every claim failed and the report gave no answer | A **startup model check** names any missing model and how to install it (Terminal warning, red banner on the page); an abstention caused by the checker says so |
| Five actions blocked over the patient's recorded weight (64 kg), with no explanation of where 64 kg came from | **Doses are calculated in code** (no second model pass) with the weight from the record; doses are checked as number plus unit; recorded values such as "64 kg" are allowed; the model's own dose is replaced by the calculator's; medications are checked against **allergies**; every flag is explained in plain language; the **patient record in use** is shown; every answer has **What to do now** |

### Next steps (agreed)

- **Step 3: equipment knowledge.** The ISS medical equipment inventory, compiled by the NASA team, replaces the generic T1 equipment list. A workflow adds each device's documents (manuals, procedures, checklists) to the knowledge base, tagged with the device, so **Show me how** can show checked steps from those documents. LEO scenarios first.
- **Step 4: speed on the laptop only.** SpaceDoc must work without Earth or any other computer. Compare `qwen3:8b` and `qwen3:4b` for question turns on the same scenarios, then tune the assessment (thinking budget, number of checks).
- **Knowledge gaps.** The knowledge base has no acute radiation syndrome source yet, so the assessment cannot support that diagnosis from sources. Candidate NASA documents go through the corpus workflow like any other.
