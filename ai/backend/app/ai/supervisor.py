"""LangGraph supervisor for evidence-grounded, selectively routed specialist workflows."""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from .agents import AGENTS, SUPERVISOR_ID
from .stacktrace import parse_frames

LEGACY_AGENT_ALIASES = {"architecture-analyst": "repository-explorer"}

_PATTERNS: dict[str, list[tuple[re.Pattern, int]]] = {
    "bug-investigator": [
        (re.compile(r"traceback|stack ?trace", re.I), 5),
        (re.compile(r"\b(bug|crash(?:es|ed|ing)?|broken|not working|doesn'?t work|fails?|failing|failed|segfault|panic)\b", re.I), 2),
        (re.compile(r"\b\w+(?:Error|Exception)\b"), 2),
        (re.compile(r"\b(error|exception|undefined|null pointer)\b", re.I), 1),
    ],
    "dependency-analyst": [
        (re.compile(r"\b(imports?|imported|dependenc\w*|packages?|librar(?:y|ies)|requirements|npm|pip|circular|third[- ]party|external)\b", re.I), 2),
        (re.compile(r"\bwho (?:uses|imports)\b|\bused by\b|\bdepends on\b", re.I), 2),
    ],
    "documentation": [
        (re.compile(r"\b(document(?:ation)?|docs|readme|api reference|changelog)\b", re.I), 3),
        (re.compile(r"\b(?:generate|write|create)\b.*\b(?:docs?|documentation|readme)\b", re.I), 3),
    ],
    "repository-explorer": [
        (re.compile(r"\b(architecture|components?|layers?|design|modules?|data flow|overall structure|fit together|"
                    r"overview|what is this|repository structure|project structure|folders?|directories|directory|"
                    r"entry points?|main files?|important files|where (?:do|should) i start|tech stack|languages?)\b", re.I), 2),
        (re.compile(r"what does this (?:repo|repository|project|app) do", re.I), 3),
        (re.compile(r"\bhow (?:\w+ ){0,4}(?:connected|related|interact\w*)\b", re.I), 2),
    ],
    "code-intelligence": [
        (re.compile(r"\b(function|class|method|symbol|defined|definition|signature|parameters?|arguments?|returns?|"
                    r"implement(?:s|ed|ation)?|where is|complexity|maintainability)\b", re.I), 2),
        (re.compile(r"\bwhat does \S+ do\b|\bhow does \S+ work\b", re.I), 2),
    ],
    "code-recommendation": [
        (re.compile(r"\b(recommend(?:ation|ations)?|suggest(?:ion|ions)?|improve(?:ment|ments)?|refactor|"
                    r"optimi[sz]e|best practice|could be better)\b", re.I), 3),
    ],
}

PRIORITY = ["bug-investigator", "documentation", "dependency-analyst", "code-recommendation",
            "repository-explorer", "code-intelligence"]
_CONNECTOR = re.compile(r"\b(and|also|plus|then|as well as)\b", re.I)


def _scores(question: str, symbol_mention: bool) -> dict[str, int]:
    scores = {agent: sum(weight for pattern, weight in patterns if pattern.search(question))
              for agent, patterns in _PATTERNS.items()}
    if len(parse_frames(question)) >= 1:
        scores["bug-investigator"] += 5
    if symbol_mention:
        scores["code-intelligence"] += 3
    return scores


def route_request(question: str, forced: str | None = None, previous_agent: str | None = None,
                  symbol_mention: bool = False) -> tuple[str, str]:
    """Return one primary agent and a human-readable route explanation."""
    forced = LEGACY_AGENT_ALIASES.get(forced, forced)
    if forced:
        if forced not in AGENTS:
            raise ValueError(f"Unknown agent '{forced}'.")
        return forced, f"You asked for the {AGENTS[forced].name}."
    scores = _scores(question, symbol_mention)
    best = max(PRIORITY, key=lambda agent: (scores[agent], -PRIORITY.index(agent)))
    if scores[best] > 0:
        reasons = {
            "bug-investigator": "The request describes an error or contains a stack trace.",
            "documentation": "The request asks for documentation.",
            "dependency-analyst": "The request is about imports or dependencies.",
            "code-recommendation": "The request asks for evidence-based improvement recommendations.",
            "repository-explorer": "The request is about repository structure or architecture.",
            "code-intelligence": "The request is about specific code" + (" (it names a symbol in the repository)." if symbol_mention else "."),
        }
        return best, reasons[best]
    if previous_agent:
        previous_agent = LEGACY_AGENT_ALIASES.get(previous_agent, previous_agent)
    if previous_agent in AGENTS and len(question.split()) <= 8:
        return previous_agent, "Short follow-up: kept the agent from the previous answer."
    return "repository-explorer", "No specific topic detected: starting with the repository overview."


