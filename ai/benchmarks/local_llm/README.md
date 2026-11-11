# Local LLM evaluation and adaptation feasibility

This directory is intentionally isolated from user repositories and the production database. Its fixture is synthetic. No training has been run and evaluation cases are not training examples.

## Reproducible benchmark

From `backend/` with the project virtual environment active:

```powershell
python -m pip install -r ..\benchmarks\local_llm\requirements.txt
python ..\benchmarks\local_llm\run_benchmark.py --repeats 2
```

By default the harness compares the production prompts with the structured prompts in `prompts_optimized.json` for both installed models. It runs one model at a time, streams each response, and saves raw outputs and per-run measurements under `results/`. It uses a 4096-token context, 160 generated-token limit, temperature 0, and a 5-minute request timeout; these are benchmark overrides and do not change app settings. `--models` can select an installed model and `--repeats` controls repetition count. Use only a few repetitions on the 7B model initially because it is larger than the laptop's VRAM.

The evaluator reports response wall time, first-content-token latency, Ollama prompt/evaluation token and duration counters where returned, generated tokens/second, host CPU and RAM samples, Ollama process working set, and `nvidia-smi` GPU utilization/VRAM samples. The first run for a model/prompt may include model loading; compare cold and warm runs separately. Automated correctness is a transparent proxy: expected-term coverage, expected file-path coverage, forbidden/unknown path mentions, and evidence-ID citation presence. It cannot establish semantic correctness or all unsupported claims; inspect `outputs` and manually grade those before selecting a model.

## Data separation

- `evaluation_cases.jsonl` and `fixtures/sample_repo/` are deterministic held-out test data and must never be copied into fine-tuning training splits.
- `training/proposed_train.jsonl` is a proposed synthetic training format only. It has evidence-bearing chat examples and source metadata, but it has not been quality-reviewed as a production dataset and no model was trained on it.
- Keep any future user-derived examples out of these fixtures unless explicit permission, anonymization, licensing review, and secret scanning have been completed.

Each evaluation case has an ID, agent, question, evidence snippets with source paths/line ranges and symbols, expected concepts, expected and forbidden paths, and an expected agent. Results record prompt version, model digest if available, settings, timestamp, raw output, telemetry and automatic checks.

## Current architecture audit

The six specialists are declared in `backend/app/ai/agents.py`. `backend/app/ai/supervisor.py` classifies/routs requests and coordinates selected agents with LangGraph. There is one configured generative model (`CODEMIND_AI_MODEL`) shared by all specialists and supervisor consolidation; no per-agent model selection exists. The configured local provider is `OllamaProvider` in `backend/app/ai/providers.py`, which calls `/api/chat` and streams when used by chat. Bug investigations use that same model with a JSON-output prompt in `backend/app/ai/investigator.py`. Documentation content is first assembled deterministically in `backend/app/ai/docs.py`; the model is optional for a short grounded summary. Evidence comes from lexical SQLite/source retrieval in `backend/app/ai/retrieval.py`. `nomic-embed-text:latest` is used for optional semantic reranking, with lexical fallback; there is no persistent vector index. The frontend chat uses Ollama through the backend SSE endpoint, not direct model access.

Production inference settings currently include endpoint, timeout, max output tokens, temperature, and evidence character budget. Ollama `/api/chat` supplies `num_predict` and temperature; context length, keep-alive, parallelism and per-agent settings are not presently surfaced in application configuration. The benchmark pins `num_ctx` itself to compare on this 4 GB device.

## Hardware and fine-tuning feasibility

Measured host inventory: Windows, NVIDIA RTX 3050 Laptop GPU with 4096 MiB reported VRAM, Ryzen 7 4800H (8 cores/16 logical processors), and 16 GiB RAM. Installed GGUFs are Qwen2.5-Coder 3B, Q4_K_M (~1.93 GB file), Qwen2.5 7B, Q4_K_M (~4.68 GB), and Nomic Embed Text F16 (~274 MB). At idle `nvidia-smi` reported 0 MiB GPU use. These are measurements; available VRAM under a desktop workload will be lower.

The 3B Q4 model is the appropriate first inference candidate. The 7B Q4 artifact exceeds physical VRAM by itself and must be partially CPU/RAM offloaded; do not keep both generators loaded concurrently. Nomic embedding should be called only as needed and its memory behavior measured. No benchmark should run alongside a user workload; close GPU-heavy applications and run models sequentially. The harness stores measured warm/cold timing and sampled host/GPU telemetry.

Fine-tuning is not recommended on this machine as configured. The backend virtual environment has no PyTorch installed, and CUDA training is not set up. A 3B 4-bit QLoRA run may be technically possible only with a tightly constrained sequence length, micro-batch 1, gradient checkpointing and memory-efficient optimizer in a compatible CUDA/Linux environment; 4 GB VRAM is below a dependable budget once activations and runtime overhead are included. 7B LoRA/QLoRA is not practical on 4 GB. Full fine-tuning is out of scope. Windows-native CUDA support varies by library; WSL2/Linux is the safer path for PEFT/Transformers, and Unsloth should be treated as Linux/WSL-dependent unless its current Windows support is verified for the exact release. Sixteen GB system RAM is marginal for a training stack plus model/cache and WSL. If training becomes justified, first use a small, deduplicated, reviewed dataset and a short adapter experiment on rented GPU compute (or a better local GPU), then evaluate on the held-out JSONL. Ollama can import a compatible GGUF or adapter in supported formats, but conversion/base-model and adapter compatibility must be verified; the training format itself is not deployable.

## Recommendations (not yet production changes)

1. Keep `qwen2.5-coder:3b` as the production default unless repeated held-out measurements show a material 7B quality gain that justifies CPU offload latency.
2. Keep one generator loaded at a time. Benchmark cold and warm latency separately, pin a moderate context, and cap generated tokens by task. Only expose Ollama `keep_alive`/`num_ctx`/concurrency settings in production after the benchmark confirms reliable memory behavior.
3. Keep deterministic lexical retrieval and evidence validation as the foundation. The small Nomic model is optional reranking, not a substitute for source evidence.
4. Optimize prompts before training: require evidence IDs and explicit unknowns, minimize irrelevant context, and evaluate unsupported paths. Adopt a prompt only if its repeated scores and manual review improve without losing completeness.
5. Consider per-agent models only after measured task-specific gains and resource validation; the current single shared model is simpler and safer for 4 GB VRAM.

## External feasibility references

- Hugging Face PEFT quantization guide: https://huggingface.co/docs/peft/developer_guides/quantization
- Unsloth Windows installation guidance: https://unsloth.ai/docs/get-started/install/windows-installation.md
- Ollama importing GGUF and Safetensors models: https://docs.ollama.com/import
