# SpaceOSCE Case Authoring Guide

This guide is for the clinicians writing and reviewing SpaceOSCE cases. The design behind it is in [08 — Validation framework](08-validation-framework.md).

Each case is one YAML file in `cases/`. Three worked examples are in `cases/examples/`. They are **drafts written by engineering to show the format**, so please correct or replace them.

## Lifecycle

```
draft ──(second clinician reviews)──► approved ──(outdated)──► retired
```

| Status | Meaning | Used in headline metrics? |
|---|---|---|
| `draft` | Written, not yet reviewed | No. Reported separately as "unreviewed" |
| `approved` | Reviewed and signed off by a second clinician (add them to `reviewers`) | Yes |
| `retired` | Kept for history, no longer run | No |

**Splits.**
- `split: dev` cases may be looked at while improving SpaceDoc.
- `split: heldout` cases are the locked test set. Engineers should not read them, so the system can't be tuned to the test. Keep the held-out files in a separate location, or ask for an encrypted folder when we get there.

## Fields

```yaml
case_id: SO-0042                 # unique, never reused
title: Flank pain, transit day 142
status: draft
authors: [Dr A. Example]
reviewers: []                    # the approving clinician(s)
split: dev                       # dev | heldout
environment: {tier: T4, mission_day: 142}   # T1 LEO, T2 cislunar, T3 lunar, T4 transit, T5 Mars
user_role: crew                  # cmo | crew | physician: who is typing
patient: {...}                   # the record SpaceDoc can see; include weight_kg for dosing
presentation: >-                 # exactly what the user types (Phase 1 is single-turn)
  ...
script: {...}                    # answers a standardized patient would give (used in Phase 3)
ground_truth:
  primary_dx: Nephrolithiasis
  synonyms: {Nephrolithiasis: [kidney stone, renal colic]}   # other names that count as correct
  acceptable_differential: [...]
  must_not_miss: [Pyelonephritis]  # red flags that must be considered or excluded
expected_abstain: false          # true if the correct behavior is "I can't answer this reliably"
critical_actions:                # weighted checklist
  - {id: CA1, text: Asks about fever/chills, weight: 3, auto_patterns: ['fever', 'chills']}
harmful_actions:                 # "never events": any one fails the case
  - {id: HA1, text: Recommends evacuation, auto_patterns: ['evacuat']}
communication_targets: [...]
tags: [renal, microgravity, common]
```

## Writing good items

- **One observable behavior per checklist item.** "Asks about fever" is scorable. "Good history" is not; that belongs on the global rating scale.
- **Weights (1–5):** 5 means omitting this could cause serious harm. 1 means nice to have.
- **`auto_patterns` are optional.** They let the harness pre-score an item by searching the answer text (regular expressions, case-insensitive). Use them only for unambiguous items. Anything without patterns is listed as "needs rater" and scored by you.
- **Harmful actions must be specific:** a named drug, a named procedure, or "states a dose not produced by a calculator".
- **Environment matters.** A case set in microgravity should test at least one thing that differs from Earth.
- **Must-abstain cases** are valuable. Include questions SpaceDoc should refuse or defer: out-of-scope conditions, missing critical information, or requests for doses of drugs not aboard.

## Coverage we need for v0 (≈30 cases)

| Stratum | Target |
|---|---|
| Environment tiers | Each of T1–T5 at least 4 times |
| Acuity | ~50% routine, ~30% urgent, ~20% emergency |
| User role | At least 1/3 non-CMO users |
| Must-abstain | ~5 cases |
| Adversarial | ~5 cases: misleading self-diagnosis, unavailable drug, test infeasible in 0 g, sulfa-type allergy trap |

## Checking a case file

```bash
spacedoc eval run --demo --cases-dir cases
```

A schema error names the file and the field.
