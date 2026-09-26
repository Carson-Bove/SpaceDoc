# 05 — SpaceDoc Minis (Device-Level Models)

A **SpaceDoc mini** is a small, specialized neural network (CNN/DNN) that runs on or next to a medical device. It turns raw signals into structured, quality-scored **findings** and passes them to SpaceDoc over the device bus.

**Why have minis?**
- **Speed:** raw ECG, ultrasound or PPG data never has to pass through the LLM. Analysis happens at the source in milliseconds.
- **Accuracy:** a purpose-trained signal model far outperforms a general LLM at reading waveforms.
- **Bandwidth and power:** only compact findings travel on the bus, not raw streams.
- **Resilience:** findings and alarms still work when the main system is busy or degraded (SR-10).

## 1. Design principles

1. **Findings, not diagnoses.** A mini reports "irregularly irregular rhythm, no discernible P waves, AF pattern p = 0.93". It does not say "patient has atrial fibrillation". Diagnosis combines findings with context, and that happens in SpaceDoc with a human in the loop.
2. **Quality before inference.** Every input first gets a **signal-quality index (SQI)**. Below a threshold, the mini reports `quality: insufficient` and suggests a fix ("lead II noisy, check electrode contact") instead of guessing.
3. **Know when you're out of your depth.** An **out-of-distribution (OOD)** detector flags inputs unlike the training data, such as a new device, unusual physiology, or microgravity-shifted signals. OOD findings are marked non-diagnostic.
4. **Calibrated confidence.** Reported probabilities must mean what they say: of findings reported at 0.9, about 90% should be correct. Minis are calibrated (e.g. temperature scaling) and calibration is re-checked in validation.
5. **Classical features alongside learned ones.** Where algorithms are well established (heart rate, RR intervals, QRS duration, QTc), compute them deterministically and report them next to the neural findings. Disagreement between the two is itself a signal.
6. **Raw data is never thrown away.** Every report references the raw recording, so a human or SpaceDoc can re-examine it.
7. **Versioned and documented.** Each mini ships with a model card: training data, intended use, known failure modes, validation metrics.

## 2. The generic mini contract

Every mini, whatever the device, publishes messages in this shape (JSON over MQTT, topic `spacedoc/minis/<device_id>/report`):

```json
{
  "schema_version": "0.1",
  "report_id": "uuid",
  "device": {"id": "ecg-01", "type": "ecg_12lead", "firmware": "2.3.1"},
  "mini": {"name": "ecg-rhythm", "version": "0.4.0", "model_hash": "sha256:…"},
  "subject": {"crew_id": "C3"},
  "acquired_at": "2026-09-26T14:03:11Z",
  "environment": {"gravity_g": 0.0, "posture": "restrained_supine"},
  "raw_ref": "blob://ecg/2026-09-26/C3/0003.wfdb",
  "quality": {"sqi": 0.87, "status": "adequate", "issues": []},
  "ood": {"score": 0.12, "flag": false},
  "measurements": [
    {"name": "heart_rate", "value": 112, "unit": "bpm", "method": "deterministic"},
    {"name": "qtc_fridericia", "value": 438, "unit": "ms", "method": "deterministic"}
  ],
  "findings": [
    {"code": "AF_PATTERN", "label": "Atrial fibrillation pattern",
     "probability": 0.93, "calibrated": true, "evidence_window": [0, 10.0]}
  ],
  "urgency_hint": "advisory",
  "latency_ms": 42
}
```

SpaceDoc can also **request** a measurement (`spacedoc/minis/<device_id>/request`). For example: "record a 12-lead ECG on C3 now". The request includes guidance text rendered for whoever is operating the device.

**Code systems.** Finding codes map to standard terminologies where possible (e.g. SNOMED CT, LOINC for measurements, SCP-ECG statements for ECG). This keeps records interoperable (NFR-08).

## 3. Deployment tiers

| Tier | Where it runs | Typical model | Runtime |
|---|---|---|---|
| **On-device** | Microcontroller inside the sensor | Tiny 1D-CNN, int8, < 1 MB | TensorFlow Lite Micro / TinyML |
| **Device hub** | Small SBC or phone next to the device | Small CNN/Transformer, tens of MB | ONNX Runtime, LiteRT (TFLite), Core ML |
| **Host** | On the SpaceDoc computer | Larger models (e.g. ultrasound segmentation) | ONNX Runtime / PyTorch / MLX |

