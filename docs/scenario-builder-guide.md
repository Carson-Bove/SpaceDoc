# Scenario Builder Guide (for clerks)

This guide is for the medical students and residents who write evaluation scenarios. The design behind it is in [11 — Evaluation system](11-evaluation-system.md).

A **scenario** is one medical case: who gets sick, with what, how it unfolds, and what a good response looks like. You don't pick a mission. You say where the case could happen, and the system runs it in those mission environments for you, with each one's kit, gravity and comm delay. In every run, an AI plays the crewmember who talks to the assistant being tested, and a simulation plays the patient.

## 1. Get the form

Download `medsim-eval/dist/scenario-builder.html` from the repository and double-click it. It opens in any browser and needs no internet, install or account.

Your draft is saved in that browser as you type. That copy is a convenience only (a private window or cleared browser data loses it), so **use Download files to keep your work.**

## 2. Fill it in, top to bottom

| Section | What to do |
|---|---|
| 1. About | Get the next id from the coordinator (`MSE-0123`). Write the **chief complaint** in a few words; it becomes the title. Add your full name and an email or phone. Tag the **symptoms**: type a word or a code to search the standard ICD-10-CM list. |
| 2. Condition | Pick from the 118 conditions in NASA's Integrated Medical Model. The panel shows the CLiFF's summary and its best- and worst-case courses. Every scenario is run in both courses, so you don't choose one. |
| 3. Where can this happen? | Tick the environments where this case makes sense. They are pre-filled from the CLiFF (for example, lunar dust exposure only on the lunar surface) until you change them. |
| 4. Patient | Pick a crewmember from the roster of 20 fictional astronauts. Their chart fills in: past medical and surgical history, medications (name, form, dose, frequency), allergies or NKDA, social history, and optional family history. Change anything that should be different for this case. |
| 5. The conversation | Choose **who is talking** to the assistant: the patient, the CMO, or another crewmember. Their training and familiarity come from the roster; click a number to change them for this case. Write the **chief complaint** (patient) or **opening question** (CMO, crew). Set the **quality of their input** from 1 (clear) to 5 (very poor), and tick what kind: vague, wrong terms, missing details, misread numbers, contradictory, panicked. **Emergent** makes them act under time pressure. **Additional history if asked**: *if asked about X → they say Y*. |
| 6. Medical timeline / course of illness | Optional. Add only things that **must** happen at a set time: a symptom that appears at T+6h, or vital signs at T+12h if untreated. The simulation infers the rest from the CLiFF. |
| 7. Time-critical treatment | Optional. What counts (in words, plus kit items) and the deadline. On time leans the case to the best course; late or missing leans it to the worst. |
| 8. Correct answer | The diagnosis comes from the condition. Write the **etiology** (the cause), a **differential** in rank order, and the must-not-miss diagnoses. |
| 9. Rubric | Your checklist items (below). |
| 10. Complicators | Free text: anything that makes the case harder. |
| 11. Advanced | How long a run lasts. Injects (space weather, blackouts) are kept here for later. |
| 12. Review and save | Set the status. Ask for physiology review if the case needs it; the notes for the physiologist appear when you do. Fix everything in red in the Check panel, then Download files. |

**Times** are written from the start of the scenario: `T+0`, `T+30m`, `T+6h`, `T+1d6h`.

**The side panel** has the live **Check**, an **Encyclopedia** search (condition summaries, kit drugs from FDA labels, normal values, space terms) and **Where it runs**, which shows for each ticked environment what medicine is possible and what's aboard.

## 3. Writing the rubric

Every scenario is scored against the **general rubric** (currently `general@0.2`):

- **safety gates**: never events that fail the run
- **six 1–5 domains**: information gathering, diagnostic reasoning, management, safety and escalation, environment and resources, communication
- **two standard items**, scored automatically from your correct answer: naming the diagnosis (+6) and naming the etiology (+4, only counted with the diagnosis)

You add the **checklist items** specific to your case. The quickest way is **Add common items with one click**, then edit them. Or write your own.

**Yes/no or rated?** If two people could answer yes or no from the transcript alone, it's a yes/no item. If the question is "how well", the domains already cover it. Add a rated item only when this case needs a "how well" the domains don't capture, and then write what a 1, a 3 and a 5 look like.

**Good items describe what an observer would see:**

| Instead of | Write |
|---|---|
| Examines the abdomen appropriately | Directs an exam that checks right lower quadrant tenderness and rebound or guarding |
| Gives adequate analgesia | Gives pain relief from the kit |
| Manages the allergy properly | Asks what the penicillin reaction was, or chooses a regimen that avoids it and says why |

The Check panel flags words like *appropriately*, *adequate* and *properly*.

**Points.** Click **+ do** or **− don't**, then 1–10. Give more points to what matters more clinically: a missed time-critical treatment outweighs a missed history question. Give an item a **deadline** (`T+8h`) when doing it late is as bad as not doing it.

**Domain.** Tag each item with its domain; reports group results by domain.

**Equipment.** If an item only makes sense when a device is aboard (e.g. "uses the ultrasound"), add it under *Only applies when this equipment is aboard*. In environments without it, the item is not applicable rather than failed.

## 4. Submit

1. Download files. This saves two files: `MSE-0123.scenario.json` and `MSE-0123.rubric.json`.
2. Upload both into [`scenarios/inbox/`](../scenarios/inbox/) on GitHub (**Add file → Upload files**), or send them to the coordinator.
3. Set the status to *Ready for review* when you want a second clerk to review it. Use **Print review sheet** to give them a paper or PDF copy.

To revise a scenario, use **Open existing files** and load both files. Files from the first version of the form need converting first: the coordinator runs `medsim migrate` on them.

## Lifecycle

```
draft ──► in_review ──► physiology_review (if requested) ──► approved ──► retired
```

The coordinator runs `medsim validate` on everything in the inbox. Approved scenarios move to `scenarios/approved/`. Approval needs at least one reviewer in the file.
