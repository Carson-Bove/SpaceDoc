# Glossary

## AI / ML

| Term | Meaning |
|---|---|
| **Agent** | An LLM in a loop that can call tools (functions) and act on the results |
| **AUROC** | Area under the ROC curve: how well a classifier ranks positives above negatives (0.5 = chance, 1.0 = perfect) |
| **Calibration** | Whether predicted probabilities match observed frequencies (0.9 → right 90% of the time) |
| **Chain-of-Verification (CoVe)** | The model drafts an answer, writes verification questions, answers them independently, then revises |
| **CNN** | Convolutional neural network: stacked learned filters. 1D for signals, 2D for images |
| **Conformal prediction** | A statistical wrapper that outputs prediction *sets* with a guaranteed coverage rate |
| **Constrained decoding** | Restricting generation so the output must match a grammar or JSON schema |
| **Embedding** | A vector representation of text in which similar meanings are close together |
| **Entailment / NLI** | Natural language inference: does text A logically support text B? |
| **ECE** | Expected calibration error: the average gap between confidence and accuracy |
| **Fine-tuning** | Further training a pretrained model on specific data |
| **GGUF** | The file format for quantized models used by llama.cpp and Ollama |
| **Hallucination / confabulation** | Fluent output that is not supported by facts or sources |
| **Hybrid search** | Combining keyword search (BM25) with vector (semantic) search |
| **KV cache** | Stored intermediate results for tokens already processed; grows with context length |
| **LLM** | Large language model: a transformer network trained to predict the next token |
| **LLM-as-judge** | Using an LLM to score outputs against a rubric |
| **LoRA / QLoRA** | Low-rank adaptation: training small add-on matrices instead of all weights (QLoRA does this on a quantized base) |
| **MLX** | Apple's machine-learning array framework for Apple Silicon |
| **MoE** | Mixture of experts: only some of the model's parameters are active per token |
| **OOD** | Out-of-distribution: an input unlike the training data |
| **Parameters / weights** | The learned numbers inside a model |
| **Quantization** | Storing weights at lower precision (e.g. 4-bit) to save memory and time |
| **RAG** | Retrieval-augmented generation: fetch relevant documents, then answer from them |
| **Reranker** | A model that re-scores retrieved passages for relevance |
| **Self-consistency** | Sampling several answers and checking agreement |
| **Semantic entropy** | Uncertainty measured over *meanings* of sampled answers |
| **SQI** | Signal-quality index |
| **System prompt** | Hidden instructions that steer an LLM's behavior |
| **Temperature** | A sampling randomness setting. In calibration, "temperature scaling" rescales logits |
| **Token** | A word-piece unit that LLMs read and write |

## Aerospace medicine & clinical

| Term | Meaning |
|---|---|
| **ALS / BLS** | Advanced / Basic Life Support |
| **CHeCS** | Crew Health Care System (ISS medical system) |
| **CMO** | Crew Medical Officer: the crewmember designated for medical care |
| **CMRS** | Crew Medical Restraint System: restrains the patient for treatment in microgravity |
| **Conjunction** | Mars and Earth on opposite sides of the Sun, which can black out communication |
| **DCS** | Decompression sickness |
| **ExMC** | Exploration Medical Capability (NASA HRP element) |
| **EVA** | Extravehicular activity (spacewalk or surface excursion) |
| **HRP** | NASA Human Research Program |
| **EMCL** | Exploration Medical Condition List (also SMEMCL): NASA's list of 100 medical conditions of concern for exploration missions, the basis of the IMM |
| **IMM** | Integrated Medical Model: NASA's Monte Carlo risk model of in-flight medical conditions |
| **Levels of Care** | Former NASA-STD-3001 tiers of required onboard medical capability. Replaced in Revision B (2022) by the Health and Medical Care technical requirements, which scale capability with risk assessment and mission parameters |
| **OCHMO** | NASA Office of the Chief Health & Medical Officer |
| **OSCE** | Objective Structured Clinical Examination: station-based clinical skills assessment |
| **POCUS** | Point-of-care ultrasound |
| **SANS** | Spaceflight Associated Neuro-ocular Syndrome |
| **SBAR** | Situation, Background, Assessment, Recommendation: a structured handoff format |

## Engineering & regulatory

| Term | Meaning |
|---|---|
| **CUSUM / EWMA** | Control-chart methods for detecting small persistent shifts |
| **FMEA / RPN** | Failure modes & effects analysis / risk priority number (S × L × D) |
| **GMLP** | Good Machine Learning Practice (FDA/Health Canada/MHRA principles) |
| **GSN** | Goal Structuring Notation for safety-case arguments |
| **ICC / κ** | Intraclass correlation / kappa: inter-rater agreement statistics |
| **IEC 62304** | Medical device software lifecycle standard |
| **ISO 14971** | Medical device risk management standard |
| **MQTT** | A lightweight publish/subscribe messaging protocol |
| **PCCP** | Predetermined Change Control Plan (FDA, for ML device updates) |
| **SaMD** | Software as a Medical Device |
