"""The six agents. Each one gathers evidence from real repository data and has its own system prompt. The model is
asked to answer only from that evidence (see evidence.py for the prompt block and the grounding checks)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import ApiError
from ..intelligence import graph as graph_analysis
from .context import AIContext
from .docs import architecture_markdown, dependency_markdown, overview_markdown
from .evidence import GROUNDING_RULES, EvidenceSet, tokenize


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    role: str
    description: str
    uses_ai: bool = True


AGENTS: dict[str, AgentSpec] = {a.id: a for a in [
    AgentSpec("repository-explorer", "Repository Understanding Agent", "Repository structure",
              "Uses indexed symbols and architecture evidence to explain repository structure, entry points and module responsibilities."),
    AgentSpec("code-intelligence", "Code Analysis Agent", "Functions and classes",
              "Analyzes functions, classes, measurable code properties and their indexed relationships."),
    AgentSpec("bug-investigator", "Bug Investigator", "Error analysis",
              "Investigates error messages and stack traces and points at the likely cause in the code."),
    AgentSpec("dependency-analyst", "Dependency Intelligence Agent", "Imports and packages",
              "Explains internal and external dependencies, circular dependencies and affected modules from the graph."),
    AgentSpec("documentation", "Documentation Agent", "Technical documentation",
              "Generates repository, architecture, module, API and dependency documentation from the real index."),
    AgentSpec("code-recommendation", "Code Recommendation Agent", "Evidence-based recommendations",
              "Suggests improvements grounded in repository evidence and never modifies source files."),
]}

SUPERVISOR_ID = "supervisor"

_STYLE = " Answer in concise Markdown. Name files as `path:line` when the evidence gives a line. "
PROMPTS = {
    "repository-explorer": "You are the Repository Understanding agent of CODEMIND AI. You explain how a repository is organised "
                           "using only supplied facts about files, languages, symbols, modules, architecture and entry points." + _STYLE + GROUNDING_RULES,
    "code-intelligence": "You are the Code Intelligence agent of CODEMIND AI. You explain functions, classes and code using only "
                         "the supplied definitions, references and snippets." + _STYLE + GROUNDING_RULES,
    "dependency-analyst": "You are the Dependency Intelligence agent of CODEMIND AI. You explain imports, packages and dependency "
                          "relationships using only the supplied dependency facts. Imports marked unresolved could not be "
                          "classified; never guess their origin." + _STYLE + GROUNDING_RULES,
    "code-recommendation": "You are the Code Recommendation agent of CODEMIND AI. Suggest possible improvements only when "
                           "supported by the supplied repository evidence. Explain rationale and cite files/symbols. "
                           "Clearly label hypotheses. Never claim to change files and never output instructions that "
                           "would automatically modify source code." + _STYLE + GROUNDING_RULES,
}


@dataclass
class Gathered:
    evidence: EvidenceSet
    needs_evidence: bool = False
    warnings: list[str] = field(default_factory=list)


def _merge(target: EvidenceSet, source: EvidenceSet) -> None:
    for e in source.items:
        target.add(e.path, e.start_line, e.end_line, e.kind, e.reason, e.snippet, e.symbol, e.focus_line)


def _readme(ctx: AIContext, evidence: EvidenceSet) -> None:
    with ctx.db.session() as conn:
        row = conn.execute(
            "SELECT path FROM files WHERE repository_id=? AND category='doc' AND lower(name) LIKE 'readme%'"
            " ORDER BY length(path) LIMIT 1", (ctx.repo_id,)
        ).fetchone()
    if row:
        ctx.retriever.add_file_head(evidence, row["path"], 60, f"project README ({row['path']})")


def gather_explorer(ctx: AIContext, question: str) -> Gathered:
    evidence = EvidenceSet()
    overview, _ = overview_markdown(ctx)
    evidence.add("", 0, 0, "overview", "repository overview: languages, frameworks, structure, entry points", overview)
    warnings = []
    if ctx.parsed:
        architecture, warnings = architecture_markdown(ctx)
        evidence.add("", 0, 0, "overview", "indexed modules, responsibilities and architecture relationships", architecture)
    _readme(ctx, evidence)
    if ctx.parsed:
        for item in graph_analysis.graph_stats(ctx.db, ctx.repo_id)["important_modules"][:4]:
            ctx.retriever.add_file_head(evidence, item["path"], 25, f"most depended-on file (imported by {item['fan_in']} files)")
    else:
        warnings.append("The repository has not been parsed, so important files could not be ranked by imports.")
    _merge(evidence, ctx.retriever.search(question, 3))
    return Gathered(evidence, False, warnings)


def _references_text(ctx: AIContext, symbol_id: int) -> str:
    data = ctx.intel.references(ctx.repo_id, symbol_id, 12)
    lines = [f"Files that import {data['symbol']['path']}: " + (
        ", ".join(f"{i['path']}:{i['line']} ({i['evidence']})" for i in data["imported_by"]) or "none")]
    refs = [f"{r['path']}:{r['line']} {r['kind']} from {r['source'] or 'module level'} [{r['confidence']}]" for r in data["references"]]
    lines.append("References by name: " + ("; ".join(refs) if refs else "none found"))
    lines.append(data["note"])
    return "\n".join(lines)


def gather_code(ctx: AIContext, question: str) -> Gathered:
    warnings = [] if ctx.parsed else ["The repository has not been parsed: symbol search and references are unavailable."]
    evidence = ctx.retriever.search(question, 8)
    tokens, identifiers = tokenize(question)
    hits = ctx.retriever.symbol_hits(tokens, identifiers, 1)
    if hits and ctx.parsed:
        top = hits[0]
        evidence.add(top.path, top.start_line, top.end_line, "dependency",
                     f"who imports and references {top.qualified_name}", _references_text(ctx, top.id), symbol=top.qualified_name)
    return Gathered(evidence, True, warnings)


def gather_dependency(ctx: AIContext, question: str) -> Gathered:
    evidence = EvidenceSet()
    text, warnings = dependency_markdown(ctx)
    evidence.add("", 0, 0, "dependency", "declared packages, imports, unresolved imports, cycles", text)
    if ctx.parsed:
        for path in ctx.retriever.mentioned_paths(question)[:2]:
            rel = graph_analysis.file_relations(ctx.db, ctx.repo_id, path)
            imports = ctx.intel.imports(ctx.repo_id, path, None, None, 60, 0)["items"]
            body = (f"{path} imports (repository files): {', '.join(rel['imports']) or 'none'}\n"
                    f"{path} is imported by: {', '.join(rel['imported_by']) or 'none'}\n"
                    f"External packages used: {', '.join(rel['external_packages']) or 'none'}\n"
                    f"In a dependency cycle: {'yes, with ' + ', '.join(rel['cycle_with']) if rel['in_cycle'] else 'no'}\n"
                    "Imports: " + "; ".join(f"line {i['line']} {i['module']} [{i['dep_type']}]" for i in imports))
            evidence.add(path, 1, 1, "dependency", f"import relationships of {path}", body)
        tokens, _ = tokenize(question)
        with ctx.db.session() as conn:
            for token in tokens[:5]:
                rows = conn.execute(
                    "SELECT path, line, module FROM imports WHERE repository_id=? AND dep_type='external' AND lower(package)=? LIMIT 12",
                    (ctx.repo_id, token)).fetchall()
                if rows:
                    evidence.add("", 0, 0, "dependency", f"files importing the package '{token}'",
                                 "\n".join(f"{r['path']}:{r['line']} imports {r['module']}" for r in rows))
    return Gathered(evidence, False, warnings)


def gather(agent_id: str, ctx: AIContext, question: str) -> Gathered:
    gatherers = {"repository-explorer": gather_explorer,
                 "code-intelligence": gather_code, "dependency-analyst": gather_dependency,
                 "code-recommendation": gather_code}
    if agent_id not in gatherers:
        raise ApiError(422, "unknown_agent", f"Agent '{agent_id}' does not answer free-form questions through this path.")
    return gatherers[agent_id](ctx, question)
