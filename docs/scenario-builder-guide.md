# Scenario Builder Guide (for clerks)

For the medical students and residents who write evaluation cases. The design behind it is in [11 — Evaluation system](11-evaluation-system.md).

Each case is a single clinical presentation: patient, condition, course of illness and the expected management. The author does not choose a mission. The author lists the environments in which the presentation is plausible, and each case is simulated in those environments with the local medical kit, gravity and communication delay. In each run, the presenting crewmember is portrayed as a standardized patient by an AI and the patient's physiology is simulated.

## 1. Opening the form

Download `medsim-eval/dist/scenario-builder.html` from the repository and open it in any browser. No internet connection, installation or account is needed.

Drafts are saved in the browser as you type. This copy is not reliable (a private window or cleared browser data loses it); **use Download files to keep your work.**

## 2. Sections

| Section | Instructions |
|---|---|
| 1. Case information | Obtain the next case ID from the coordinator (`MSE-0123`). Enter the **chief complaint** in brief clinical terms; it is used as the case title. Enter each author's full name and email or phone. Code the **presenting symptoms** from the ICD-10-CM list (search by term or code). |
| 2. Condition | Select from the 118 conditions in NASA's Integrated Medical Model (2023 CLiFFs). The CLiFF summary and its treated and untreated, best- and worst-case courses are shown. Every case is run under both courses; no selection is needed. |
| 3. Mission environment | Select each environment in which the presentation is plausible. Selections are pre-filled from the CLiFF incidence data (e.g. lunar dust exposure on the lunar surface only). Justify any environment outside CLiFF incidence under complicating factors. |
| 4. Patient history | Select the patient from the crew roster (20 synthetic astronaut records). The history loads from the record: PMH, PSH, medications (drug, route/form, dose, frequency), allergies or NKDA, social history and optional family history. Edit as needed for this case; **Reset to crew record** restores the original. |
| 5. Presentation | Select the **presenting party**: the patient (self-report), the crew medical officer, or a bystander crewmember. Medical training and familiarity are taken from the crew record and can be adjusted for this case. Enter the **chief complaint** in the patient's words, or the CMO's or crewmember's opening statement. Grade **historian reliability** from 1 (reliable) to 5 (unreliable) and specify how: imprecise, incorrect terminology, omits details, misreports values, inconsistent history, acutely distressed. **Emergent presentation** affects the crewmember's behaviour only. Under **History on direct questioning only**, enter each topic and the response given when asked. |
| 6. Medical timeline / course of illness | Optional. Enter only events that must occur at a fixed time, e.g. new symptom at T+6h, or vital signs at T+12h if untreated. Otherwise the course follows the CLiFF. |
| 7. Time-critical intervention | Optional. Describe the intervention, select the qualifying kit items (any one counts) and set the deadline. Timely intervention shifts the course toward the best case; delay or omission toward the worst case. |
| 8. Diagnosis and differential | The diagnosis is taken from the IMM condition and can be reworded. Enter the **etiology**, a ranked **differential diagnosis** and the **can't-miss diagnoses**. Add accepted synonyms where the wording varies. |
| 9. Scoring checklist | Case-specific checklist items (see §3). |
| 10. Complicating factors | Confounders and constraints, e.g. atypical presentation, limited stock, competing crew duties. |
| 11. Simulation settings | Case duration in simulated time. Injects (space weather, communication blackout, equipment failure) are reserved for CMO-DA integration. |
| 12. Review and submission | Set the status. Request physiology review if needed; a notes field for the physiology reviewer appears when requested. Resolve all errors under **Case check**, then **Download files**. |

**Times** are measured from presentation: `T+0`, `T+30m`, `T+6h`, `T+1d6h`.

**Side panel.** **Case check** lists errors and warnings as you write. The **Encyclopedia** searches CLiFF summaries, kit drugs (FDA labeling), reference ranges and spaceflight terms. **Medical capability by environment** shows the capabilities, formulary and equipment aboard in each selected environment.

## 3. Scoring checklist

Every case is scored against the **general rubric** (currently `general@0.2`):

- **Critical errors**: any one fails the run.
- **Six global rating domains, 1–5**: information gathering, diagnostic reasoning, management, safety and escalation, environment and resources, communication.
- **Two standard items**, scored automatically from section 8: correct diagnosis (+6) and correct etiology (+4, counted only with the diagnosis).

The author adds the **case-specific items**. Start from **Common checklist items** and edit them, or write new ones.

**Done / not done, or rated 1–5?** If two observers would agree from the transcript alone whether an action was done, score it done / not done. Quality of performance is covered by the global ratings. Use a rated item only when this case needs a quality judgment the domains do not capture, and write anchors for 1, 3 and 5.

**Write each item as an observable behaviour:**

| Avoid | Use |
|---|---|
| Examines the abdomen appropriately | Directs an exam for right lower quadrant tenderness, rebound or guarding |
| Gives adequate analgesia | Gives analgesia from the kit |
| Manages the allergy properly | Asks the nature of the penicillin reaction, or selects a regimen without cross-reactivity and states why |

Case check flags non-observable terms such as *appropriately*, *adequate* and *properly*.

**Weight.** Select **+ Expected** or **− Error**, then 1–10. Weight by clinical importance: a missed time-critical intervention outweighs a missed history question. Set a **deadline** (`T+8h`) when a late action is equivalent to an omitted one.

**Domain.** Assign each item to a domain; results are reported by domain.

**Requires equipment.** If an item depends on a device (e.g. point-of-care ultrasound), list it under **Requires equipment**. In environments without it, the item is scored not applicable rather than not done.

## 4. Submission

1. **Download files** saves two files: `MSE-0123.scenario.json` (the case) and `MSE-0123.rubric.json` (the scoring checklist).
2. Upload both to [`scenarios/inbox/`](../scenarios/inbox/) on GitHub (**Add file → Upload files**), or send them to the coordinator.
3. Set the status to *Ready for peer review* when the case is ready for a second clerk. **Print review sheet** produces a paper or PDF copy for the reviewer.

To revise a case, use **Open case files** and load both files. Files from the first version of the form are converted by the coordinator with `medsim migrate`.

## Lifecycle

```
draft ──► in_review ──► physiology_review (if requested) ──► approved ──► retired
```

The coordinator runs `medsim validate` on all files in the inbox. Approved cases move to `scenarios/approved/`. Approval requires at least one named reviewer in the file.
