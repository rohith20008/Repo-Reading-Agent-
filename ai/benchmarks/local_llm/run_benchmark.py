#!/usr/bin/env python
"""Repeatable, local-only Ollama benchmark for the synthetic CODEMIND evaluation set."""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.ai.agents import PROMPTS  # noqa: E402
from app.ai.docs import SUMMARY_SYSTEM  # noqa: E402
from app.ai.investigator import SYSTEM_PROMPT as BUG_SYSTEM  # noqa: E402

DEFAULT_MODELS = ["qwen2.5-coder:3b", "qwen2.5:7b"]
TASK_SYSTEMS = {
    **PROMPTS,
    "bug-investigator": BUG_SYSTEM,
    "documentation": SUMMARY_SYSTEM,
}
PATH_PATTERN = re.compile(
    r"(?<![\w/\\])(?:[\w.-]+[/\\])*[\w.-]+\."
    r"(?:py|pyi|js|jsx|ts|tsx|java|md|json|yaml|yml|toml)(?::\d+(?:-\d+)?)?"
    r"(?![\w/\\])",
    re.IGNORECASE,
)


def api_json(endpoint: str, payload: dict | None = None, timeout: int = 20) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Local Ollama request failed: {exc}") from exc


def gpu_sample() -> dict:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        values = [int(part.strip()) for part in result.stdout.splitlines()[0].split(",")]
        return {"gpu_utilization_pct": values[0], "gpu_memory_used_mib": values[1], "gpu_memory_total_mib": values[2]}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {}


def ollama_process_rss_mib() -> int:
    total = 0
    for process in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (process.info["name"] or "").lower()
            if "ollama" in name:
                total += process.info["memory_info"].rss
        except (psutil.Error, TypeError):
            continue
    return round(total / (1024 * 1024))


class Telemetry:
    def __init__(self) -> None:
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            vm = psutil.virtual_memory()
            self.samples.append(
                {
                    "timestamp": time.time(),
                    "host_cpu_pct": psutil.cpu_percent(interval=None),
                    "host_memory_used_mib": round(vm.used / (1024 * 1024)),
                    "ollama_process_rss_mib": ollama_process_rss_mib(),
                    **gpu_sample(),
                }
            )
            self._stop.wait(0.5)

    def __enter__(self) -> "Telemetry":
        psutil.cpu_percent(interval=None)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def summary(self) -> dict:
        result = {}
        for key in ("host_cpu_pct", "host_memory_used_mib", "ollama_process_rss_mib", "gpu_utilization_pct", "gpu_memory_used_mib"):
            values = [sample[key] for sample in self.samples if key in sample]
            if values:
                result[f"{key}_max"] = max(values)
                result[f"{key}_mean"] = round(statistics.fmean(values), 2)
        result["sample_count"] = len(self.samples)
        return result


def stream_chat(
    endpoint: str,
    model: str,
    system: str,
    question: str,
    context: str,
    num_ctx: int,
    num_predict: int,
) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
        ],
        "stream": True,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "seed": 41,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at = None
    chunks = []
    final = {}
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw in response:
            if not raw.strip():
                continue
            item = json.loads(raw.decode("utf-8"))
            content = (item.get("message") or {}).get("content", "")
            if content:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                chunks.append(content)
            if item.get("done"):
                final = item
    finished = time.perf_counter()
    output = "".join(chunks).strip()
    eval_count = final.get("eval_count")
    eval_duration = final.get("eval_duration")
    return {
        "output": output,
        "wall_seconds": round(finished - started, 4),
        "ttft_seconds": round(first_token_at - started, 4) if first_token_at else None,
        "ollama_total_duration_seconds": _ns_to_seconds(final.get("total_duration")),
        "prompt_tokens": final.get("prompt_eval_count"),
        "prompt_eval_seconds": _ns_to_seconds(final.get("prompt_eval_duration")),
        "generated_tokens": eval_count,
        "generation_seconds": _ns_to_seconds(eval_duration),
        "tokens_per_second": round(eval_count / (eval_duration / 1e9), 3) if eval_count and eval_duration else None,
        "done_reason": final.get("done_reason"),
    }


def _ns_to_seconds(value: int | None) -> float | None:
    return round(value / 1e9, 4) if isinstance(value, (int, float)) else None


