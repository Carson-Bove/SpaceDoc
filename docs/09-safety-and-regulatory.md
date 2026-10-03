# 09 — Safety Case, Regulatory Landscape & Path to Real Use

> This is an engineering overview, not legal or regulatory advice. Before any proposal claims a regulatory pathway, confirm it with a regulatory specialist, and with NASA OCHMO (Office of the Chief Health & Medical Officer) for spaceflight use.

## 1. Which rules apply?

### 1.1 Terrestrial (FDA): SpaceDoc would be a medical device

The FDA's **Clinical Decision Support (CDS) Software guidance** was revised in January 2026 [[R32](references.md#r32)]. It excludes software from device regulation only if it meets *all four* statutory criteria. Roughly, the software must:
1. not acquire, process or analyze medical images or signals
2. display or analyze medical information
3. support (not replace) a **healthcare professional's** decision
4. let the professional independently review the basis for its recommendations

SpaceDoc fails criterion 1 by design, because minis analyze ECG, ultrasound and other signals. It also targets non-HCP users (crewmembers), which conflicts with criterion 3. Its emergency functions would also struggle with criterion 4: the guidance considers the time-critical nature of a decision, because users under time pressure are more likely to rely on the software instead of reviewing its basis [[R32](references.md#r32)]. **So any terrestrial version is Software as a Medical Device (SaMD).** The design should follow device-grade processes from the start. This is cheaper than retrofitting them later.

Relevant frameworks:

| Framework | What it governs | SpaceDoc implication |
|---|---|---|
| **IMDRF SaMD risk categorization** | Risk category from the seriousness of the healthcare situation and the significance of the information the software provides | Emergency and diagnostic functions in critical situations would likely fall in the highest-risk category; confirm against the IMDRF document |
| **IEC 62304** | Medical device software lifecycle; software safety classes A/B/C | Functions that could contribute to serious injury or death are **Class C**: rigorous requirements, architecture, verification and traceability (this repo's ID scheme starts that) |
| **ISO 14971** | Risk management for medical devices | Hazard analysis (§2), risk controls, residual risk evaluation |
| **IEC 62366-1** | Usability engineering | Emergency mode, role adaptation, alarm design ([06](06-records-and-monitoring.md) §4) |
| **FDA/Health Canada/MHRA Good Machine Learning Practice (GMLP)** | Ten ML-specific principles, including representative data, test sets independent of training data, human-AI team performance, and monitoring of deployed models [[R33](references.md#r33)] | Held-out case bank, human-with-AI studies ([08](08-validation-framework.md) §4) |
| **FDA Predetermined Change Control Plans (PCCP)** | Pre-authorized ways an ML device may be updated | Matches the versioned KB, model and adapter update design (NFR-04) |

Only the FDA CDS guidance and GMLP have been read in full for this project. The IMDRF framework, IEC 62304, ISO 14971, IEC 62366-1 and FDA's PCCP guidance are listed in the [research backlog](research-backlog.md); treat their rows as orientation until they have been read.

### 1.2 Spaceflight (NASA)

| Standard | Relevance |
|---|---|
| **NASA-STD-3001 Vol 1 (Crew Health) & Vol 2 (Human Factors, Habitability & Environmental Health)** | Vol 1: Health and Medical Care requirements (which replaced the Levels of Care in Revision B), in-mission medical capabilities including autonomous medical care, and medical records [[R5](references.md#r5)]. Vol 2: medical equipment usable by non-physician crew, and crew-interface requirements for usability, workload, error rates, alerts and decision aids [[R6](references.md#r6)] |
| **NPR 7150.2 (NASA Software Engineering Requirements)** | Software classification. Crew-health-related software will likely be a high class, with correspondingly heavy process (not yet read; see backlog) |
| **NASA-STD-8739.8 (Software Assurance & Software Safety)** | Independent assurance, safety-critical software analysis (not yet read; see backlog) |
| **HRP Evidence Reports & ExMC** | Evidence base and gap definitions the system should address, e.g. the lack of computed medical decision support for exploration missions [[R7](references.md#r7)], [[R8](references.md#r8)] |

## 2. Hazard analysis (FMEA-style, initial)

Severity (S) and likelihood (L) are on a 1–5 scale, and detectability (D) is on a 1–5 scale where 5 = hard to detect. RPN = S × L × D. These values are initial estimates to be refined with clinicians.

| Hazard | Cause | Effect | S | L | D | RPN | Controls |
|---|---|---|---|---|---|---|---|
| Wrong dose shown | LLM-generated number | Overdose/underdose | 5 | 2 | 3 | 30 | SR-02 calculators only; numeric integrity check; R2+ confirmation |
| Missed critical diagnosis | Omission, poor retrieval | Delayed treatment | 5 | 3 | 4 | 60 | Must-not-miss lists in Dx engine; red-flag prompts; eval metric; CMO review |
| Infeasible recommendation | Terrestrial bias | Wasted time, harm | 4 | 3 | 2 | 24 | Environment rules engine; adversarial tests |
| Fabricated fact | Hallucination | Wrong decision | 4 | 3 | 3 | 36 | L1–L5 verification layers; abstention |
| Mini misread of noisy signal | Artifact, domain shift | False alarm or missed arrhythmia | 4 | 3 | 3 | 36 | SQI gating, OOD flag, raw data retained, deterministic features |
| LLM unavailable in emergency | Crash, thermal, power | Loss of guidance | 5 | 2 | 1 | 10 | Deterministic protocol engine independent of the LLM (SR-10) |
| Alarm fatigue | Too many alerts | Real alert ignored | 4 | 4 | 4 | 64 | Tiering, hysteresis, persistence, precision review |
| Privacy breach within crew | Access-control failure | Crew trust and cohesion harm | 3 | 2 | 3 | 18 | Role-based access (SR-12), audit |
| Over-reliance / automation bias | Confident presentation | CMO stops thinking critically | 4 | 3 | 5 | 60 | Calibrated uncertainty display, "why?" always available, training, human-with-AI studies |
| Corrupted model weights | Radiation bit flips | Erratic outputs | 4 | 2 | 4 | 32 | Weight checksums, ECC, verifier independence |
| Prompt injection via documents | Malicious or garbled content | Unsafe instructions followed | 4 | 1 | 3 | 12 | Data/instruction separation, rules engine |

The highest RPNs (alarm fatigue, missed diagnosis, automation bias) are **human–system interaction** risks, not model-accuracy risks. They are addressed through design and human-factors studies, not just a better model.

## 3. Safety case structure

A safety case is a structured argument, supported by evidence, that the system is acceptably safe for a specific use in a specific context. Proposed top-level argument (GSN-style):

- **G0:** SpaceDoc is acceptably safe as decision support for a trained CMO in analog mission conditions.
  - **G1:** Hazards are identified and controlled. *Evidence:* FMEA (§2), control tests.
  - **G2:** Clinical outputs are grounded and verified. *Evidence:* hallucination metrics ([03](03-hallucination-prevention.md) §3).
  - **G3:** Clinical performance is adequate. *Evidence:* SpaceOSCE results ([08](08-validation-framework.md)).
  - **G4:** Humans use it well. *Evidence:* human-with-AI crossover studies and emergency simulations.
  - **G5:** The system degrades safely. *Evidence:* fault-injection tests (SR-10).
  - **G6:** Changes are controlled. *Evidence:* versioning, regression suite, PCCP-style update plan.

## 4. Path to real use

| Stage | Setting | What it proves |
|---|---|---|
| Bench | Lab, simulated cases | Technical feasibility, component metrics |
| Clinical simulation | Your residents/students in simulation lab | Decision-support benefit, safety |
| Analog missions | **HERA** (NASA JSC habitat), **CHAPEA** (year-long Mars simulation, JSC), **MDRS** (Mars Desert Research Station, Utah), **HI-SEAS**, Antarctic stations (e.g. Concordia) | Real crews, isolation, delay, operational fit |
| Flight demo | ISS payload / commercial station | Flight environment |

### Funding and collaboration landscape

- **TRISH** (Translational Research Institute for Space Health): check its current funding calls. The program pages consulted during early research are listed in the [research backlog](research-backlog.md); confirm amounts and priorities directly before writing a proposal.
- **NASA SBIR/STTR:** small-business pathway. Check current solicitation topics for crew health and autonomous medical care.
- **NASA HRP solicitations:** research announcements tied to ExMC gaps.

### Positioning relative to existing work

| Effort | Focus | SpaceDoc's complementary angle |
|---|---|---|
| NASA ExMC gap: no computed medical decision support for exploration missions [[R7](references.md#r7)] | Evidence gap | SpaceDoc targets this gap directly, with an explicit hallucination layer, device minis, longitudinal monitoring, role adaptation and an open design |
| Google **AMIE** [[R1](references.md#r1)] | Conversational diagnostic AI (terrestrial) | Model for rigorous OSCE-style evaluation methodology |

NASA and TRISH projects on crew medical assistants and crew health data platforms are listed in the [research backlog](research-backlog.md). Add them to this table once their reports have been read in full.

**Recommendation:** position SpaceDoc as **complementary and interoperable**, especially its verification layer and SpaceOSCE framework, rather than as a competitor. Partnerships and analog access are more likely that way.

---

## How this works in AI systems: why ML needs extra safety engineering

Traditional software is **specified**: you can trace every behavior to a line of code. An ML model's behavior is **learned**: it emerges from data, so you can't inspect it line by line. Three consequences:

1. **Verification shifts from inspection to testing.** You establish performance statistically on representative data. This is why the held-out case bank matters so much.
2. **Distribution shift.** A model validated on Earth data can behave differently on space data. It's like a sensor calibrated at sea level being used at altitude. The fixes are to monitor inputs (OOD detection) and keep validating in the target environment.
3. **Locked vs adaptive models.** A model that keeps learning after deployment is a moving target for certification. SpaceDoc uses **locked, versioned models**. Improvements ship as new, re-validated versions with rollback (the PCCP idea).
