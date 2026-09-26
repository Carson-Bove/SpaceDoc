# 02 — Running SpaceDoc Locally

**Goal (NFR-01):** SpaceDoc runs fully offline on the reference laptop (MacBook Air M4, 16 GB unified memory), with a path to flight-like edge hardware. NASA's CMO-DA made the same move from a cloud prototype to fully offline edge deployment, so this is the right constraint to design around from day one.

## 1. The hardware we have

| Machine | Key numbers | Best role |
|---|---|---|
| **MacBook Air M4, 16 GB** | Unified memory, shared by CPU and GPU; ~120 GB/s memory bandwidth; fanless, so it throttles under long sustained load | **Runs SpaceDoc** (reference target) |
| **Desktop, 32 GB DDR4 + 8 GB VRAM GPU** | Fast GPU for models ≤ ~7 GB; large but slow CPU RAM | **Eval and training rig**: train minis, run large batches of evaluation overnight, run bigger "judge" models slowly |

## 2. Memory math (how to know what fits)

A model's memory footprint is roughly:

```
weights  ≈ parameters × bits_per_weight / 8
KV cache ≈ 2 × layers × kv_heads × head_dim × bytes_per_value × context_tokens
total    ≈ weights + KV cache + runtime overhead (~0.5–1 GB)
```

**Worked example (Llama-3-8B-like model: 32 layers, 8 KV heads, head_dim 128):**
- Weights at 4-bit (~4.5–4.9 effective bits including scales): 8e9 × 4.7 / 8 ≈ **4.7 GB**
- KV cache per token at FP16: 2 × 32 × 8 × 128 × 2 bytes = 131 kB, so an **8k-token context ≈ 1 GB** and 32k ≈ 4 GB

**The 16 GB Mac budget.** macOS and apps need ~4–5 GB, and by default macOS only lets the GPU use part of unified memory. Plan for about **9–10 GB for all models together**:

| Component | Candidate | Approx. memory |
|---|---|---|
| Orchestrator LLM | ~8–9B dense, 4-bit | ~5 GB |
| KV cache | 8k context | ~1 GB |
| Embedding model | ~0.6B (e.g. Qwen3-Embedding-0.6B), 8-bit | ~0.6 GB |
| Reranker | ~0.6B, 8-bit | ~0.6 GB |
| Grounding verifier | MiniCheck-FT5 (0.77B) | ~0.8–1.5 GB |
| **Total** | | **~8–9 GB**, workable |
| Multimodal specialist (on demand) | MedGemma 1.5 4B, 4-bit | ~2.5–3 GB, swapped in when an image is involved |

A 12–14B orchestrator at 4-bit (~7–8.5 GB) fits on its own but leaves no room for the verifier stack. On this machine, **one 8B model plus small specialist models beats one bigger model with no verification.**

**Speed.** Generating each new token requires reading every weight from memory once. Decode speed is therefore bounded by `memory bandwidth ÷ model size` ≈ 120 GB/s ÷ 5 GB ≈ **~24 tokens/s upper bound** on the M4. Expect roughly 15–25 tokens/s in practice, and less when thermally throttled. Reading the prompt ("prefill") is compute-bound and much faster per token. Measure both in Phase 1.

**The desktop.** An 8B 4-bit model fits entirely in 8 GB VRAM, which is fast (GPU bandwidth is typically 250–450 GB/s). A 27–32B model at 4-bit (~16–19 GB) must run mostly on CPU RAM. DDR4 dual-channel gives ~40–50 GB/s, so that is only a few tokens/s. That is too slow for chat but fine for **overnight batch evaluation** with a stronger judge model.

## 3. Runtimes

| Runtime | What it is | Notes |
|---|---|---|
| **MLX / mlx-lm** | Apple's array framework for Apple Silicon | Usually the fastest option on Mac |
| **llama.cpp** | C++ inference engine using GGUF model files | Same model files run on Mac *and* PC; grammar/JSON-schema-constrained decoding; OpenAI-compatible server |
| **Ollama** | Friendly wrapper and model manager | Since v0.19 (Mar 2026) it uses an MLX backend on Macs with ≥ 32 GB; **16 GB Macs still use the llama.cpp path** |
| **LM Studio** | Desktop GUI (MLX + llama.cpp) | Good for quick model comparisons by hand |
| **RamaLama** | Red Hat project that runs models as OCI containers | Used for NASA's offline CMO-DA tests; closest to a flight-like deployment |

