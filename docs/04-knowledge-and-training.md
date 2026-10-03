# 04 — Knowledge, Training Data & the Aerospace Context Model

## 1. RAG first, fine-tune second

There are two ways to "teach" an LLM aerospace medicine:

| | Retrieval-augmented generation (RAG) | Fine-tuning |
|---|---|---|
| What it changes | What the model **reads** at answer time | The model's **weights** (how it behaves) |
| Analogy | Open-book exam with a curated reference shelf | Changing how the student thinks and writes |
| Citable? | Yes, every claim points to a passage | No, knowledge is diffused into weights |
| Updatable? | Swap a document and the change takes effect immediately | Requires retraining and re-validation |
| Hallucination effect | Reduces it (grounding) | Can *increase* confident errors if used to inject facts |

The original RAG paper showed both properties [[R15](references.md#r15)]. Human raters judged RAG's outputs more factual than a model without retrieval, and swapping the document index changed the answers without retraining: with a 2016 Wikipedia index the model named 70% of 2016 world leaders correctly, with a 2018 index 68% of 2018 leaders, and with the mismatched index only 12% and 4%.

**SpaceDoc decision:**
- **Knowledge comes through RAG.** This is required for SR-01 traceability and for the Earth-uplink update model (NFR-04).
- **Fine-tuning (LoRA) is reserved for behavior**, and only if base models fall short in evaluation:
  - reliably using the canonical JSON and tools
  - applying the environment context when reasoning
  - abstaining appropriately
  - role-register style

## 2. Knowledge base design

### 2.1 Source tiers

| Tier | Content | Examples | Licensing notes |
|---|---|---|---|
| **A: Mission-authoritative** | What this mission actually has and does | Mission formulary, equipment list, onboard procedures and checklists, crew baselines | Provided by the mission. Highest priority in retrieval |
| **B: Space-medicine evidence** | Spaceflight-specific risks and standards | NASA-STD-3001 Vol 1 & 2; NASA HRP Evidence Reports (e.g. SANS, medical conditions risk); the Exploration Medical Condition List behind the IMM; ExMC publications; open-access space-medicine papers | NASA public-release documents: generally usable, confirm per document |
| **C: General clinical references** | Terrestrial medicine | Open clinical guidelines; PubMed Central Open Access subset; NCBI Bookshelf titles; WHO guidance | Per-article/per-title licenses vary (CC BY vs CC BY-NC-ND). Track license in metadata |
| **D: Textbooks** | Deep reference | *Principles of Clinical Medicine for Space Flight*; *Fundamentals of Aerospace Medicine*; wilderness/austere medicine texts | Copyrighted. Needs a license or a publisher agreement before ingestion |

### 2.2 Chunk metadata (every passage carries this)

```yaml
source_id: nasa-hrp-sans-2022
title: "Evidence Report: Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS)"
tier: B
authority: NASA HRP
published: 2022-04
version_hash: 9f3c…
license: public-release
environment_tags: [microgravity, long-duration]   # used to filter/boost
topic_tags: [ophthalmology, neuro, SANS]
evidence_level: review                            # e.g. guideline / RCT / review / expert
supersedes: null
```

### 2.3 Retrieval pipeline

1. **Query rewrite:** the LLM expands the question, adding synonyms and spaceflight-specific terms.
2. **Hybrid search:** keyword search (BM25, which is strong on drug names and acronyms) plus dense vector search (strong on paraphrase).
3. **Filter and boost:** by environment tags that match the current tier, tier A over B/C, and recency.
4. **Rerank:** a cross-encoder reranker picks the top ~5–8 passages.
5. **Pass with IDs:** passages go to the orchestrator with citation IDs.

**Retrieval quality is measured separately** with recall@k on a labeled question→passage set. When the right passage never reaches the model, even perfect verification can only abstain.

## 3. Datasets for evaluation and tuning (not knowledge)

| Use | Candidates | Access |
|---|---|---|
| Medical QA sanity baselines | MedQA, PubMedQA, MedHallu (hallucination detection) | Open |
| Clinical-conversation evaluation | HealthBench (rubric-based) | Open |
| OSCE-style evaluation | SpaceOSCE, our own clinician-written cases ([08](08-validation-framework.md)) | Created with your clinicians |
| Vitals/EHR trends | MIMIC-IV, eICU (credentialed); open waveform sets | After CITI + PhysioNet credentialing |
| Device signals | See [05](05-spacedoc-minis.md) | Mostly open |

## 4. The aerospace context model

Every reasoning step, rule check and retrieval receives an **Environment Context** object (component C-12):

```yaml
mission_tier: T4            # LEO / cislunar / lunar surface / transit / Mars surface
gravity_g: 0.0
comm:
  one_way_delay_s: 840
  link_available: true
  next_blackout: 2027-01-14
mission_day: 142
habitat:
  cabin_pressure_kPa: …     # affects DCS risk, O2 delivery
  o2_fraction: …
  co2_mmHg: …               # Vol 2 limit: ppCO2 ≤ 3 mmHg, 1-h average [R6]
eva_schedule: [...]
radiation:
  cumulative_mSv_by_crew: {...}
evacuation: none
formulary_ref: inv-2026-09-01
equipment_ref: eq-2026-09-01
```

### 4.1 Environment-specific clinical knowledge (starter list for clinician review)

**Physical exam and procedures**

| Topic | Microgravity (T1, T2, T4) | Partial gravity (T3 0.17 g, T5 0.38 g) |
|---|---|---|
| Orthostatic vital signs / tilt | Not meaningful as on Earth (no gravitational pooling) | Reduced effect; interpret against partial-g baseline |
| Patient positioning (e.g. Trendelenburg, recovery position) | No "head-down" by posture; the patient must be restrained (e.g. Crew Medical Restraint System) | Partially effective; untested |
| CPR | Special techniques are needed. The ESAM/DGLRM guideline recommends **Evetts-Russomano** for immediate BLS and the **handstand** method, with the patient restrained on the Crew Medical Restraint System, for ALS [[R9](references.md#r9)] | Standard CPR is feasible but more demanding. There is no definitive hypogravity guideline, and the evidence is from manikin studies only [[R10](references.md#r10)] |
| Fluids and IVs | Air bubbles do not rise and separate; bags need pressure infusion | Partial separation |
| Fluid levels on imaging | Free fluid does not layer dependently the same way | Altered |
| Vomiting / airway | Emesis and droplets float; aspiration and contamination risk for cabin and crew | Reduced but present |
| Wound irrigation, bleeding | Fluids form floating globules; containment needed | Altered |

**Conditions with elevated or unique risk in spaceflight** (seed topics for the knowledge base and the differential engine's priors):
- **Space adaptation:** space motion sickness, headache, nasal congestion (fluid shift), back pain (spinal elongation), sleep disruption
- **SANS** (Spaceflight Associated Neuro-ocular Syndrome): optic disc edema, globe flattening, chorioretinal folds, hyperopic shift. About 70% of long-duration crew show one or more signs. The effect of mission duration is not yet known, although folds are thought to progress on longer missions. OCT is the most sensitive monitoring tool [[R8](references.md#r8)].
- **Musculoskeletal:** bone mineral loss, muscle atrophy, deconditioning. Injury risk on return to gravity and during partial-g EVA.
- **Renal stones:** increased risk from bone demineralization and hydration changes [[R7](references.md#r7)]. A classic "flank pain in space" differential.
- **EVA-related:** decompression sickness, suit-related abrasions and fingernail injuries, hypothermia/hyperthermia
- **Cardiovascular:** orthostatic intolerance after gravity transitions; arrhythmia monitoring
- **Radiation:** cumulative exposure, acute events from solar particle events
- **Immune:** latent viral reactivation, altered infection risk
- **Eye:** foreign bodies (floating debris), corneal abrasions
- **Behavioral health:** isolation, confinement, sleep (flagged for specialist design)
- **Pharmacology:**
  - A 2024 analysis of the ISS formulary covered 106 unique medications. Of the 91 with public shelf-life data, 54 have a terrestrial shelf life of 36 months or less in original packaging, and 14 expire within 24 months [[R12](references.md#r12)].
  - In a reanalysis of ISS stability studies, flight-stored medications degraded about 1.5 times faster than matched ground controls, and non-protective repackaging was the most harmful factor [[R11](references.md#r11)].
  - How drug absorption and metabolism change in flight is still being studied.
  - The formulary tool (C-07) must track expiry, and the rules engine must down-weight near-expiry items.

**Planetary dust**
- **Lunar dust:** Apollo crews reported transient eye and throat irritation, watery eyes and cough after dust was carried into the lunar module. The concern is that fine, jagged, electrostatically charged particles are re-aerosolized in the habitat. Long-term, a silicosis-like pneumoconiosis is the model risk, but chronic effects are unknown [[R13](references.md#r13)]. Apollo 14 dust was less toxic to the lung than crystalline silica and more toxic than titanium dioxide, and it irritated the eye only minimally [[R7](references.md#r7)]. NASA-STD-3001 Vol 2 limits dust particles under 10 µm to a time-weighted average of 0.3 mg/m³ for intermittent daily exposure over up to 6 months [[R6](references.md#r6)]. SpaceDoc should present the long-term risk as an area of uncertainty.
  - *Terminology note:* there is no standard condition called "volcanosis". Use **lunar dust toxicity** (acute irritation) and **pneumoconiosis/silicosis-like disease** (chronic, by analogy to silica exposure on Earth).
- **Mars dust:** very fine particles (about 2–8 µm) plus **perchlorates** (~0.5–1% of soil), which can inhibit thyroid iodide uptake. Also silica and iron oxides. Plausible endpoints include respiratory irritation and fibrosis, thyroid dysfunction and, speculatively, hematologic effects [[R14](references.md#r14)]. No samples have been returned, so the composition is uncertain. Vol 2 Rev F sets a Martian dust limit of 0.1 mg/m³ (time-weighted average, particles under 10 µm) for exposures of up to 30 days [[R6](references.md#r6)]; the lunar limit is not presumed to apply to Mars [[R7](references.md#r7)]. Monitoring thyroid function becomes relevant on Mars-surface missions.

This content goes into the knowledge base as tagged passages. The **feasibility subset** (what cannot be done where) is also encoded as deterministic rules in the verification layer ([03](03-hallucination-prevention.md) L6).

## 5. Fine-tuning plan (if and when needed)

1. **Baseline first:** measure base models plus RAG on the Phase 1 harness.
2. **Collect failures:** turn them into training examples, written or checked by clinicians. Synthetic data is allowed only with human review.
3. **Train:** LoRA [[R29](references.md#r29)] on the desktop GPU. Training an 8B model at 4-bit (QLoRA) may fit in 8 GB VRAM for small batches; verify this in practice (the QLoRA paper is still in the research backlog).
4. **Re-evaluate on held-out cases:** never on the cases used for training.
5. **Ship as a versioned adapter:** small, swappable and roll-back-able (NFR-04).

---

## How this works in AI systems: embeddings, and what LoRA does

**Embeddings.** An embedding model turns a passage of text into a vector, a list of ~1,000 numbers (1,024 for Qwen3-Embedding-0.6B [[R24](references.md#r24)]). It is trained so that passages with similar *meaning* end up near each other. "Renal calculus" and "kidney stone" land close together even though they share no words. Retrieval is then a nearest-neighbor search using cosine similarity (the angle between vectors). Keyword search complements it: the vector search can blur "metoprolol" and "metformin", but keyword search won't.

**LoRA (Low-Rank Adaptation).** Full fine-tuning updates all 8 billion weights. LoRA freezes them and learns a small correction for selected weight matrices: ΔW = B·A, where B and A are thin matrices of low rank r. On GPT-3 the paper found that a rank as small as 1 was enough for some tasks, and it tested ranks up to 64 [[R29](references.md#r29)]. Think of it as adding a low-order correction term to a large validated model instead of redesigning it. It is cheap to train and tiny to store: for GPT-3 the paper's LoRA checkpoint was 35 MB, against 350 GB for the full model. It can be subtracted to recover the original behavior.