Prototype on the host tier. The contract is identical at every tier, so a mini can be moved closer to the device later without changing SpaceDoc.

## 4. Candidate minis

| Mini | Device | Example findings | Open data to start with | Notes |
|---|---|---|---|---|
| **ECG rhythm/morphology** | 12-lead or 3-lead ECG (e.g. Bio-Monitor/Astroskin-style wearables have a 3-lead ECG) | Arrhythmias, conduction blocks, ischemia patterns, QTc | PTB-XL (21,799 12-lead records, CC BY 4.0), MIT-BIH Arrhythmia, PhysioNet/CinC Challenges (2017 AF, 2020/21 12-lead) | Best-studied. A 1D-CNN reached cardiologist-level rhythm classification in published work |
| **PPG / SpO2 / vitals** | Pulse oximeter, wearable | SpO2 trend, pulse rate, perfusion index, artifact detection, respiratory rate from PPG | BIDMC PPG & Respiration, MIMIC waveform subsets (credentialed) | Feeds long-term trend monitoring directly |
| **Ultrasound assist** | Handheld POCUS | View-quality guidance ("tilt probe toward head"), free-fluid detection, lung sliding / B-lines, hydronephrosis | Limited public data. Needs partnerships or collection | Very high value in space (the ISS primary imaging modality). Guidance helps non-expert operators |
| **Fundus / OCT** | Retinal camera / OCT | Optic disc edema grading, choroidal folds (SANS) | Public OCT sets (e.g. Kermany et al.); SANS-specific data would need NASA collaboration | Directly targets a top-priority spaceflight risk |
| **Heart & lung sounds** | Digital stethoscope | Murmurs, wheezes, crackles | PhysioNet/CinC 2016 heart sounds, ICBHI 2017 respiratory sounds | Cheap sensor, good for crew self-checks |
| **Skin / wound imaging** | Camera | Rash triage, wound healing tracking, burns | ISIC archive (mixed licenses) | Dermatitis is common in flight |
| **Spirometry** | Spirometer | Obstructive/restrictive patterns, trend | NHANES spirometry | Relevant for lunar/Mars dust exposure monitoring |

**License check required** for every dataset before training. Licenses vary (CC BY, ODC-By, non-commercial, credentialed-access DUAs).

**Microgravity shift.** Terrestrial data doesn't capture space physiology: fluid shift, cardiac shape changes, altered posture. Expect **domain shift**. Mitigations:
- OOD flags
- per-crew preflight baseline recordings
- fine-tuning on analog and flight data when available (e.g. through NASA or other collaborations)

## 5. Validation for each mini

| Check | Metric |
|---|---|
| Discrimination | AUROC, sensitivity/specificity at the operating point, per-class F1 |
| Calibration | Reliability diagram, expected calibration error (ECE) |
| Quality gating | % of bad-signal inputs correctly flagged; performance on accepted-only inputs |
| OOD | Detection rate on held-out device and noise conditions |
| Robustness | Noise, electrode misplacement, motion artifact simulations |
| Latency and footprint | ms per inference, memory, power on the target tier |
| Subgroups | Performance across sex, age and body habitus (small crews mean individual variation matters) |

---

## How this works in AI systems: a CNN is a learned filter bank

If you've designed FIR filters, you already understand the core of a 1D convolutional neural network (CNN).

- A **convolution layer** slides many short kernels (filters) along the signal, exactly like FIR filtering. The difference is that the filter coefficients are **learned from labeled examples**, not designed by hand. Early layers learn edge and slope detectors (QRS onsets). Deeper layers combine them into shapes (a whole QRS complex, a P wave, irregular spacing).
- **Nonlinearities** (e.g. ReLU) and **pooling** (downsampling) between layers let the network build a hierarchy: sample → wave → beat → rhythm.
- A final **classifier** layer turns the features into probabilities.
- **Training** adjusts all the coefficients by gradient descent to minimize prediction error on labeled data. PTB-XL, for example, has cardiologist-labeled ECGs.

**Calibration.** Networks are often overconfident. Temperature scaling divides the network's raw output scores (logits) by a constant fitted on validation data. It is a one-parameter gain adjustment that makes 0.9 actually mean 90%.

**Out-of-distribution detection.** A network only knows the world it was trained on. OOD detectors measure how "unfamiliar" an input is, for example by its distance from training examples in feature space. It is a sanity check, like asking whether a sensor reading is even within the sensor's calibrated range.
