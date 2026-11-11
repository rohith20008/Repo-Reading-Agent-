# CODEMIND AI

CODEMIND AI is a local web application that helps you understand a codebase. You register a folder from your
computer, it scans and parses the code, and then you can explore files, search functions and classes, see the
architecture and dependencies, ask questions in an AI chat, investigate bugs and generate documentation.

Everything runs on your own computer. Repository code is only ever **read** (never executed).

```
agent_pro/   React + TypeScript + Vite frontend (http://localhost:5173)
backend/     FastAPI + SQLite backend           (http://localhost:8000)
scripts/     Windows PowerShell helper scripts
```

## What needs an AI model and what does not

| Feature | Needs AI inference? |
| --- | --- |
| Register, scan, languages / frameworks / statistics | No |
| File explorer, code parsing, symbol search (functions, classes), references | No |
| Dependency analysis, dependency graph, circular dependencies, architecture view | No |
| Documentation (overview, architecture, module, API, dependency report) | No – the facts are generated from the code. Ollama can add a written summary. |
| AI chat | **Yes** |
| Bug investigation | Evidence (stack-trace locations, matching code) works without AI; the root-cause explanation **needs AI** |

Repository registration, scanning, parsing and deterministic intelligence continue to work if Ollama is unavailable.

## Requirements

