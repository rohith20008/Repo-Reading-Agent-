"""SQLite persistence for chat, agent runs, investigations and documents."""
from __future__ import annotations

import json
import uuid

from ..db import Database
from ..errors import ApiError
from ..repo_service import utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _message(row) -> dict:
    item = {
        "id": row["id"], "role": row["role"], "content": row["content"], "createdAt": row["created_at"],
        "agent": row["agent"], "files": json.loads(row["files_json"]), "warnings": json.loads(row["warnings_json"]),
        "error": row["error"],
    }
    if "workflow_id" in row.keys():
        item["requestId"] = row["workflow_id"]
    if "workflow_selected_agents" in row.keys() and row["workflow_selected_agents"] is not None:
        item.update({
            "selectedAgents": json.loads(row["workflow_selected_agents"]),
            "agentStatuses": json.loads(row["workflow_agent_statuses"]),
            "agentResults": json.loads(row["workflow_agent_results"]),
            "errors": json.loads(row["workflow_errors"]),
            "stage": row["workflow_stage"],
            "durationMs": row["workflow_duration_ms"],
        })
    return item


def _document(row) -> dict:
    return {
        "id": row["id"], "title": row["title"], "type": row["type"], "repositoryId": row["repository_id"],
        "repositoryName": row["repository_name"] if "repository_name" in row.keys() else "", "module": row["module"],
        "instructions": row["instructions"], "format": "markdown", "content": row["content_md"], "status": row["status"],
        "aiEnhanced": bool(row["ai_enhanced"]), "warnings": json.loads(row["warnings_json"]),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"], "failureReason": row["failure_reason"],
    }


