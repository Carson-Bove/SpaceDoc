# 09 — Safety Case, Regulatory Landscape & Path to Real Use

> This is an engineering overview, not legal or regulatory advice. Before any proposal claims a regulatory pathway, confirm it with a regulatory specialist, and with NASA OCHMO (Office of the Chief Health & Medical Officer) for spaceflight use.

## 1. Which rules apply?

### 1.1 Terrestrial (FDA): SpaceDoc would be a medical device

The FDA's **Clinical Decision Support (CDS) Software guidance** was revised in January 2026. It excludes software from device regulation only if it meets *all four* statutory criteria. Roughly, the software must:
1. not acquire, process or analyze medical images or signals
2. display or analyze medical information
3. support (not replace) a **healthcare professional's** decision
4. let the professional independently review the basis for its recommendations

SpaceDoc fails criterion 1 by design, because minis analyze ECG, ultrasound and other signals. It also targets non-HCP users (crewmembers), which conflicts with criterion 3. **So any terrestrial version is Software as a Medical Device (SaMD).** The design should follow device-grade processes from the start. This is cheaper than retrofitting them later.

Relevant frameworks:

| Framework | What it governs | SpaceDoc implication |
|---|---|---|
| **IMDRF SaMD risk categorization** | Risk category from *state of the situation* (critical / serious / non-serious) × *significance of information* (treat or diagnose / drive / inform) | Emergency and diagnostic functions in critical situations fall in the highest category (IV) |
| **IEC 62304** | Medical device software lifecycle; software safety classes A/B/C | Functions that could contribute to serious injury or death are **Class C**: rigorous requirements, architecture, verification and traceability (this repo's ID scheme starts that) |
| **ISO 14971** | Risk management for medical devices | Hazard analysis (§2), risk controls, residual risk evaluation |
| **IEC 62366-1** | Usability engineering | Emergency mode, role adaptation, alarm design ([06](06-records-and-monitoring.md) §4) |
| **FDA/Health Canada/MHRA Good Machine Learning Practice (GMLP)** | ML-specific principles: data management, independence of test data, human-AI team performance, monitoring | Held-out case bank, human-with-AI studies ([08](08-validation-framework.md) §4) |
| **FDA Predetermined Change Control Plans (PCCP)** | Pre-authorized ways an ML device may be updated | Matches the versioned KB, model and adapter update design (NFR-04) |

### 1.2 Spaceflight (NASA)

| Standard | Relevance |
|---|---|
| **NASA-STD-3001 Vol 1 (Crew Health) & Vol 2 (Human Factors, Habitability & Environmental Health)** | Levels of Care, medical capability requirements, human-factors requirements for crew interfaces |
| **NPR 7150.2 (NASA Software Engineering Requirements)** | Software classification. Crew-health-related software will likely be a high class, with correspondingly heavy process |
| **NASA-STD-8739.8 (Software Assurance & Software Safety)** | Independent assurance, safety-critical software analysis |
| **HRP Evidence Reports & ExMC** | Evidence base and gap definitions the system should address |

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

- **TRISH** (Translational Research Institute for Space Health, Baylor College of Medicine with Caltech and MIT, funded by NASA HRP): Catalyst grants for proof-of-concept work (reported up to ~$150K / 1 year). Research priorities include medical system architecture (**Hermes**, an edge-computing crew health platform with per-crewmember AI agents).
- **NASA SBIR/STTR:** small-business pathway. Check current solicitation topics for crew health and autonomous medical care.
- **NASA HRP solicitations:** research announcements tied to ExMC gaps.

### Positioning relative to existing work

| Effort | Focus | SpaceDoc's complementary angle |
|---|---|---|
| NASA **CMO-DA** (Google; offline via Red Hat RamaLama on Spaceborne Computer ground twin) | LLM + VLM clinical decision support, OSCE-tested | Explicit hallucination layer, device minis, longitudinal monitoring, role adaptation, open design |
| TRISH **Hermes** | Edge crew health data platform | SpaceDoc could plug into Hermes-like platforms as the reasoning and verification layer |
| Google **AMIE** | Conversational diagnostic AI (terrestrial) | Model for rigorous OSCE-style evaluation methodology |

**Recommendation:** position SpaceDoc as **complementary and interoperable**, especially its verification layer and SpaceOSCE framework, rather than as a competitor. Partnerships and analog access are more likely that way.

---

## How this works in AI systems: why ML needs extra safety engineering

Traditional software is **specified**: you can trace every behavior to a line of code. An ML model's behavior is **learned**: it emerges from data, so you can't inspect it line by line. Three consequences:

1. **Verification shifts from inspection to testing.** You establish performance statistically on representative data. This is why the held-out case bank matters so much.
2. **Distribution shift.** A model validated on Earth data can behave differently on space data. It's like a sensor calibrated at sea level being used at altitude. The fixes are to monitor inputs (OOD detection) and keep validating in the target environment.
3. **Locked vs adaptive models.** A model that keeps learning after deployment is a moving target for certification. SpaceDoc uses **locked, versioned models**. Improvements ship as new, re-validated versions with rollback (the PCCP idea).
