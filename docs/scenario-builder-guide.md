# Scenario Builder Guide (for clerks)

This guide is for the medical students and residents who write evaluation scenarios. The design behind it is in [11 — Evaluation system](11-evaluation-system.md).

A **scenario** is one medical event in one part of a NASA Design Reference Mission (DRM): who gets sick, with what, on which mission day, and what happens around them. An AI plays the crewmember who talks to the assistant being tested, a simulation plays the patient, and your **rubric** says what a good response looks like.

## 1. Get the form

Download `medsim-eval/dist/scenario-builder.html` from the repository and double-click it. It opens in any browser and needs no internet, install or account.

Your draft is saved in that browser as you type. That copy is a convenience only (a private window or cleared browser data loses it), so **use Download files to keep your work.**

## 2. Fill it in, top to bottom

| Section | What to do |
|---|---|
| 1. About | Ask the coordinator for the next id (`MSE-0123`). Write a short title. |
| 2. Mission | Pick the DRM, the phase, the mission day and the patient. The right-hand panel shows the environment, and the habitat's **What medicine is possible here** and **What's aboard**. Read them: they're what the crew actually has. |
| 3. Condition | Pick from the 118 conditions in NASA's Integrated Medical Model. The table shows the CLiFF's best- and worst-case courses. Leave **Course** on *Let the simulation decide* unless the scenario only makes sense one way. |
| 4. Patient | Age, weight, allergies, regular medications, relevant history. |
| 5. Conversation | The crewmember's first message, who they are, their medical training, how they act, and the facts they'll give if asked. Write facts the way they'd say them. |
| 6. Timeline (optional) | Only things that **must** happen at a set time: a symptom that appears at T+6h, vital signs at T+12h if untreated. The simulation infers the rest from the CLiFF. |
| 7. Events (optional) | Space weather, dust storms, comm blackouts, equipment failures. |
| 8. Branches (optional) | Make the course depend on what the assistant does, e.g. "if no antibiotic by T+24h, the course becomes the worst case". |
| 9. Complicators | Free text: anything that makes the case harder. |
| 10. Correct answer | Leading diagnosis, acceptable alternatives, must-not-miss diagnoses. |
| 11. Rubric | Your checklist items (below). |
| 12. Check and save | Fix everything in red in the Check panel, then Download files. |

**Times** are written from the start of the scenario: `T+0`, `T+30m`, `T+6h`, `T+1d6h`.

## 3. Writing the rubric

Every scenario is scored against the **general rubric** (currently `general@0.1`). It has:

- **safety gates**: never events that fail the run
- **six 1–5 domains**: information gathering, diagnostic reasoning, management, safety and escalation, environment and resources, communication

You don't rewrite those. You add the **checklist items** that are specific to your case.

**Yes/no or rated?** If two people could answer yes or no from the transcript alone, it's a yes/no item. If the question is "how well", the domains already cover it. Add a rated item only when this case needs a "how well" the domains don't capture, and then write what a 1, a 3 and a 5 look like.

**Good items describe what an observer would see:**

| Instead of | Write |
|---|---|
| Examines the abdomen appropriately | Directs an exam that checks right lower quadrant tenderness and rebound or guarding |
| Gives adequate analgesia | Gives pain relief from the kit |
| Manages the allergy properly | Asks what the penicillin reaction was, or chooses a regimen that avoids it and says why |

The Check panel flags words like *appropriately*, *adequate* and *properly*.

**Points.** Use +1 to +10 for things it should do and −1 to −10 for things it shouldn't, with more points for what matters more clinically. A missed time-critical treatment is worth more than a missed history question. Give an item a **deadline** (`T+8h`) when doing it late is as bad as not doing it.

**Domain.** Tag each item with the domain it belongs to. Reports group results by domain, so this shows where an assistant is weak.

## 4. Submit

1. Download files. This saves two files: `MSE-0123.scenario.json` and `MSE-0123.rubric.json`.
2. Upload both into [`scenarios/inbox/`](../scenarios/inbox/) on GitHub (**Add file → Upload files**), or send them to the coordinator.
3. Set **Status** to *Ready for review* when you want a second clerk to review it. Use **Print review sheet** to give them a paper or PDF copy.
4. If the case depends on detailed physiology, set **Physiology review** to *Request review* and leave notes for the physiologist.

To revise a scenario, use **Open existing files** and load both files.

## Lifecycle

```
draft ──► in_review ──► physiology_review (if requested) ──► approved ──► retired
```

The coordinator runs `medsim validate` on everything in the inbox. Approved scenarios move to `scenarios/approved/`. Approval needs at least one reviewer in the file.
