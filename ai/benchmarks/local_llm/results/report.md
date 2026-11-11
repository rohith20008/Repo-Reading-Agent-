# CODEMIND local model benchmark report

**Run:** 2026-11-01, on this Windows laptop  
**Raw results:** `benchmark-20261101-200318.json`  
**Dataset:** 8 synthetic evaluation cases, 2 repetitions per model and prompt (64 runs total)  
**Models:** existing local Ollama models only; no downloads  
**No production application setting or model was changed.**

## Setup and methodology

Ran both models serially, unloading each before the next. Each evaluation case was requested with the current production system prompt and with its structured alternative, at temperature 0, seed 41, `num_ctx=4096`, `num_predict=128`. The two repetitions are useful for repeatability but are too few for strong statistical claims. For each request, the harness measured wall latency, first content-token latency, Ollama prompt/generation counters, streamed generation rate, host CPU/RAM, Ollama-named process RSS, and `nvidia-smi` GPU utilization/VRAM.

Automatic quality checks are proxies, not a semantic benchmark: expected concept-group coverage, expected file coverage (literal file mention or a citation to evidence from that file), evidence-ID citation rate, and unknown/forbidden path mentions. These checks do not prove that a factual claim is supported. A person should review the raw answers before making a model or prompt-selection decision. Documentation uses the production documentation summary system prompt as the baseline; its normal application input is deterministically prepared facts, so the synthetic evidence question is an approximation of the live documentation route.

## Aggregate measurements

Each condition below contains 16 responses: 8 cases × 2 repetitions.