class AIStore:
    def __init__(self, db: Database):
        self.db = db

    # ---- conversations -----------------------------------------------------------------
    def create_conversation(self, repo_id: str, title: str) -> str:
        cid, now = new_id("conv"), utcnow()
        with self.db.tx() as conn:
            conn.execute("INSERT INTO conversations (id, repository_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                         (cid, repo_id, title[:60] or "New conversation", now, now))
        return cid

    def conversation(self, cid: str) -> dict:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n FROM conversations c WHERE c.id=?",
                (cid,),
            ).fetchone()
        if row is None:
            raise ApiError(404, "conversation_not_found", "Conversation not found.")
        return self._conversation(row)

    @staticmethod
    def _conversation(row) -> dict:
        return {"id": row["id"], "title": row["title"], "repositoryId": row["repository_id"],
                "createdAt": row["created_at"], "updatedAt": row["updated_at"], "messageCount": row["n"]}

    def conversations(self, repo_id: str) -> list[dict]:
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS n FROM conversations c"
                " WHERE c.repository_id=? ORDER BY c.updated_at DESC, c.rowid DESC", (repo_id,)
            ).fetchall()
        return [self._conversation(r) for r in rows]

    def conversation_with_messages(self, cid: str) -> dict:
        data = self.conversation(cid)
        data["messages"] = self.messages(cid)
        return data

    def messages(self, cid: str, limit: int | None = None) -> list[dict]:
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT m.*, w.selected_agents_json AS workflow_selected_agents,"
                " w.agent_statuses_json AS workflow_agent_statuses, w.agent_results_json AS workflow_agent_results,"
                " w.errors_json AS workflow_errors, w.stage AS workflow_stage, w.duration_ms AS workflow_duration_ms"
                " FROM messages m LEFT JOIN agent_workflows w ON w.id=m.workflow_id"
                " WHERE m.conversation_id=? ORDER BY m.rowid", (cid,)
            ).fetchall()
        items = [_message(r) for r in rows]
        return items[-limit:] if limit else items

    def add_message(self, cid: str, role: str, content: str, agent: str | None = None, files: list | None = None,
                    evidence: list | None = None, warnings: list | None = None, error: str | None = None,
                    workflow_id: str | None = None, message_id: str | None = None) -> dict:
        mid, now = message_id or new_id("msg"), utcnow()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, agent, files_json, evidence_json, warnings_json,"
                " error, created_at, workflow_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (mid, cid, role, content, agent, json.dumps(files or []), json.dumps(evidence or []),
                 json.dumps(warnings or []), error, now, workflow_id),
            )
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, cid))
        return {"id": mid, "role": role, "content": content, "createdAt": now, "agent": agent, "files": files or [],
                "warnings": warnings or [], "error": error, "requestId": workflow_id}

    def retry_failed_message(self, cid: str, assistant_message_id: str) -> dict:
        with self.db.tx() as conn:
            assistant = conn.execute(
                "SELECT rowid, role, error FROM messages WHERE id=? AND conversation_id=?",
                (assistant_message_id, cid),
            ).fetchone()
            if assistant is None or assistant["role"] != "assistant" or not assistant["error"]:
                raise ApiError(404, "message_not_found", "The failed answer to retry was not found.")
            if conn.execute(
                "SELECT 1 FROM messages WHERE conversation_id=? AND rowid>? LIMIT 1",
                (cid, assistant["rowid"]),
            ).fetchone():
                raise ApiError(409, "retry_not_available", "Only the latest failed answer can be retried.")
            user = conn.execute(
                "SELECT id, role FROM messages WHERE conversation_id=? AND rowid<? ORDER BY rowid DESC LIMIT 1",
                (cid, assistant["rowid"]),
            ).fetchone()
            if user is None or user["role"] != "user":
                raise ApiError(409, "retry_not_available", "The failed answer has no matching user question.")
            user_message_id = user["id"]
            conn.execute("DELETE FROM messages WHERE id=?", (assistant_message_id,))
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utcnow(), cid))
        return next(item for item in self.messages(cid) if item["id"] == user_message_id)

    def rename_conversation(self, cid: str, title: str) -> dict:
        with self.db.tx() as conn:
            changed = conn.execute("UPDATE conversations SET title=? WHERE id=?", (title.strip()[:120], cid)).rowcount
        if not changed:
            raise ApiError(404, "conversation_not_found", "Conversation not found.")
        return self.conversation(cid)

    def delete_conversation(self, cid: str) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE agent_runs SET conversation_id=NULL WHERE conversation_id=?", (cid,))
            conn.execute("UPDATE agent_workflows SET conversation_id=NULL WHERE conversation_id=?", (cid,))
            if not conn.execute("DELETE FROM conversations WHERE id=?", (cid,)).rowcount:
                raise ApiError(404, "conversation_not_found", "Conversation not found.")

    # ---- agent runs --------------------------------------------------------------------
    def add_run(self, repo_id: str, conversation_id: str | None, agent: str, question: str, route_reason: str | None,
                status: str, provider: str | None, model: str | None, started_at: str, duration_ms: int,
                evidence_count: int, error: str | None, workflow_id: str | None = None) -> str:
        rid = new_id("run")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO agent_runs (id, repository_id, conversation_id, agent, question, route_reason, status, provider,"
                " model, started_at, duration_ms, evidence_count, error, workflow_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, repo_id, conversation_id, agent, question[:500], route_reason, status, provider, model, started_at,
                 duration_ms, evidence_count, error, workflow_id),
            )
        return rid

    def runs(self, repo_id: str | None, limit: int) -> list[dict]:
        sql = ("SELECT r.*, p.name AS repository_name, w.selected_agents_json, w.agent_results_json,"
               " w.stage AS workflow_stage, w.status AS workflow_status FROM agent_runs r"
               " JOIN repositories p ON p.id=r.repository_id LEFT JOIN agent_workflows w ON w.id=r.workflow_id"
               + (" WHERE r.repository_id=?" if repo_id else "") + " ORDER BY r.started_at DESC, r.rowid DESC LIMIT ?")
        with self.db.session() as conn:
            rows = conn.execute(sql, ((repo_id, limit) if repo_id else (limit,))).fetchall()
        result = []
        for r in rows:
            item = {
                "id": r["id"], "repositoryId": r["repository_id"], "repositoryName": r["repository_name"],
                "agent": r["agent"], "question": r["question"], "status": r["status"],
                "routeReason": r["route_reason"], "provider": r["provider"], "model": r["model"],
                "startedAt": r["started_at"], "durationMs": r["duration_ms"],
                "evidenceCount": r["evidence_count"], "error": r["error"],
                "conversationId": r["conversation_id"], "requestId": r["workflow_id"],
                "stage": r["workflow_stage"],
            }
            if r["selected_agents_json"] is not None:
                item["selectedAgents"] = json.loads(r["selected_agents_json"])
                item["workflowStatus"] = r["workflow_status"]
                item["agentOutput"] = next((agent.get("answer", "") for agent in json.loads(r["agent_results_json"])
                                            if agent.get("agent") == r["agent"]), "")
            result.append(item)
        return result

    # ---- LangGraph workflows -----------------------------------------------------------
    def start_workflow(self, workflow_id: str, repo_id: str, conversation_id: str | None, question: str,
                       started_at: str) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO agent_workflows (id, repository_id, conversation_id, question, status, stage, started_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (workflow_id, repo_id, conversation_id, question[:500], "running", "routing", started_at),
            )

    def recover_interrupted_workflows(self) -> None:
        now = utcnow()
        errors = json.dumps([{"agent": "supervisor", "message": "The backend stopped before this workflow completed."}])
        with self.db.tx() as conn:
            rows = conn.execute(
                "SELECT id, agent_statuses_json FROM agent_workflows WHERE status IN ('queued','running')"
            ).fetchall()
            for row in rows:
                statuses = json.loads(row["agent_statuses_json"])
                statuses = {agent: "failed" if state in ("queued", "pending", "running") else state
                            for agent, state in statuses.items()}
                conn.execute(
                    "UPDATE agent_workflows SET status='failed', stage='failed', finished_at=?, errors_json=?,"
                    " agent_statuses_json=?, final_response='Workflow interrupted because the backend stopped.'"
                    " WHERE id=?",
                    (now, errors, json.dumps(statuses), row["id"]),
                )

    def update_workflow_progress(self, workflow_id: str, stage: str, selected_agents: list[str] | None = None,
                                 agent_statuses: dict[str, str] | None = None,
                                 agent_results: list[dict] | None = None, route_reason: str | None = None) -> None:
        with self.db.tx() as conn:
            changed = conn.execute(
                "UPDATE agent_workflows SET stage=?,"
                " selected_agents_json=COALESCE(?, selected_agents_json),"
                " agent_statuses_json=COALESCE(?, agent_statuses_json),"
                " agent_results_json=COALESCE(?, agent_results_json),"
                " route_reason=COALESCE(?, route_reason)"
                " WHERE id=? AND status IN ('queued','running')",
                (stage, json.dumps(selected_agents) if selected_agents is not None else None,
                 json.dumps(agent_statuses) if agent_statuses is not None else None,
                 json.dumps(agent_results) if agent_results is not None else None, route_reason, workflow_id),
            ).rowcount
        if not changed:
            raise ApiError(409, "workflow_not_running", "Agent workflow is no longer active.")

    def finish_workflow(self, workflow_id: str, result: dict) -> None:
        evidence = [ev for item in result.get("agentResults", []) for ev in item.get("evidence", [])]
        context = {
            "relevantFiles": sorted({ev["path"] for ev in evidence if ev.get("path")}),
            "relevantSymbols": sorted({ev["symbol"] for ev in evidence if ev.get("symbol")}),
            "dependencyContext": [ev for ev in evidence if ev.get("kind") == "dependency"],
        }
        with self.db.tx() as conn:
            changed = conn.execute(
                "UPDATE agent_workflows SET task_category=?, selected_agents_json=?, agent_statuses_json=?,"
                " route_reason=?, agent_results_json=?, relevant_context_json=?, errors_json=?, final_response=?, status=?, stage=?,"
                " finished_at=?, duration_ms=? WHERE id=?",
                (result.get("taskCategory", ""), json.dumps(result.get("selectedAgents", [])),
                 json.dumps(result.get("agentStatuses", {})), result.get("routeReason"), json.dumps(result.get("agentResults", [])),
                 json.dumps(context), json.dumps(result.get("errors", [])), result.get("finalResponse", ""),
                 result.get("status", "failed"), result.get("stage", "failed"), utcnow(),
                 result.get("durationMs", 0), workflow_id),
            ).rowcount
        if not changed:
            raise ApiError(404, "workflow_not_found", "Agent workflow not found.")

    @staticmethod
    def _workflow(row) -> dict:
        return {
            "requestId": row["id"], "repositoryId": row["repository_id"], "conversationId": row["conversation_id"],
            "question": row["question"], "taskCategory": row["task_category"],
            "routeReason": row["route_reason"],
            "selectedAgents": json.loads(row["selected_agents_json"]),
            "agentStatuses": json.loads(row["agent_statuses_json"]),
            "agentResults": json.loads(row["agent_results_json"]),
            "relevantContext": json.loads(row["relevant_context_json"]),
            "errors": json.loads(row["errors_json"]), "finalResponse": row["final_response"],
            "status": row["status"], "stage": row["stage"], "startedAt": row["started_at"],
            "finishedAt": row["finished_at"], "durationMs": row["duration_ms"],
        }

    def workflow(self, workflow_id: str) -> dict:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM agent_workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            raise ApiError(404, "workflow_not_found", "Agent workflow not found.")
        return self._workflow(row)

    def workflows(self, repo_id: str | None = None, limit: int = 50, agent: str | None = None,
                  status: str | None = None, started_after: str | None = None,
                  started_before: str | None = None) -> list[dict]:
        clauses, params = [], []
        if repo_id:
            clauses.append("w.repository_id=?")
            params.append(repo_id)
        if agent:
            clauses.append("instr(w.selected_agents_json, json_quote(?))>0")
            params.append(agent)
        if status:
            clauses.append("w.status=?")
            params.append(status)
        if started_after:
            clauses.append("w.started_at>=?")
            params.append(started_after)
        if started_before:
            clauses.append("w.started_at<=?")
            params.append(started_before)
        sql = ("SELECT w.*, r.name AS repository_name FROM agent_workflows w"
               " JOIN repositories r ON r.id=w.repository_id"
               + (" WHERE " + " AND ".join(clauses) if clauses else "")
               + " ORDER BY w.started_at DESC, w.rowid DESC LIMIT ?")
        params.append(limit)
        with self.db.session() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [{**self._workflow(row), "repositoryName": row["repository_name"]} for row in rows]

    # ---- investigations ----------------------------------------------------------------
    def save_investigation(self, repo_id: str, result: dict) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO investigations (id, repository_id, title, status, confidence, created_at, completed_at, result_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (result["id"], repo_id, result["title"], result["status"], result.get("confidence"), result["createdAt"],
                 result.get("completedAt"), json.dumps(result)),
            )

    def investigation(self, iid: str) -> dict:
        with self.db.session() as conn:
            row = conn.execute("SELECT result_json FROM investigations WHERE id=?", (iid,)).fetchone()
        if row is None:
            raise ApiError(404, "investigation_not_found", "Investigation not found.")
        return json.loads(row["result_json"])

    def investigations(self, repo_id: str) -> list[dict]:
        with self.db.session() as conn:
            rows = conn.execute(
                "SELECT result_json FROM investigations WHERE repository_id=? ORDER BY created_at DESC, rowid DESC", (repo_id,)
            ).fetchall()
        return [json.loads(r["result_json"]) for r in rows]

    def delete_investigation(self, iid: str) -> None:
        with self.db.tx() as conn:
            if not conn.execute("DELETE FROM investigations WHERE id=?", (iid,)).rowcount:
                raise ApiError(404, "investigation_not_found", "Investigation not found.")

    # ---- documents ---------------------------------------------------------------------
    def save_document(self, repo_id: str, doc_type: str, module: str | None, instructions: str | None, title: str,
                      content: str, ai_enhanced: bool, warnings: list[str], status: str, failure: str | None) -> str:
        did, now = new_id("doc"), utcnow()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO documents (id, repository_id, type, module, instructions, title, content_md, ai_enhanced,"
                " warnings_json, status, failure_reason, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, repo_id, doc_type, module, instructions, title, content, int(ai_enhanced), json.dumps(warnings),
                 status, failure, now, now),
            )
        return did

    _DOC_SQL = "SELECT d.*, r.name AS repository_name FROM documents d JOIN repositories r ON r.id=d.repository_id"

    def document(self, did: str) -> dict:
        with self.db.session() as conn:
            row = conn.execute(f"{self._DOC_SQL} WHERE d.id=?", (did,)).fetchone()
        if row is None:
            raise ApiError(404, "document_not_found", "Document not found.")
        return _document(row)

    def documents(self, repo_id: str) -> list[dict]:
        with self.db.session() as conn:
            rows = conn.execute(f"{self._DOC_SQL} WHERE d.repository_id=? ORDER BY d.created_at DESC, d.rowid DESC", (repo_id,)).fetchall()
        return [_document(r) for r in rows]

    def delete_document(self, did: str) -> None:
        with self.db.tx() as conn:
            if not conn.execute("DELETE FROM documents WHERE id=?", (did,)).rowcount:
                raise ApiError(404, "document_not_found", "Document not found.")
