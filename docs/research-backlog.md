# Research Backlog

These are sources we want but have not read in full. They are **not cited anywhere**. An item moves into [references](references.md) (if it is a paper, preprint or official document) or into `corpus/manifest.yaml` (if it is also open-access with a permissive license) only after it has been read in full.

## Network access (checked Sept 2026)

All eight hosts the project needs were reachable: arxiv.org, pmc.ncbi.nlm.nih.gov, www.ncbi.nlm.nih.gov, www.nasa.gov, standards.nasa.gov, www.fda.gov, huggingface.co and ollama.com. humanresearchroadmap.nasa.gov, export.arxiv.org and the PMC Open Access bucket (pmc-oa-opendata.s3.amazonaws.com) also worked.

Two quirks:
- The PMC website serves PDFs behind a browser check, so scripts get an HTML page instead of the PDF. The manifest downloads PMC papers from the PMC Open Access bucket instead.
- www.fda.gov returns 401 to the `spacedoc corpus fetch` user-agent but serves the same files to a browser or curl. FDA documents are cited, not in the corpus, so this does not affect the manifest.

Still blocked (403 through this environment's network policy): ntrs.nasa.gov, www.nature.com (and its login host idp.nature.com), www.sciencedirect.com, europepmc.org, www.ebi.ac.uk and www.imdrf.org. Also blocked when checked in Oct 2026: afrri.usuhs.edu, www.cdc.gov, stacks.cdc.gov, remm.hhs.gov, dailymed.nlm.nih.gov, jts.health.mil, www.navsea.navy.mil and irp.fas.org. Most items below are waiting on one of these.

## Knowledge-base corpus

**In the manifest** (read in full; US Government public domain or CC BY): NASA-STD-3001 Vol 1 Rev C and Vol 2 Rev F; the HRP evidence reports on in-flight medical conditions (2017) and SANS (2022); the drug potency (2023) and ISS formulary expiration (2024) papers; the lunar dust (2022) and Martian dust (2025) reviews; and the CPR in extreme environments scoping review (2024). The 2022 SANS report replaces the 2017 version that was on the original list. Added in Oct 2026: eight more HRP evidence reports, listed below.

**Proposed additions** (read in full, permissive, not on the original candidate list):

| Document | License | Why |
|---|---|---|
| Hinkelbein et al., ESAM/DGLRM guideline for CPR in microgravity (2020), PMC7607644 | CC BY 4.0 | The recommendations behind the microgravity CPR protocol variants; cited as [R9] |

**Clinical sources (Oct 2026).** The practice consults showed the knowledge base had no clinical source for acute radiation syndrome, wounds, tetanus or decompression sickness, so the assessment abstained on them. Sources were proposed to fill that gap, and each is read in full and its license confirmed on the document itself before it goes in the manifest. NASA documents the NASA team adds go through the same steps.

*Added to the manifest.* NASA HRP evidence reports on humanresearchroadmap.nasa.gov, marked "Approved for Public Release", the same series and terms as the two HRP reports already in the corpus. Some co-authors are contractors or university staff, as in those two. The body of each was read in full and the reference lists skimmed. These are risk reports, not treatment protocols, so they support the assessment's reasoning but do not replace a clinical handbook.

| Report | What it gives SpaceDoc | Use in a consult |
|---|---|---|
| Acute Radiation Syndromes due to Solar Particle Events (2016) | Symptom phases and timing, dose thresholds, blood-count response, antiemetics and G-CSF as countermeasures, skin injury | High: the gap from the radiation practice consult |
| Renal Stone Formation (2024) | Presentation, differential, risk factors, ultrasound and urine checks, hydration and medicines aboard | High: the demo scenario |
| Decompression Sickness and Hypoxia (2023) | Signs and types of decompression sickness after a spacewalk, in-suit and cabin pressure treatment, hypoxia signs, oxygen | High: on the must-not-miss list |
| Injury and Compromised Performance due to EVA Operations (2022) | Hand, shoulder and foot injuries from the suit, heat stress, CO2 symptoms | Moderate |
| Host-Microorganism Interactions (2022) | Infections seen in flight and viral reactivation | Moderate |
| Ineffective or Toxic Medication (2023) | Drug stability and shelf life; repackaging shortens shelf life, while most drugs in sealed packaging keep their strength well past the expiry date | Low to moderate: drug quality, not dosing |
| Bone Fracture due to Spaceflight-induced Changes to Bone (2024) | Mostly bone loss and fracture-risk estimates | Low: little on treating a fracture |
| Injury due to Dynamic Loads (2021) | Mostly occupant-protection engineering for launch and landing; injury rates, mild head and spine injury | Low |

*Radiation sickness, added Oct 2026* (read in full; US Government works). These are terrestrial clinical guidance, tier C.

| Source | What it gives SpaceDoc | Notes |
|---|---|---|
| AFRRI, *Medical Management of Radiological Casualties*, 5th edition (2022) | First 72 hours: triage score from blood counts and vomiting, dose estimation, antiemetic and cytokine doses, skin injury, internal contamination and decorporation drugs, decontamination | No copyright notice; a DoD (Uniformed Services University) publication. Its tables are images, so retrieval cannot see them (triage categories, dose effects, time-to-vomiting biodosimetry, decorporation doses, potassium iodide). The university's site-wide policy page is on www.usuhs.edu, which this environment blocks |
| CDC, *Acute Radiation Syndrome: A Brochure for Physicians* | Conditions for ARS, the three syndromes and four stages, serial blood counts | Its syndrome thresholds are higher than AFRRI's |
| CDC, *Cutaneous Radiation Injury: A Brochure for Physicians* | Skin injury stages and grades, treatment by stage | Photos are third-party; only the text is used |
| HHS REMM (12 pages) | Severity grading and treatments to consider, time phases by dose range, cytokine label doses (updated 2026), combined injury and surgery timing, aspirin/NSAID caution, skin radiation syndrome, physical exam | Public domain; REMM asks to be credited as "Source: https://remm.hhs.gov". Menu and calculator pages were left out |

*Wounds, tetanus and trauma, added Oct 2026* (read in full; US Government works; tier C).

| Source | What it gives SpaceDoc | Notes |
|---|---|---|
| CDC, *Pink Book* chapter 21 (tetanus) and four CDC tetanus clinician pages (2026) | Tetanus signs and diagnosis, the wound vaccine and TIG rules, TIG doses (250 IU to prevent, 500 IU to treat), treatment | The 2026 CDC pages are the current rules; the Pink Book says its vaccine advice may be outdated. CDC's printable flow chart was left out because its text extracts out of order |
| JTS, *Human Space Flight Emergencies in the Prehospital Environment* (Dec 2025) | Hydrazine, nitrogen tetroxide and ammonia exposure (with methylene blue and pyridoxine doses), decompression illness, post-flight physiology | Written with NASA Space Medicine Operations, for rescue forces after landing |
| JTS prolonged-care guidelines: wound management (2017), nursing, wound care and splints (2025), burns (2017), analgesia and sedation (2017) | Wound irrigation, debridement, closure and dressings; nursing care over days; burn fluids and dressings; pain and sedation doses | Written for long delays before evacuation, with "minimum, better, best" options. The 2017 tetanus charts predate CDC's current rules |
| JTS, infection prevention (2021), eye trauma (2021), inhalation injury and toxic industrial chemicals (2016) | Antibiotics by wound type; eye injuries, abrasions, foreign bodies and chemical burns; ammonia, smoke, carbon monoxide and cyanide | Eye photos are third-party; only the text is used. The JTS site's terms page is on mrdc.health.mil, which this environment blocks |

Other JTS guidelines that may be worth adding next: ocular injuries and traumatic brain injury in prolonged field care, pain, anxiety and delirium, the Prolonged Casualty Care Guidelines, telemedicine, acute mental health, sepsis in prolonged field care, acute coronary syndrome, stroke, concussion, altitude emergencies (hypoxia) and extremity fractures.

Still not covered by any source in the corpus: drug labels. The sources for these and the remaining items are below.

*Probably US Government works; to read next.* These hosts were allowed in this environment in Oct 2026, except www.navsea.navy.mil, whose site refuses scripted downloads.

| Document | Host | Why |
|---|---|---|
| US Public Health Service, *The Ship's Medicine Chest and Medical Aid at Sea* (2003) | official copy still to locate; a copy is on irp.fas.org | Medical care in an isolated vessel without a physician, written for lay responders: close to a CMO's situation |
| DailyMed drug labels for the formulary medications | dailymed.nlm.nih.gov | Contraindications, interactions and label dosing, to check medication claims |
| US Navy Diving Manual, Revision 7 (decompression sickness chapters) | www.navsea.navy.mil | Signs and classification of decompression sickness |

*Probably not eligible* (license to confirm): StatPearls on the NCBI Bookshelf (CC BY-NC-ND); the WHO *International Medical Guide for Ships* (WHO copyright); IAEA safety reports on radiation injuries (IAEA copyright).

**Still to obtain:**

| Document | Blocker |
|---|---|
| Exploration medical condition list reports (e.g. NASA/TM-2019-220299, "Development of an Accepted Medical Condition List") | ntrs.nasa.gov blocked |
| CHeCS ISS medical hardware catalog (NTRS 20110022379) | ntrs.nasa.gov blocked |

**Not eligible for the corpus.** None of the candidates on the original list turned out to be NC or ND. These sources were read for the design docs but cannot be ingested:

| Source | License | Use instead |
|---|---|---|
| MedQA-CS benchmark data | CC BY-NC 4.0 | Evaluation reference only ([R3]) |
| Koo & Li 2016 (PMC4913118) | Publisher copyright; not in the PMC Open Access subset | Cited for methods ([R4]) |
| Hannun et al. 2019 (PMC6784839) | Author manuscript; not CC | Cited for the ECG mini ([R31]) |

## Papers and official documents not yet read

| Source | Status | Was used for |
|---|---|---|
| NTRS 20240011677, "Objective Structured Clinical Evaluation (OSCE) of an AI Clinical Decision Support System (CDSS) Tool" | ntrs.nasa.gov blocked | NASA's CMO-DA OSCE evaluation (docs 00, 08, 09) |
| NASA/TM-2017-219290, "Interpretation of NASA-STD-3001 Levels of Care for Exploration Missions" | ntrs.nasa.gov blocked; also superseded, since Vol 1 Rev B replaced the Levels of Care | Levels of Care (now cited from Vol 1 Rev C) |
| ASCEND 2022, "Communication Delays, Disruptions, and Blackouts for Crewed Mars Missions" | ntrs.nasa.gov blocked | Mars conjunction blackout length and period (removed from doc 00) |
| "Lunar dust induces minimal pulmonary toxicity compared to Earth dust" (2025) | www.sciencedirect.com blocked | Lunar dust toxicity (doc 04 now cites the lunar dust review, the HRP report and Vol 2) |
| Moody & Mark, MIT-BIH Arrhythmia Database paper | Not yet located and read | MIT-BIH facts (doc 05 now cites the PTB-XL paper's summary table) |
| Kermany et al., *Cell* 2018 (retinal OCT dataset) | Not yet opened | Fundus/OCT mini data |
| IMDRF, "Software as a Medical Device: Possible Framework for Risk Categorization" (N12, 2014) | www.imdrf.org blocked | SaMD risk category (doc 09, now marked orientation only) |
| Dettmers et al., QLoRA (arXiv:2305.14314) | Reachable, not yet read | 4-bit fine-tuning on 8 GB VRAM (doc 04 keeps "verify in practice") |
| Phi-4 and Llama 3 technical reports | Not yet read | Doc 02 model table |
| Papers on computers flown on the ISS (e.g. HPE Spaceborne Computer-2) | No paper found yet | Flight-hardware precedent (removed from doc 02) |
| Papers on TRISH's Hermes crew health platform | No paper found yet | Positioning (removed from docs 00 and 09) |

**Standards named in doc 09 but not read** (most are paywalled or not yet located): IEC 62304, ISO 14971, IEC 62366-1, FDA's Predetermined Change Control Plan guidance (fda.gov, reachable), NPR 7150.2 and NASA-STD-8739.8.

## Datasets to verify before use

Check each dataset's paper and license before training a mini:
- PTB-XL: the paper is read ([R30]); check the current PhysioNet release and the dataset license on the PhysioNet page.
- PhysioNet/CinC 2020 and 2021 12-lead ECG challenges
- PhysioNet/CinC 2016 heart sounds; ICBHI 2017 respiratory sounds
- BIDMC PPG and Respiration; MIMIC-IV and MIMIC waveforms; eICU (credentialed access)
- ISIC skin-lesion archive (mixed licenses)
- NHANES spirometry
- Public retinal OCT sets (e.g. Kermany et al.)

## Facts that live only in model cards

The papers-only rule means these are not cited. Check the model card or library page instead:
- Bespoke-MiniCheck-7B: training data and license
- MedGemma and MedGemma 1.5: license terms (Health AI Developer Foundations)
- Phi-4 and Llama 3.x: licenses
- Ollama tags and file sizes (checked on ollama.com in Sept 2026; see [phase1-getting-started.md](phase1-getting-started.md))

## Removed from the references

These were news articles, blogs, vendor or program pages, or curated lists, so they are no longer cited. Claims that depended on them were re-sourced to a paper or official document, or reduced to a general statement.

| Removed source | What happened to the claim |
|---|---|
| Google Cloud blog on NASA/Google CMO-DA testing (Aug 2025) | CMO-DA description removed; the HRP report's decision-support gap and AMIE ([R1]) are cited instead |
| Red Hat blog on RamaLama and NASA (Jun 2026) | RamaLama row and offline-test claim removed; container deployment kept as a later-phase task |
| The Register, NASA AI medic (27 Jun 2026) | CMO-DA accuracy figures (88/80/74%) removed |
| TRISH Hermes and TRISH funding pages | Hermes description and the ~$150K Catalyst figure removed |
| NASA IMM overview web page | Replaced by the HRP report (EMCL of 100 conditions) and Vol 1 Appendix E |
| Human Research Roadmap SANS risk page | Replaced by the 2022 SANS evidence report |
| CSA Bio-Monitor (Astroskin) page | 3-lead wearable claim removed; ISS 12-lead ECG cited from the HRP report |
| EdinburghNLP awesome-hallucination-detection list | Not used for any claim |
| MedGemma developer page; Google Research blog on MedGemma 1.5; Gemma 4 blog; Qwen3 blog | Replaced by the MedGemma, MedGemma 1.5, Gemma 4 and Qwen3 technical reports ([R25]–[R27], [R23]) |
| yage.ai analysis of Ollama's MLX backend | Ollama v0.19 claim removed; check the Ollama release notes |
| HPE Spaceborne Computer-2 page | Flight-hardware precedent removed (see above) |
| Covington, "5 Key Takeaways from FDA's Revised CDS Software Guidance" | Replaced by the FDA guidance itself ([R32]) |
| PhysioNet PTB-XL dataset page | Replaced by the PTB-XL paper ([R30]); the page is still the place to check the dataset license |