def checks(case: dict, output: str, known_paths: set[str]) -> dict:
    lowered = output.casefold()
    terms = case["required_terms"]
    term_hits = [
        group for group in terms
        if any(alternative.casefold() in lowered for alternative in (group if isinstance(group, list) else [group]))
    ]
    paths = [match.group(0) for match in PATH_PATTERN.finditer(output)]
    normalized = [path.replace("\\", "/").split(":")[0].lstrip("./") for path in paths]
    found_paths = sorted(set(path for path in normalized if path in known_paths))
    expected = case["expected_paths"]
    forbidden = sorted(set(path for path in normalized if path in case.get("forbidden_paths", [])))
    unknown_paths = sorted(set(path for path in normalized if path not in known_paths and path not in forbidden))
    cited_ids = {
        citation.strip("[]\"")
        for citation in re.findall(r"\[E\d+\]|\"E\d+\"", output)
    }
    cited_paths = {
        item["path"] for item in case["evidence"]
        if item["id"] in cited_ids
    }
    identified_paths = set(found_paths) | cited_paths
    return {
        "required_term_coverage": round(len(term_hits) / len(terms), 3) if terms else 1.0,
        "required_terms_found": term_hits,
        "required_terms_missing": [term for term in terms if term not in term_hits],
        "expected_path_coverage": round(len(set(expected) & identified_paths) / len(set(expected)), 3) if expected else 1.0,
        "expected_paths_found": sorted(set(expected) & identified_paths),
        "unknown_path_mentions": unknown_paths,
        "forbidden_path_mentions": forbidden,
        "has_evidence_id_citation": bool(cited_ids),
        "unsupported_path_proxy_count": len(unknown_paths) + len(forbidden),
    }


def build_baseline_systems() -> dict[str, str]:
    systems = {}
    for agent, prompt in TASK_SYSTEMS.items():
        if agent == "documentation":
            # The production docs model receives deterministic fact Markdown between markers.
            systems[agent] = prompt + " Cite supplied evidence IDs when present. Do not create additional facts."
        else:
            systems[agent] = prompt
    return systems


def unload_model(endpoint: str, model: str) -> None:
    try:
        api_json(f"{endpoint.rstrip('/')}/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=30)
    except RuntimeError as exc:
        print(f"Warning: could not request Ollama unload for {model}: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--endpoint", default="http://localhost:11435")
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--num-predict", type=int, default=160)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    tags = api_json(f"{args.endpoint.rstrip('/')}/api/tags")
    installed = {item["name"]: item for item in tags.get("models", [])}
    missing = [model for model in args.models if model not in installed]
    if missing:
        parser.error(f"Model(s) are not installed; refusing to download: {', '.join(missing)}")
    cases = [json.loads(line) for line in (ROOT / "evaluation_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    optimized = json.loads((ROOT / "prompts_optimized.json").read_text(encoding="utf-8"))
    baseline = build_baseline_systems()
    known_paths = {
        item.relative_to(ROOT / "fixtures" / "sample_repo").as_posix()
        for item in (ROOT / "fixtures" / "sample_repo").rglob("*")
        if item.is_file()
    }
    endpoint = args.endpoint.rstrip("/")
    records = []
    started_at = datetime.now(timezone.utc).isoformat()
    for model in args.models:
        model_meta = installed[model]
        print(f"Model {model} ({model_meta.get('size', 0) / 1e9:.2f} GB): running baseline and optimized prompts", flush=True)
        for case in cases:
            context = "\n\n".join(
                f"[{ev['id']}] {ev['path']}:{ev['startLine']}-{ev['endLine']}"
                + (f" ({ev['symbol']})" if ev.get("symbol") else "")
                + f"\n```\n{ev['snippet']}\n```"
                for ev in case["evidence"]
            )
            for repeat in range(1, args.repeats + 1):
                for version, prompts in (("production", baseline), ("structured", optimized)):
                    record = {
                        "case_id": case["id"],
                        "agent": case["agent"],
                        "model": model,
                        "model_digest": model_meta.get("digest"),
                        "prompt_version": version,
                        "repeat": repeat,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    try:
                        with Telemetry() as telemetry:
                            result = stream_chat(
                                endpoint,
                                model,
                                prompts[case["agent"]],
                                case["question"],
                                context,
                                args.num_ctx,
                                args.num_predict,
                            )
                        record.update(result)
                        record["telemetry"] = telemetry.summary()
                        record["checks"] = checks(case, result["output"], known_paths)
                    except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                        record["error"] = str(exc)
                        record["telemetry"] = {}
                    records.append(record)
                    print(
                        f"  {case['id']} {version} #{repeat}: "
                        + (f"{record.get('wall_seconds')}s" if "wall_seconds" in record else f"ERROR {record['error']}"),
                        flush=True,
                    )
        unload_model(endpoint, model)
        time.sleep(2)
    result_path = args.output or ROOT / "results" / f"benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "endpoint": endpoint,
                "settings": {
                    "temperature": 0,
                    "seed": 41,
                    "num_ctx": args.num_ctx,
                    "num_predict": args.num_predict,
                    "repeats": args.repeats,
                    "sequential_models": True,
                },
                "models": [
                    {"name": name, "digest": installed[name].get("digest"), "size_bytes": installed[name].get("size")}
                    for name in args.models
                ],
                "cases": len(cases),
                "records": records,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(records)} runs to {result_path}")
    return 0 if all("error" not in record for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
