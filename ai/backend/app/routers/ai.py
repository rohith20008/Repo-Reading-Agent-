from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..ai.agents import AGENTS
from ..ai.docs import DOC_TYPES
from ..errors import ApiError
from ..schemas import CamelModel

router = APIRouter(prefix="/api", tags=["ai"])
logger = logging.getLogger(__name__)


class ChatRequest(CamelModel):
    message: str
    conversation_id: str | None = None
    agent: str | None = None
    retry_message_id: str | None = None


class RenameRequest(CamelModel):
    title: str


class ContextSearchRequest(CamelModel):
    query: str
    limit: int = 8


class AgentRunRequest(CamelModel):
    question: str


class InvestigationRequest(CamelModel):
    title: str | None = None
    description: str | None = None
    error_message: str | None = None
    stack_trace: str | None = None
    file_path: str | None = None
    affected_module: str | None = None


class DocumentRequest(CamelModel):
    type: str
    module: str | None = None
    instructions: str | None = None
    use_ai: bool = True


def _ai(request: Request):
    return request.app.state.ai


# ---- status and agents -----------------------------------------------------------------------
@router.get("/ai/status")
def ai_status(request: Request, check: bool = True, refresh: bool = False):
    """Return a live Ollama/model check; refresh=true bypasses the ten-second cache."""
    return _ai(request).status(check, refresh)


@router.get("/ai/agents")
def ai_agents():
    return [{"id": a.id, "name": a.name, "role": a.role, "description": a.description, "usesAi": a.uses_ai}
            for a in AGENTS.values()]


# ---- chat ------------------------------------------------------------------------------------
@router.post("/repositories/{repo_id}/chat")
def chat(repo_id: str, body: ChatRequest, request: Request):
    return _ai(request).chat(repo_id, body.message, body.conversation_id, body.agent, retry_message_id=body.retry_message_id)


@router.post("/repositories/{repo_id}/chat/stream")
async def chat_stream(repo_id: str, body: ChatRequest, request: Request):
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_token(text: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "delta", "text": text})

    async def execute():
        try:
            result = await asyncio.to_thread(
                _ai(request).chat, repo_id, body.message, body.conversation_id, body.agent, on_token, body.retry_message_id,
            )
            await queue.put({"type": "complete", "data": result})
        except ApiError as exc:
            await queue.put({"type": "error", "data": {"code": exc.code, "message": exc.message, **exc.extra}})
        except Exception:
            logger.exception("Unexpected failure while executing a streamed chat workflow")
            await queue.put({"type": "error", "data": {
                "code": "internal_error", "message": "The chat workflow failed unexpectedly. Please retry.",
            }})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(execute())
        while True:
            event = await queue.get()
            if event is None:
                await task
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/repositories/{repo_id}/conversations")
def conversations(repo_id: str, request: Request):
    request.app.state.repos.get(repo_id)
    return _ai(request).store.conversations(repo_id)


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, request: Request):
    return _ai(request).store.conversation_with_messages(conversation_id)


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: RenameRequest, request: Request):
    return _ai(request).store.rename_conversation(conversation_id, body.title)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, request: Request):
    _ai(request).store.delete_conversation(conversation_id)
    return Response(status_code=204)


@router.post("/repositories/{repo_id}/context/search")
def context_search(repo_id: str, body: ContextSearchRequest, request: Request):
    return _ai(request).retrieve(repo_id, body.query, max(1, min(body.limit, 30)))


# ---- agents ----------------------------------------------------------------------------------
@router.get("/agent-runs")
def all_agent_runs(request: Request, limit: int = Query(100, ge=1, le=500)):
    return _ai(request).store.runs(None, limit)


@router.get("/agent-workflows")
def all_agent_workflows(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    repository_id: str | None = None,
    agent: str | None = None,
    status: str | None = Query(None, pattern="^(queued|running|completed|partial|failed|evidence_only|no_evidence)$"),
    started_after: str | None = None,
    started_before: str | None = None,
):
    return _ai(request).store.workflows(repository_id, limit, agent, status, started_after, started_before)


@router.get("/repositories/{repo_id}/agent-runs")
def agent_runs(repo_id: str, request: Request, limit: int = Query(100, ge=1, le=500)):
    request.app.state.repos.get(repo_id)
    return _ai(request).store.runs(repo_id, limit)


@router.get("/repositories/{repo_id}/agent-workflows")
def agent_workflows(repo_id: str, request: Request, limit: int = Query(50, ge=1, le=200)):
    request.app.state.repos.get(repo_id)
    return _ai(request).store.workflows(repo_id, limit)


@router.get("/agent-workflows/{workflow_id}")
def agent_workflow(workflow_id: str, request: Request):
    return _ai(request).store.workflow(workflow_id)


@router.post("/repositories/{repo_id}/agents/{agent_id}/run")
def run_agent(repo_id: str, agent_id: str, body: AgentRunRequest, request: Request):
    return _ai(request).run_agent(repo_id, agent_id, body.question)


# ---- investigations --------------------------------------------------------------------------
@router.post("/repositories/{repo_id}/investigations")
def start_investigation(repo_id: str, body: InvestigationRequest, request: Request):
    return _ai(request).investigate(repo_id, {
        "title": body.title, "description": body.description, "errorMessage": body.error_message,
        "stackTrace": body.stack_trace, "filePath": body.file_path, "affectedModule": body.affected_module,
    })


@router.get("/repositories/{repo_id}/investigations")
def list_investigations(repo_id: str, request: Request):
    request.app.state.repos.get(repo_id)
    return _ai(request).store.investigations(repo_id)


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str, request: Request):
    return _ai(request).store.investigation(investigation_id)


@router.delete("/investigations/{investigation_id}", status_code=204)
def delete_investigation(investigation_id: str, request: Request):
    _ai(request).store.delete_investigation(investigation_id)
    return Response(status_code=204)


# ---- documentation ---------------------------------------------------------------------------
@router.get("/documentation/types")
def documentation_types():
    return DOC_TYPES


@router.post("/repositories/{repo_id}/documentation")
def generate_documentation(repo_id: str, body: DocumentRequest, request: Request):
    return _ai(request).generate_document(repo_id, body.type, body.module, body.instructions, body.use_ai)


@router.get("/repositories/{repo_id}/documentation")
def list_documentation(repo_id: str, request: Request):
    request.app.state.repos.get(repo_id)
    return _ai(request).store.documents(repo_id)


@router.get("/documentation/{document_id}")
def get_document(document_id: str, request: Request):
    return _ai(request).store.document(document_id)


@router.delete("/documentation/{document_id}", status_code=204)
def delete_document(document_id: str, request: Request):
    _ai(request).store.delete_document(document_id)
    return Response(status_code=204)


@router.get("/documentation/{document_id}/export")
def export_document(document_id: str, request: Request, format: str = Query("md", pattern="^(md|json)$")):
    doc = _ai(request).store.document(document_id)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", doc["title"]).strip("-")[:80] or "document"
    if format == "json":
        body, media, extension = json.dumps(doc, indent=2), "application/json", "json"
    else:
        body, media, extension = doc["content"], "text/markdown; charset=utf-8", "md"
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}.{extension}"'})