- Windows 10/11 (the scripts are PowerShell; the code itself is cross-platform)
- Python 3.11 or newer (developed with 3.12)
- Node.js 20 or newer and npm
- Optional: [Ollama](https://ollama.com) for local AI chat, recommendations and semantic re-ranking

## Quick start (Windows)

Open PowerShell in the project folder (`ai`) and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1        # once: venv, packages, database, npm install
powershell -ExecutionPolicy Bypass -File backend\scripts\start_ollama.ps1  # starts/reuses CODEMIND Ollama on 11435
powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1    # starts CODEMIND backend + frontend if ports are free
```

Default URLs are <http://127.0.0.1:5173> (frontend) and <http://127.0.0.1:8000> (backend). The backend health
check is <http://127.0.0.1:8000/api/health>; Ollama and model status is
<http://127.0.0.1:8000/api/ai/status?refresh=true>.

If a port is already used by another application, the startup script stops with the port and process ID rather than
opening that other application or terminating it. Choose free ports explicitly, for example:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1 -BackendPort 8001 -FrontendPort 5176
```

The script configures CORS for that frontend port in the backend process only and sets the Vite API URL to the
selected backend port. To stop the app, close the two CODEMIND PowerShell windows or press `Ctrl+C` in each.
This stops only the FastAPI and Vite processes; do not close or stop the separate Ollama server window if you want
to keep CODEMIND AI available. The Ollama listener on port 11434 is never stopped by CODEMIND.

### The same thing by hand

```powershell
# Ollama (one terminal; separate from backend lifetime)
cd backend
powershell -ExecutionPolicy Bypass -File scripts\start_ollama.ps1

# Backend (terminal 2; does not start or stop Ollama)
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                                   # only if backend\.env does not already exist
cd ..
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1

# Frontend (terminal 3)
cd agent_pro
npm install
npm run dev
```

The SQLite database is created automatically at `backend\data\codemind.db` the first time the backend starts
(`setup.ps1` also creates it up front). It contains registered paths, scan indexes and AI history; back it up before
maintenance and do not delete it to troubleshoot routine startup issues.
Interactive API documentation is available at <http://localhost:8000/docs>.

## Using the app

1. **Repositories** → *Add repository*. Enter an absolute Windows path such as `C:\Users\you\projects\my-app`
   (or pick one from the suggested folders). Git repositories and ordinary source folders both work.
2. Click **Scan**. The scan lists files and folders, languages, frameworks and package managers, and then the code
   is parsed automatically (functions, classes, imports). Progress is shown live.
3. **Explorer** – browse the tree, open files, see each file's symbols and imports, and search symbols by name.
4. **Architecture** and **Dependencies** – modules and how they import each other, external packages,
   circular dependencies and the most important modules.
5. **AI Chat** – pick a repository and ask questions. Answers stream from local Ollama and cite the real files and
   line numbers they used. Failed answers can be retried without duplicating the question in conversation history.
6. **Bug Investigation** – paste an error message and/or stack trace. The relevant code is located from the stack
   frames and searched; with local Ollama you also get a likely root cause and suggested fix (a suggestion only –
   nothing is changed in your files).
7. **Documentation** – generate and download Markdown documentation.
8. **Agents** – the six specialised agents and the history of what they ran.

## Architecture and data flows

### Frontend

`agent_pro/src` contains the React application. Vite serves it during development, React Router lazy-loads the
feature pages, and API services in `src/services/api` use the shared HTTP client. Context providers hold UI state;
durable conversations and generated records are fetched from the backend rather than treated as browser-only data.
The dependency graph uses the existing React Flow library. The chat stream is parsed as server-sent events and
only the answer text deltas are appended to the current assistant bubble; the supervisor result replaces that
temporary display when the request completes.

### Backend and repository intelligence

`backend/app/main.py` creates the FastAPI application and wires database, repository, scanner, parser, intelligence
and AI services into application state. Routers provide the HTTP surface, while services own the operations.
Repository registration resolves and validates a local folder on the backend. The scanner applies built-in and
repository ignore rules, records file metadata in SQLite, and the parser extracts supported language symbols,
imports and relationships from source files. Intelligence queries derive dependency and architecture views from
those persisted indexes; no model inference is needed for scanning or deterministic analysis.

### SQLite persistence

The database schema and additive compatibility migrations live in `backend/app/db.py`. Repository-owned files,
directories, scan/parse runs, symbols, imports, relations, technologies, conversations, messages, agent runs,
agent workflows, investigations and documents are stored in SQLite. Repository foreign keys cascade when a
repository is explicitly removed. WAL mode and short-lived connections allow ordinary reads during indexing.
Workflow history includes request, repository and conversation IDs, supervisor routing reason, selected agents,
current stage and statuses, specialist results, errors, final response and timing.

### Local AI, retrieval and agent execution

`backend/app/ai/providers.py` implements the inference boundary. Configuration permits Ollama only and requires a
loopback endpoint; there is no hosted-provider fallback. `CODEMIND_AI_MODEL` selects the chat model, and
`CODEMIND_AI_EMBEDDING_MODEL` selects the local embedding model. The six specialists are Repository Understanding,
Code Analysis, Bug Investigation, Dependency Intelligence, Documentation and Code Recommendation. The LangGraph
supervisor routes to a relevant specialist, or to a subset for a combined task, then collects and consolidates
their outputs. Recommendations are advisory; repository source is not edited by agents.

`GET /api/ai/status` performs a lightweight live Ollama tags check by default. It distinguishes server reachability
from whether the configured chat model is installed and caches the result for ten seconds. Add `?refresh=true` to
force a new check; `?check=false` reports configuration only without contacting Ollama.

Retrieval is repository-scoped and starts from SQLite symbol indexes and bounded source snippets. When configured,
local Nomic embeddings rerank the retrieved lexical candidates; vectors are created on demand rather than stored
as a separate vector database. If embedding inference is unavailable, the lexical ranking remains usable and a
warning is returned. Retrieved evidence is size-limited before it is sent to Ollama, and answer references are
checked against repository evidence.

### Chat, investigations and documentation

Chat requests create persisted user/assistant messages and a linked workflow record. The frontend uses the SSE
endpoint for streamed single-specialist code answers; multi-specialist work returns specialist output after
consolidation rather than streaming intermediate agent text. Conversation list, retrieval, rename, delete and
retry operations use backend persistence. Retrying the latest failed answer preserves its user turn and message ID.

Bug Investigation uses stack-frame mapping, file and symbol hints, literal error searches and caller evidence
before asking the local model to interpret the collected evidence. Its reports and workflow history are persisted;
it never applies a fix. Documentation is built from indexed repository facts, can optionally include a local AI
summary, is saved as a document, can be reopened and exported as Markdown or JSON. Generated documents are not
written into repository files.

### Agent monitoring

The Agent Monitor combines persisted agent runs with workflow records. It displays workflow stage and status,
selected agents, routing reason, results, errors and duration. Workflow filtering supports repository, specialist,
status and date boundaries. While a workflow is active, the frontend refreshes the persisted state periodically;
after it completes, active polling stops.

## API areas

The FastAPI API is rooted at `/api`; OpenAPI details are at `/docs`. Main workflow groups include:

- `/repositories`, `/scans`, `/parse-runs` and repository-scoped `/symbols`, `/imports`, `/dependencies`, `/dependency-graph`, `/architecture`.
- `/ai/status`, `/ai/agents`, repository-scoped `/context/search`, `/chat` and `/chat/stream`.
- `/conversations` for persisted conversation retrieval, rename and deletion.
- `/agent-runs` and `/agent-workflows` for persisted execution history and filters.
- `/repositories/{id}/investigations` and `/investigations/{id}` for investigation history.
- `/repositories/{id}/documentation` and `/documentation/{id}` for generation, retrieval, deletion and export.

Request and response models are defined with the routers and schemas; use `/docs` for the deployed version's
exact fields. Long-running scan and parse operations use background managers with status endpoints. Chat, direct
investigation and document generation currently return after their request completes, although their workflow
records expose progress to concurrent monitor polling.

## Known limitations

- General programming chat without selecting a scanned repository is not currently supported.
- Investigation and documentation calls are synchronous HTTP requests; their persisted workflow stages can be
  polled, but they do not have a dedicated SSE token/progress stream.
- Only single-specialist code-answer chat streams model tokens. Multi-agent responses are consolidated before
  display, by design.
- Nomic embeddings rerank lexical candidates on demand; the application does not maintain a persistent vector
  index or provide broad semantic search independent of lexical retrieval.
- Documentation is generated and persisted directly; an editable unsaved preview workflow and dedicated
  class/function/selected-file scopes are not currently provided.
- Active workflow recovery marks requests interrupted by backend shutdown as failed; it does not resume model work.
- Local model response quality and latency depend on the installed Ollama model and available hardware.

## AI configuration

AI inference uses local Ollama only. The supplied `backend\.env` and `backend\.env.example` use the installed
`qwen2.5-coder:3b` chat model and `nomic-embed-text:latest` embeddings. Restart the backend after changing settings.
Check the result at <http://localhost:8000/api/ai/status> (`?check=true` tests the local chat model) or on the Dashboard.

### Local model with Ollama

1. Install Ollama from <https://ollama.com>.
2. Start or reuse CODEMIND's separate Ollama server with
   `powershell -ExecutionPolicy Bypass -File backend\scripts\start_ollama.ps1`. It listens only on
   `127.0.0.1:11435`, verifies the owning process, and never starts, stops, or reconfigures the other
   server on `11434`.
3. Configure `backend\.env`:
   ```
   CODEMIND_AI_PROVIDER=ollama
   CODEMIND_AI_MODEL=qwen2.5-coder:3b
   CODEMIND_AI_EMBEDDING_MODEL=nomic-embed-text:latest
   CODEMIND_AI_ENDPOINT=http://127.0.0.1:11435
   ```
   Both local Ollama processes use the same per-user model store by default (`%USERPROFILE%\.ollama\models`),
   so existing model files are reused instead of downloaded a second time. No `OLLAMA_MODELS` override is set
   by the CODEMIND launcher. If a model is missing from 11435, the launcher reports it without downloading;
   in PowerShell, pull it explicitly to that server with
   `$env:OLLAMA_HOST='127.0.0.1:11435'; ollama pull qwen2.5-coder:3b` (repeat for the embedding model).
   This only changes the current PowerShell process. Small local models work best with
   `CODEMIND_AI_CONTEXT_CHARS=8000`.

No cloud model provider or remote Ollama endpoint is accepted. Chat prompts, retrieved code and embeddings stay on
the local Ollama service.

The frontend streams chat through `POST /api/repositories/{repo_id}/chat/stream` (server-sent events). The existing
`POST /api/repositories/{repo_id}/chat` endpoint remains available for non-streaming clients.

### Settings reference

| Variable | Meaning | Default |
| --- | --- | --- |
| `CODEMIND_AI_PROVIDER` | `ollama` or empty (no AI) | `ollama` in the supplied `.env` |
| `CODEMIND_AI_MODEL` | Local chat model | `qwen2.5-coder:3b` |
| `CODEMIND_AI_EMBEDDING_MODEL` | Local embedding model | `nomic-embed-text:latest` |
| `CODEMIND_AI_ENDPOINT` | CODEMIND's local Ollama endpoint (loopback only) | `http://127.0.0.1:11435` |
| `CODEMIND_AI_TIMEOUT` | Seconds to wait for the model | 120 |
| `CODEMIND_AI_MAX_TOKENS` | Longest answer | 1500 |
| `CODEMIND_AI_TEMPERATURE` | Sampling temperature | 0.2 |
| `CODEMIND_AI_CONTEXT_CHARS` | Repository text sent per question | 16000 |
| `CODEMIND_DB` | SQLite file | `backend\data\codemind.db` |
| `CODEMIND_EXCLUDES` | Extra scan exclusions (`.gitignore` syntax, comma separated) | – |
| `CODEMIND_CORS` | Allowed browser origins | `http://localhost:5173` |
| `VITE_API_URL` (frontend `.env`) | Backend address | `http://localhost:8000` |

## Tests and checks

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest          # backend tests

cd ..\agent_pro
npm test                                       # frontend tests (HTTP client, layout helpers)
npm run typecheck                              # TypeScript
npm run lint                                   # oxlint
npm run build                                  # type-check + production build
```

The backend tests use temporary repositories and isolated HTTP mocks, so the suite runs without Ollama. A separate
local integration check exercises the configured chat and embedding models.

## Troubleshooting

- **"Cannot reach the CODEMIND backend"** – the backend is not running (or not on port 8000). Start it with
  `scripts\start-backend.ps1` and check <http://localhost:8000/api/health>.
- **"Port ... is already in use"** – another application owns that port. Do not terminate an unrelated process.
  Choose free ports, e.g. `scripts\start-all.ps1 -BackendPort 8001 -FrontendPort 5176`; the script configures the
  matching backend URL and CORS origin for that process.
- **"That folder does not exist" / "Use an absolute path"** – enter the full path including the drive letter.
- **"No local AI model is configured"** – set the Ollama variables above and restart the backend.
- **"Cannot reach Ollama"** – start Ollama; **"model not found"** – run `ollama pull <model>`.
- **PowerShell refuses to run scripts** – use the `-ExecutionPolicy Bypass -File ...` form shown above.
- **The AI answer is slow** – local models on a laptop CPU can take a minute or more; raise
  `CODEMIND_AI_TIMEOUT` if needed or use a smaller model.

## Safety notes

- Repository files are only read; no repository code, script or build step is ever run.
- `.env`, key and credential files are listed but their contents are never read or sent anywhere.
  Obvious secrets inside code snippets are masked before they are shown to a model.
- Symbolic links are not followed and every file read is checked to stay inside the registered folder.
- AI inference is limited to Ollama endpoints on the local loopback interface.
- The backend only accepts browser requests from `localhost` origins and is meant for local use; there is no login.

## How the AI part works (short)

- A **LangGraph supervisor** routes each request to the relevant specialist: Repository Understanding, Code Analysis,
  Bug Investigation, Dependency Intelligence, Documentation or Code Recommendation. Clearly combined requests can
  run more than one agent; ordinary requests do not invoke every agent.
- Each agent collects evidence from the scanned repository. Retrieval selects candidates from the lexical index and,
  when the local embedding model is available, re-ranks them with `nomic-embed-text`; otherwise it remains lexical.
- The model only sees that evidence (marked as untrusted data), must cite it, and its references are checked: file
  references in the answer come only from real evidence, and citations or file paths that do not exist are flagged
  in the chat. If nothing relevant is found the model is not called at all.
- Bug investigation never changes your files. Confidence is capped by how strong the evidence is.

## Limitations

- The configured local Qwen chat model and Nomic embedding model were exercised through Ollama. Answer quality
  remains model-dependent; deterministic repository parsing and dependency analysis do not require Ollama.
- "Stop watching" on a running scan only hides the progress window; the backend finishes the scan on its own.

- Import classification (internal / external / standard library / unresolved) is static and best effort; packages
  installed in virtual environments or `node_modules` are not inspected.
- Module types in the architecture view (frontend, API, service, database) are guessed from folder names and
  detected frameworks.
- AI answers are only as good as the model you configure and the code snippets retrieved for the question; answers
  list the evidence they used so you can check them.