| Model / prompt | Mean wall time | Mean time to first token | Mean generated tok/s | Expected concepts covered | Expected file coverage | Responses citing evidence IDs | Unknown file path mentions |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen2.5-coder:3b`, production | 4.27 s | 2.71 s | 63.19 | 63.5% | 44.8% | 31.3% | 0 |
| `qwen2.5-coder:3b`, structured | 4.28 s | 2.46 s | 62.78 | 68.2% | 47.9% | 25.0% | 0 |
| `qwen2.5:7b`, production | 16.20 s | 3.43 s | 8.58 | 84.4% | 53.1% | 56.3% | 6 |
| `qwen2.5:7b`, structured | 17.38 s | 2.81 s | 8.56 | 84.9% | 55.2% | 62.5% | 4 |

Structured prompts were not a uniform win. On 3B, mean concept coverage improved by 4.7 percentage points and file coverage by 3.1 points, but the citation rate fell by 6.3 points. On 7B, concept coverage increased by 0.5 points, file coverage by 2.1 points, citation rate by 6.2 points, and unknown path mentions fell from six to four; mean latency rose by 1.18 s. These modest results support further task-specific prompt work, not replacing all production prompts wholesale.

## Hardware measurements

- Host inventory: RTX 3050 Laptop GPU, 4096 MiB VRAM; Ryzen 7 4800H, 8 cores / 16 threads; 16 GiB physical RAM; Windows.
- Installed artifacts reported by Ollama: `qwen2.5-coder:3b` Q4_K_M, 1,929,912,626 bytes; `qwen2.5:7b` Q4_K_M, 4,683,087,332 bytes; `nomic-embed-text:latest` F16, 274,302,450 bytes.
- During the benchmark, peak sampled VRAM was 2,157 MiB for 3B and 2,299 MiB for 7B; peak GPU utilization reached 99-100% and 97%, respectively. Peak host CPU reached 72% for 3B and 98% for 7B. Peak host RAM used was 13,174 MiB for 3B and 15,114 MiB for 7B.
- A separate live Ollama residency check reported the 7B runner at 5.0 GB total size, split **55% CPU / 45% GPU** with a 2,048-token context; `nvidia-smi` showed 2,239 MiB VRAM in use. The model was unloaded after the check. The benchmark models were run sequentially, not concurrently.
- The recorded Ollama process RSS is only the working set of processes whose names contain “ollama”; it is not a reliable measurement of the separate inference runner's total RAM. Use the Ollama residency split and system RAM peak for memory interpretation. After the final run, all models were unloaded, GPU use returned to 0 MiB, and Windows reported 4,587 MiB free RAM.

The 7B model is larger than physical VRAM and was demonstrably CPU/GPU split. It used almost all available host RAM during this run. Its average generation rate was about 7× slower than 3B. Do not keep both generation models resident or run the 7B benchmark alongside other memory-heavy applications.

## Per-agent model and prompt recommendations

These are recommendations for subsequent evaluation, not automatic production routing. All six current agents and supervisor consolidation use the single configured `CODEMIND_AI_MODEL`; per-agent model configuration does not exist.

| Agent | Candidate for a quality-first experiment | Evidence / trade-off |
|---|---|---|
| Repository Understanding | 7B + structured prompt | The repeated synthetic case achieved 1.00 concept coverage, 0.75 expected-file coverage and citations in both responses. Production prompt scored 0.88, 0.25 and 0.50 respectively. One question repeated twice; validate on broader repositories. |
| Code Analysis | 7B + production prompt for multi-file flow; 3B + structured prompt for a quick simple explanation | Across two cases, 7B production achieved 0.69 concept coverage / 0.62 path coverage / 0.75 citation rate; 3B structured achieved 0.81 / 0.50 / 0.00. The 3B simple explanation was correct but uncited; the 7B multi-file-flow answer was stronger. |
| Bug Investigation | 7B + structured prompt, with human review | Across the arithmetic bug and null-root-cause cases, structured 7B achieved 0.83 concept coverage, full expected-file coverage and citations in both responses. 3B production also cited both sources, but one proposed arithmetic correction was itself wrong. |
| Dependency Intelligence | 7B + production prompt pending more cases | Both models covered all expected dependency concepts. The 7B production prompt cited evidence in both runs and had 0.50 expected-file coverage; 3B was much faster but did not cite evidence IDs in this case. |
| Documentation | 7B + production prompt for quality-first generation | In this one synthetic task it covered all expected concepts/files; the structured alternative reduced concept/path coverage. The deterministic documentation builder should remain authoritative; model summaries need evidence validation. |
| Code Recommendation | No model is ready for autonomous or trusted recommendation output | Both 7B prompts had full concept coverage but zero expected path coverage and zero citations. 3B production was faster but also weakly grounded. Keep suggestions review-only and improve the dataset/prompt before selecting a model. |

With current evidence and hardware, keep `qwen2.5-coder:3b` as the application default for interactive responsiveness and avoid loading the 7B model by default. Consider a deliberate, user-selected quality mode only after a larger evaluation confirms its gains and confirms acceptable RAM/latency. Do not add per-agent switching yet.

## Prompt evaluation

The structured alternatives are stored in `prompts_optimized.json`. They explicitly require evidence-ID citations, limit claims to supplied evidence, distinguish hypotheses, and say when evidence is insufficient. No production prompt was changed: the aggregate scores do not justify a global replacement. Next prompt iteration should target failures visible in raw outputs: 3B omitted evidence IDs, 3B repository understanding invented entry points, and the 7B production prompt occasionally named unsupported file paths. Add more paraphrases and adversarial “not enough evidence” cases before considering prompt adoption.

## Fine-tuning feasibility

No training job was started and no training packages or model weights were installed. `torch` is not present in the backend virtual environment. The available Ollama GGUFs are inference artifacts, not directly trainable Transformers checkpoints.

- **LoRA without quantized base:** not feasible on this 4 GB GPU; a 3B FP16 base alone is roughly 6 GB of weights, before activations, adapters, gradients, optimizer states and CUDA/runtime memory. Full fine-tuning is further out of scope.
- **QLoRA / PEFT:** the only plausible first experiment would be a tiny 3B adapter with micro-batch 1, short sequence length, gradient checkpointing and memory-efficient optimizer. This is still not a dependable fit on 4 GB VRAM; use a larger GPU (practical starting point likely 8-12 GB for 3B, estimate only) or cloud GPU. 7B is not practical here. Exact memory depends heavily on sequence length, target modules, optimizer and library.
- **Transformers / PEFT:** viable framework choices in a configured CUDA Linux environment, but the project's Windows backend environment lacks PyTorch and has no training stack. WSL2 with a verified NVIDIA CUDA passthrough is a possible development setup; a rented GPU is less risky for an initial experiment.
- **Unsloth:** current docs describe Windows Desktop/Studio and Windows Core via Conda, Docker or WSL. Its presence does not change the 4 GB VRAM limit; verify the exact supported model/CUDA/library combination before installation.
- **GGUF/Ollama:** Ollama documents importing GGUF and Safetensors model directories. A trained PEFT adapter must be compatible with the exact base and deployment format; merge/convert and test it separately before Ollama import. The proposed JSONL is not a model or adapter.

These are feasibility estimates, not measured training requirements. The held-out evaluation cases must stay out of any future fine-tuning split.