class SharedState(TypedDict, total=False):
    request_id: str
    repository_id: str
    question: str
    task_category: str
    selected_agents: list[str]
    route_reason: str
    relevant_files: list[str]
    relevant_symbols: list[str]
    dependency_context: dict[str, Any]
    agent_statuses: dict[str, str]
    agent_results: list[dict[str, Any]]
    errors: list[dict[str, str]]
    execution_metadata: dict[str, Any]
    final_response: str
    forced: str | None
    previous_agent: str | None
    symbol_mention: bool
    runner: Any
    stream_runner: Any
    progress: Any
    consolidator: Any
    result: dict[str, Any]


def _selected_agents(question: str, scores: dict[str, int], primary: str, forced: str | None) -> list[str]:
    if forced:
        return [LEGACY_AGENT_ALIASES.get(forced, forced)]
    if _CONNECTOR.search(question):
        matching = [agent for agent in PRIORITY if scores[agent] >= 2]
        if len(matching) > 1:
            return matching
    return [primary]


class Supervisor:
    """Compiled LangGraph; executes only selected specialists and records each outcome."""

    def __init__(self) -> None:
        graph = StateGraph(SharedState)
        graph.add_node("route", self._route)
        graph.add_node("execute_agents", self._execute_agents)
        graph.add_node("finalize", self._finalize)
        graph.set_entry_point("route")
        graph.add_edge("route", "execute_agents")
        graph.add_edge("execute_agents", "finalize")
        graph.add_edge("finalize", END)
        self.graph = graph.compile()

    @staticmethod
    def _route(state: SharedState) -> dict:
        scores = _scores(state["question"], state.get("symbol_mention", False))
        primary, reason = route_request(state["question"], state.get("forced"), state.get("previous_agent"),
                                       state.get("symbol_mention", False))
        selected = _selected_agents(state["question"], scores, primary, state.get("forced"))
        category = "multi-agent" if len(selected) > 1 else primary
        statuses = {agent: "pending" for agent in selected}
        if state.get("progress"):
            state["progress"]("agent-selection", selected, statuses, [], reason)
        return {"selected_agents": selected, "task_category": category, "route_reason": reason,
                "agent_statuses": statuses}

    @staticmethod
    def _execute_agents(state: SharedState) -> dict:
        results, errors, statuses = [], [], dict(state.get("agent_statuses", {}))
        for agent_id in state["selected_agents"]:
            statuses[agent_id] = "running"
            if state.get("progress"):
                state["progress"](f"agent:{agent_id}", state["selected_agents"], statuses, results, state["route_reason"])
            try:
                runner = state.get("stream_runner") if len(state["selected_agents"]) == 1 else None
                result = runner(agent_id, state["question"]) if runner else state["runner"](agent_id, state["question"])
                if not isinstance(result, dict):
                    raise TypeError("Agent returned an invalid result.")
            except Exception as exc:
                result = {"agent": agent_id, "status": "failed", "answer": "", "error": str(exc),
                          "files": [], "evidence": [], "warnings": [], "steps": []}
            status = result.get("status", "completed")
            statuses[agent_id] = status if status in ("failed", "partial") else "completed"
            result = {**result, "agent": agent_id}
            results.append(result)
            if state.get("progress"):
                state["progress"]("collecting-results", state["selected_agents"], statuses, results, state["route_reason"])
            if status == "failed":
                errors.append({"agent": agent_id, "message": result.get("error") or "Agent execution failed."})
        evidence = [item for result in results for item in result.get("evidence", [])]
        relevant_files = {item["path"] for item in evidence if item.get("path")}
        relevant_files.update(file["path"] for result in results for file in result.get("files", []) if file.get("path"))
        relevant_symbols = {item["symbol"] for item in evidence if item.get("symbol")}
        dependency_context = [item for item in evidence if item.get("kind") == "dependency"]
        return {"agent_results": results, "agent_statuses": statuses, "errors": errors,
                "relevant_files": sorted(relevant_files), "relevant_symbols": sorted(relevant_symbols),
                "dependency_context": dependency_context}

    @staticmethod
    def _finalize(state: SharedState) -> dict:
        results = state.get("agent_results", [])
        successful = [item for item in results if item.get("status") != "failed"]
        primary = state["selected_agents"][0]
        if not successful:
            answer = "No specialist agent completed successfully. See the workflow errors for details."
            status = "failed"
        elif len(successful) == 1:
            answer = successful[0].get("answer", "")
            status = "partial" if state.get("errors") else successful[0].get("status", "completed")
        else:
            try:
                answer = state["consolidator"](successful)
                status = "partial" if state.get("errors") else "completed"
            except Exception as exc:
                answer = "\n\n".join(f"### {AGENTS[item['agent']].name}\n\n{item.get('answer', '')}" for item in successful)
                state.setdefault("errors", []).append({"agent": "supervisor", "message": f"Consolidation failed: {exc}"})
                status = "partial" if state.get("errors") else "completed"
        files = list({(f.get("path"), f.get("line")): f for item in successful for f in item.get("files", [])}.values())
        evidence = [ev for item in successful for ev in item.get("evidence", [])]
        warnings = [warning for item in results for warning in item.get("warnings", [])]
        steps = [{"agentId": SUPERVISOR_ID, "label": f"Selected {len(state['selected_agents'])} specialist agent(s): "
                                                          + ", ".join(AGENTS[a].name for a in state["selected_agents"])}]
        for item in results:
            steps.extend(item.get("steps", []))
        elapsed = int((time.perf_counter() - state["execution_metadata"]["started"]) * 1000)
        result = {
            "agent": primary, "selectedAgents": state["selected_agents"], "agentResults": results,
            "agentStatuses": state["agent_statuses"], "taskCategory": state["task_category"],
            "requestId": state["request_id"], "routeReason": state["route_reason"], "steps": steps,
            "answer": answer, "finalResponse": answer, "files": files, "evidence": evidence,
            "warnings": warnings, "errors": state.get("errors", []), "status": status, "durationMs": elapsed,
            "stage": "partial" if status == "partial" else ("completed" if status != "failed" else "failed"),
        }
        return {"final_response": answer, "result": result,
                "execution_metadata": {"durationMs": elapsed, "status": status, "stage": result["stage"]}}

    def run(self, question: str, runner: Callable[[str, str], dict], forced: str | None = None,
            previous_agent: str | None = None, symbol_mention: bool = False, repository_id: str = "",
            request_id: str | None = None, consolidator: Callable[[list[dict]], str] | None = None,
            relevant_files: list[str] | None = None, relevant_symbols: list[str] | None = None,
            dependency_context: dict[str, Any] | None = None,
            stream_runner: Callable[[str, str], dict] | None = None,
            progress: Callable[[str, list[str], dict[str, str], list[dict[str, Any]], str], None] | None = None) -> dict:
        state = self.graph.invoke({
            "request_id": request_id or str(uuid.uuid4()), "repository_id": repository_id, "question": question,
            "forced": forced, "previous_agent": previous_agent, "symbol_mention": symbol_mention, "runner": runner,
            "stream_runner": stream_runner,
            "progress": progress,
            "consolidator": consolidator, "relevant_files": relevant_files or [],
            "relevant_symbols": relevant_symbols or [], "dependency_context": dependency_context or {},
            "execution_metadata": {"started": time.perf_counter()},
        })
        return state["result"]