**Recommendation.** Put every model behind an **OpenAI-compatible local HTTP API**, so SpaceDoc code never depends on a specific runtime. Start with **llama.cpp** (identical GGUF files on both machines, mature constrained decoding). Benchmark **MLX** on the Mac as the optimization path. Revisit **RamaLama** containers for the analog-deployment phase.

## 4. Candidate models (as of Sept 2026; re-check at Phase 1)

| Model | Size(s) | License | Why consider |
|---|---|---|---|
| **Qwen3 / Qwen3.5 family** | dense 0.6B–32B (e.g. 8B, 9B) | Apache 2.0 | Strong tool calling and instruction following at small sizes |
| **Gemma 4** | E2B, E4B, 12B, 26B-A4B (MoE), 31B | Apache 2.0 (Apr 2026) | Multimodal, long context; E4B/12B fit the laptop |
| **MedGemma 1.5** | 4B multimodal (Jan 2026); MedGemma 1 at 4B / 27B | Health AI Developer Foundations terms | Medical-tuned text and imaging; a developer building block, not a clinical product |
| **Phi-4** | 14B | MIT | Strong reasoning for size; tight on 16 GB |
| **Llama 3.x** | 8B | Llama community license | Widely supported baseline |
| **Qwen3-Embedding / Reranker** | 0.6B, 4B, 8B | Apache 2.0 | Top-tier open retrieval models; the 0.6B fits easily |
| **MiniCheck** | 0.77B (Flan-T5); 7B (Bespoke) | see model cards | Purpose-built "is this sentence supported by this document?" checker |

**Do not pick a model because it has "Med" in its name.** The MedHallu benchmark found that when relevant knowledge is supplied (which is exactly what RAG does), general-purpose LLMs can outperform medically fine-tuned ones at spotting hallucinations. SpaceDoc selects models **empirically**. Shortlist 3–4 and score them on the Phase 1 harness ([08](08-validation-framework.md)) on:
1. tool-call and JSON-schema reliability
2. faithfulness to retrieved sources
3. abstention when sources are missing
4. latency on the M4

## 5. Toward flight hardware

- **Existing precedent:** HPE's Spaceborne Computer-2 on the ISS includes an NVIDIA T4 GPU node. CMO-DA is being tested on its ground twin.
- **Edge modules:** Jetson-class boards are the likely analog-mission target. Every model choice above is sized so it can transfer.
- **Radiation:** outside LEO, single-event upsets (bit flips) can silently corrupt weights in memory. Mitigations:
  - ECC memory
  - periodic hashing of loaded model weights against a known checksum
  - redundant execution for critical deterministic code (protocols, calculators)
  - keeping the LLM out of the emergency critical path (SR-10)
- **Power and thermal:** a "low-power mode" (NFR-06) swaps to a ~2–4B orchestrator. Monitoring and protocols keep running without the LLM.

---

## How this works in AI systems: what a "parameter" is, and quantization

An LLM is a very large stack of matrix multiplications. The **parameters (weights)** are the numbers in those matrices, learned during training. "8B" means 8 billion of them. The model reads text as **tokens** (word pieces, roughly ¾ of a word each) and repeatedly predicts the next token.

**Quantization** stores each weight with fewer bits: 16 → 8 → 4. It is like choosing ADC bit depth for a sensor. Fewer bits means less memory and faster reads but more quantization noise. Modern 4-bit schemes store small groups of weights with a shared scale factor (block floating point), which keeps quality loss surprisingly small for most tasks. Medicine is precision-sensitive, though, so **quantization level is itself something we evaluate** (4-bit vs 8-bit on the same test set), not assume.

The **KV cache** is the model's working memory for the current conversation. It stores intermediate results for every token so far, so memory grows linearly with context length. This is why "just stuff the whole medical record into the prompt" doesn't scale, and why retrieval (fetching only the relevant parts) matters.
