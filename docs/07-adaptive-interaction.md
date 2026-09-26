# 07 — Adaptive Interaction: Who Am I Talking To?

## 1. Identity and role profiles

The interaction layer (C-01) identifies the user at session start (login, badge, or voice enrollment in later phases) and loads a **role profile**:

```yaml
user_id: C2
display_name: "Flight Engineer"
role: crew                      # cmo | physician | crew | commander | earth_surgeon
medical_literacy: basic         # expert | clinical | informed | basic
authority:
  can_authorize: []             # e.g. [R2] for the CMO
  record_access: self
preferences:
  units: SI
  language: en
  verbosity: concise
training:                       # procedures this person has trained on
  - bls_microgravity
  - ultrasound_basic
```

Profiles are editable by the CMO. SpaceDoc may *suggest* raising a literacy level (e.g. "this user consistently uses clinical terminology") but never changes it on its own.

**Patient vs operator.** The user may be the patient ("my back hurts"), an operator acting on someone else ("the commander is unconscious"), or the CMO consulting. SpaceDoc asks explicitly when this is ambiguous, because it changes privacy, authority and tone.

## 2. Same facts, different words (SR-09)

Content is separated from presentation:

1. The orchestrator produces **one canonical answer**: structured claims, citations, actions and uncertainty. It is written clinically.
2. The verification layer checks it ([03](03-hallucination-prevention.md)).
3. A **renderer** turns it into text for the specific user.
4. The rendered text is **re-verified** against the canonical answer. This is an entailment check plus exact matching of every number, drug, unit and action.

The same finding, rendered three ways:

| Register | Rendering |
|---|---|
| **Expert / CMO** | "Right CVA tenderness, colicky flank pain radiating to groin, microscopic hematuria on dipstick. Leading Dx: nephrolithiasis (bone demineralization + reduced urine volume, mission day 142). Recommend renal POCUS for hydronephrosis. Analgesia per formulary: see dosing card [calc]." |
| **Informed crew** | "The pattern (pain in your side that comes in waves, spreading toward the groin, and a trace of blood in the urine) most likely points to a kidney stone. Kidney stones are more common in spaceflight because bones release calcium. The CMO can confirm with a quick ultrasound of the kidney." |
| **Basic / stressed** | "This is probably a kidney stone. That's painful but usually not dangerous. 1) Drink water now. 2) I've alerted the CMO, who will come check with the ultrasound. 3) If you get a fever or chills, tell me right away." |

Rules for the renderer:
- Never drop a **red flag** or **safety instruction** when simplifying.
- Define a technical term the first time it is used in a lower register.
- Numbers stay exact: never "a couple of pills" for "2 tablets".
- Keep the uncertainty visible ("probably", "most likely") and calibrated to the canonical confidence.

## 3. Emergency mode

Triggered by keywords, device warnings, or the CMO's emergency button:

- **The protocol engine drives** (C-05). One step at a time, large text, voice read-out, and hands-free "next / repeat / back".
- **Timers and counters** are built in: compression cycles, medication intervals, elapsed time.
- **Role-aware assignment:** "Engineer, you are on compressions. CMO, prepare the defibrillator."
- **Environment-adapted steps:** the protocol variant for the current gravity tier, e.g. microgravity CPR technique and restraint.
- **The LLM is off the critical path.** It can answer side questions ("what does 'shockable rhythm' mean?"), and those answers are fully verified.
- **Automatic documentation:** every step, time and device reading goes to the record. An event summary is generated for the CMO to sign.

## 4. Conversation design

- **Structured intake.** For symptoms, SpaceDoc follows a history-taking structure (onset, location, duration, character, aggravating/relieving factors, radiation, timing, severity; plus a targeted review of systems). It asks one or two questions at a time.
- **Ask, don't assume.** If a key discriminator is missing, ask for it before answering. This also counters sycophancy: the user's self-diagnosis is treated as a hypothesis to test.
- **Explain on demand.** "Why?" shows the sources and the reasoning steps (FR-13).
- **Time-delay awareness.** If Earth input would help and the link allows, SpaceDoc offers to prepare a packet and says when a reply could arrive.

## 5. Earth handoff: the SBAR packet

```
S (Situation):   C3, 34M, flank pain 6h, mission day 142, transit (T4), delay 14 min
B (Background):  No prior stones. Meds: none. Allergies: none. Fluid intake ↓ last 5 days (logged)
A (Assessment):  Likely R nephrolithiasis (POCUS: mild hydronephrosis). Vitals stable. SpaceDoc confidence: moderate
R (Request):     Confirm analgesic plan & tamsulosin use; advise on thresholds for escalation
Attachments:     POCUS clips (3), vitals 72h, urine dipstick photo, SpaceDoc audit excerpt
```

---

## How this works in AI systems: system prompts, and why we render twice

An LLM's behavior is steered by a **system prompt**: hidden instructions placed before the conversation ("You are SpaceDoc… The user is a flight engineer with basic medical literacy…"). It is powerful but soft. The model *usually* follows it, not always.

That's why SpaceDoc doesn't rely on one prompt that says "be accurate *and* simple". Asking a model to do both at once is where meaning drifts. Instead, the pipeline has stages:
- Stage 1 is optimized for correctness and gets checked.
- Stage 2 is optimized for clarity and gets checked against stage 1.

This is the same idea as separating a controller's setpoint computation from its actuator command shaping, with a feedback check on each stage.
