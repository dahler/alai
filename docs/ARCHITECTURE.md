# ALAI — Architecture Reference

> Last updated: 2026-09-16

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Service Map](#service-map)
3. [Request Lifecycle](#request-lifecycle)
4. [Backend Components](#backend-components)
   - [Router Service](#router-service)
   - [RAG Pipeline](#rag-pipeline)
   - [Knowledge Graph](#knowledge-graph)
   - [Agent System](#agent-system)
   - [SmartLLM](#smartllm)
   - [AI Service & Ollama Client](#ai-service--ollama-client)
5. [Database Schema](#database-schema)
6. [Frontend Architecture](#frontend-architecture)
7. [MCP Server](#mcp-server)
8. [Model Strategy](#model-strategy)
9. [Authentication](#authentication)
10. [Deployment](#deployment)

---

## System Overview

ALAI is an enterprise AI assistant built on local Ollama models with optional
cloud LLM fallback. It provides:

- **Chat** — streaming conversation with context memory
- **RAG** — question-answering grounded in uploaded company documents
- **Knowledge Graph** — entity/relationship extraction and hybrid retrieval
- **Agent** — tool-using AI (web search, finance, file generation, email)
- **MCP** — Claude.ai integration via Model Context Protocol

```
Browser / Claude.ai
      │
      ▼
   Nginx  (reverse proxy)
      │
      ├──► Frontend  (React + Vite)
      │
      └──► Backend  (FastAPI)
                │
                ├── PostgreSQL + pgvector  (data + embeddings)
                ├── Ollama  (local LLMs on Mac Mini)
                ├── Anthropic / OpenAI  (optional cloud LLMs)
                └── Docling Server  (document parsing on Mac Mini)

   MCP Server  (FastAPI, port 8001)
      │
      └──► Backend /api/rag/query  (RAG bridge for Claude.ai)
```

---

## Service Map

| Service | Technology | Port | Purpose |
|---------|-----------|------|---------|
| Frontend | React 18 + Vite + TailwindCSS | 3000 | Chat UI, document manager, graph viewer |
| Backend | FastAPI + SQLAlchemy (async) | 8000 | API, RAG, agent, auth |
| MCP Server | FastAPI + MCP SDK 2.x | 8001 | Claude.ai OAuth + RAG bridge |
| PostgreSQL | Postgres 15 + pgvector | 5432 | Data store + vector index |
| Docling | Python HTTP server | 5001 | PDF/DOCX parsing (Mac Mini) |
| Ollama | llama.cpp HTTP | 11434 | Local LLM inference (Mac Mini) |
| Nginx | Nginx | 80/443 | TLS termination, reverse proxy |

---

## Request Lifecycle

Every chat message goes through this pipeline:

```
1. Frontend  →  POST /api/conversations/{id}/messages/stream

2. Backend middleware
   └── JWT / anonymous session auth

3. Attachment processing (if files attached)
   ├── Image → extract to image_paths
   ├── Small doc (<12 000 chars) → full text in document_contents
   └── Large doc → chunked into AttachmentChunk rows

4. Auto-reuse last chunked attachment (if no new file)

5. KB check  →  has_knowledge_base = (DocumentChunk count > 0)

6. Load recent history (last 6 messages) for routing + query rewriting

7. Language detection + RouterService.classify()
   ├── Hard bypass: images → VISION
   ├── Hard bypass: edit prefix → DIRECT_ANSWER
   ├── Hard bypass: greeting → DIRECT_ANSWER
   └── SmartLLM prompt (with last 4 turns context) → direct_answer | rag_search | agentic

8. Branch on router decision:
   ├── rag_search
   │   ├── rewrite_query() — LLM expands query for better retrieval
   │   ├── KG enabled: KnowledgeGraphService.hybrid_search()
   │   └── KG disabled: RAGService.search()
   ├── agentic  →  AgentPipeline.execute()
   └── direct_answer / vision  →  skip to step 9

9. Save user message to DB

10. Load last 6 messages as LLM context

11. Build prompt:
    ├── System prompt (ALAI persona)
    ├── Optional: RAG context block ([1] filename\n\nchunk_text)
    ├── Optional: attachment document text
    └── Conversation history (last 6 messages)

12. AIService.generate_response_stream()
    └── OllamaClient.chat_stream() → SSE chunks to frontend

13. Accumulate full response, save assistant message to DB

14. Generate conversation title (first message only)
```

---

## Backend Components

### Router Service

**File:** `backend/app/router/service.py`

Classifies every incoming message into one of three actions:

| Action | Meaning |
|--------|---------|
| `direct_answer` | General knowledge, text editing, greetings |
| `rag_search` | Search internal company documents |
| `agentic` | Requires tools (files, live data, email) |

**Decision flow:**

```
1. Image attached?             → VISION_ANALYSIS (hard bypass)
2. Clear edit prefix?          → DIRECT_ANSWER (hard bypass, zero latency)
   (fix, translate, rewrite, perbaiki, terjemahkan, …)
3. One-word greeting?          → DIRECT_ANSWER (hard bypass)
4. SmartLLM with context       → LLM reads last 4 conversation turns
                                  and decides, handling:
                                  - Editing session continuity
                                  - Topic switches mid-conversation
                                  - Ambiguous plain-text messages
```

**Context injection** (key feature — see CHANGELOG):
The last 4 messages are injected into the LLM router prompt so it can
detect when a user is continuing an editing session vs. starting a new
RAG query, even without explicit keywords.

**Safety overrides:**
- `agentic` with confidence < 85% + KB present → downgrade to `rag_search`
- `rag_search` with confidence < 88% + attachment present → downgrade to `direct_answer`

---

### RAG Pipeline

**Files:** `backend/app/services/rag.py`, `backend/app/services/embedding.py`,
`backend/app/services/docling_service.py`

#### Ingestion

```
Document upload
    │
    ▼
DoclingService.parse()
    ├── Remote: POST http://mac-mini:5001/parse  (Docling PDF parser)
    └── Fallback: PyMuPDF (local)
    │
    ▼
Structure extraction
    ├── DocumentSection rows (hierarchical, with headings)
    └── DocumentChunk rows (800-token chunks, overlap 100)
    │
    ▼
EmbeddingService.embed_texts()  (bge-m3, 1024-dim via Ollama)
    ├── Chunk embeddings → stored in DocumentChunk.embedding
    └── Section summary embeddings → DocumentSection.summary_embedding
    │
    ▼
pgvector IVFFlat index (lists=100)
```

#### Retrieval (query time)

```
Query (rewritten by LLM)
    │
    ▼
Section-first filter
    └── Find top sections by summary_embedding cosine similarity
    │
    ▼
Chunk vector search (pgvector <=> operator)
    └── Filter to chunks within matched sections
    │
    ▼
BM25 re-ranking (rank_bm25)
    │
    ▼
Context expansion
    └── Load sibling chunks for continuity
    │
    ▼
Hard cap: 24 000 chars total context
```

#### Query Rewriting (agentic RAG)

Before hitting the vector store, the LLM rewrites the user's question
into richer search terms:

```python
# ai.py → rewrite_query()
"Expand abbreviations, add synonyms, write in Bahasa Indonesia or English.
 Output ONE improved search query (max 25 words)."
```

The rewritten query is used **only for retrieval** — the original question
is still sent to the LLM for generating the answer.

---

### Knowledge Graph

**Files:** `backend/app/services/knowledge_graph.py`,
`backend/app/services/entity_extraction.py`,
`backend/app/services/relationship_extraction.py`,
`backend/app/services/graph_retrieval.py`

#### Graph Structure

```
Entity  ──[relation]──►  Entity
  │                         │
  └── linked to DocumentChunk(s)
```

Entity types: Person, Organization, Location, Regulation, Product, Date, Amount, etc.

#### Ingestion

```
DocumentChunks
    │
    ▼
EntityExtractionService (SmartLLM)
    └── Extract: name, type, aliases, description
    │
    ▼
RelationshipExtractionService (SmartLLM)
    └── Extract: (source, relation, target) triples with confidence
    │
    ▼
GraphLinkingService
    └── Deduplicate and link to existing entities
```

#### Hybrid Retrieval

```
Query
    │
    ├── Vector search on EntityEmbeddings     (who/what it mentions)
    ├── Graph traversal (1-hop relationships) (what it connects to)
    └── Chunk vector search                   (where it appears)
    │
    ▼
Merge + rerank → SearchResult[]
    (vector_score, graph_score, source, matched_entities, relationships)
```

---

### Agent System

**Files:** `backend/app/agent/pipeline.py`, `backend/app/agent/loop.py`,
`backend/app/agent/executor.py`, `backend/app/agent/tools.py`

10-stage pipeline:

```
1. Language detection
2. Intent analysis (SmartLLM)
3. Context gathering
4. Planner (SmartLLM → structured tool plan)
5. Tool execution (ToolExecutor with timeout/sandbox)
6. Evidence merging
7. Reflection (SmartLLM validates plan vs. results)
8. Response generation (Ollama main model)
9. Citation formatting
10. Output rendering
```

**Available tools:**

| Tool | Description |
|------|-------------|
| `rag_search` | Search company knowledge base |
| `web_search` | Tavily web search |
| `yahoo_finance` | Stock quotes, financial data |
| `send_email` | Send email via SMTP |
| `read_email` | Read inbox |
| `generate_excel` | Create .xlsx reports |
| `generate_word` | Create .docx documents |
| `generate_pdf` | Create PDF reports |
| `generate_pptx` | Create PowerPoint decks |

---

### SmartLLM

**File:** `backend/app/services/smart_llm.py`

Provider-agnostic LLM client used for internal tasks (routing, planning,
entity extraction). Automatically selects the best available provider:

```
Priority:  Claude Haiku (Anthropic API)
           ↓ if ANTHROPIC_API_KEY not set
           GPT (OpenAI API)
           ↓ if OPENAI_API_KEY not set
           Ollama qwen2.5:14b  (always available, local, free)
```

Used by: RouterService, AgentPipeline, EntityExtractionService,
RelationshipExtractionService, AIService.rewrite_query()

**Not used for:** generating the final user-facing answer (that's AIService).

---

### AI Service & Ollama Client

**Files:** `backend/app/services/ai.py`, `backend/app/ai/ollama.py`

Model selection at inference time:

| Condition | Model |
|-----------|-------|
| Text chat (default) | `gemma3:4b` (OLLAMA_TEXT_MODEL) |
| Image in message | `qwen2.5vl` (OLLAMA_VISION_MODEL) |
| use_agent_model=True | `qwen2.5:14b` (OLLAMA_AGENT_MODEL) |

Key methods:
- `generate_response()` — non-streaming, returns full string
- `generate_response_stream()` — async generator, yields chunks
- `rewrite_query(query, history)` — LLM expands query for RAG retrieval
- `generate_title(first_message)` — short conversation title (English/Bahasa only)
- `check_health()` — ping Ollama

---

## Database Schema

### Core Tables

```
users
├── id, email (unique), name, avatar_url, is_admin
└── → conversations, attachments, document_chunks, report_templates

conversations
├── id, title, user_id (FK→users), anonymous_session_id
└── → messages[]

messages
├── id, conversation_id (FK), role (user|assistant|system)
├── content (Text), sources (JSON)
└── → attachments[]

attachments
├── id, message_id (FK), user_id (FK), folder_id (FK)
├── filename, original_filename, file_path, content_type, file_size
├── is_company_doc, is_embedded, graph_status, processing_status
└── → chunks[], sections[], summaries[]
```

### RAG Tables

```
document_chunks
├── id, attachment_id (FK), section_id (FK), user_id (FK)
├── chunk_index, chunk_text (Text), heading_context
├── page_start, page_end, token_count, is_company_doc
└── embedding  vector(1024)  ← IVFFlat index

document_sections
├── id, attachment_id (FK), parent_section_id (FK, self-ref)
├── title, level, section_index, content, page_start, page_end
├── summary (optional)
└── summary_embedding  vector(1024)  ← IVFFlat index
```

### Knowledge Graph Tables

```
entities
├── id, name, normalized_name (indexed), entity_type (indexed)
├── description, aliases, mention_count
└── embedding  vector(1024)  (optional)

entity_relationships
├── id, source_entity_id (FK), relation_type, target_entity_id (FK)
├── confidence (float), source_document_id, source_chunk_id
└── context (Text, optional)

document_entities
├── id, document_id (FK), entity_id (FK), chunk_id (FK, optional)
└── mention_count, confidence
```

### Auth & Config Tables

```
oauth_accounts
└── user_id, provider, provider_user_id, access_token, refresh_token

report_templates
└── name, format (pdf|docx|xlsx|pptx), sections_json, owner_id, is_company_wide

document_folders
└── name, user_id, is_company_folder
```

---

## Frontend Architecture

```
App.tsx
├── MainLayout (sidebar + router outlet)
│   ├── Sidebar.tsx          — conversation list, navigation
│   └── Pages:
│       ├── Chat.tsx          — main chat interface
│       │   ├── ChatWindow    — message list
│       │   ├── ChatMessage   — renders markdown, citations, sources
│       │   │   ├── CiteBadge         — amber superscript [1]
│       │   │   ├── DocumentViewerModal — cited passage + chunk viewer
│       │   │   └── Code blocks, tables, inline code
│       │   └── ChatInput     — text input + file upload
│       ├── Documents.tsx     — upload, list, manage documents
│       ├── KnowledgeGraph.tsx — entity/relationship visualization (D3/Force)
│       ├── DocumentGraph.tsx  — document connection graph
│       ├── Files.tsx          — file browser
│       └── Templates.tsx      — report template editor
```

**State management:** Zustand stores (authStore, chatStore, conversationStore)

**Streaming:** Native `fetch` with `ReadableStream` for SSE message chunks

**Theme:** Soft warm cream — CSS custom properties on `:root`:
```css
--dark-bg: #faf8f5   --dark-sidebar: #f0ece6   --dark-chat: #e8e0d8
--dark-text: #292524  --dark-muted: #78716c    --dark-hover: #b45309
```
Accent color: amber (`#b45309` / `#d97706`) replacing original purple.

---

## MCP Server

**File:** `mcp_server/main.py`

Enables Claude.ai to use ALAI as a remote MCP tool.

**OAuth 2.0 flow:**
```
Claude.ai  →  GET /.well-known/oauth-authorization-server
           →  POST /register       (dynamic client registration, RFC 7591)
           →  GET  /authorize      (auto-approved, no login UI)
           →  POST /token          (auth code exchange)
           →  POST /messages/      (tool call with Bearer token)
```

**InMemoryOAuthProvider:** Auto-approves every authorization request.
Suitable for internal corporate tools where all users are trusted.

**Tool exposed:** `search_documents(query: str)` — calls backend
`/api/rag/query` with the `RAG_API_KEY` Bearer token.

---

## Model Strategy

| Use case | Model | Provider | Notes |
|----------|-------|----------|-------|
| Chat (text) | `gemma3:4b` | Ollama | Primary chat model |
| Chat (image) | `qwen2.5vl` | Ollama | Vision-capable |
| Agent reasoning | `qwen2.5:14b` | Ollama | Complex multi-step |
| Router | `gemma3:1b` | Ollama | Fast, lightweight |
| SmartLLM | Claude Haiku | Anthropic | If API key set |
| SmartLLM fallback | GPT | OpenAI | If API key set |
| SmartLLM fallback | `qwen2.5:14b` | Ollama | Always available |
| Embeddings | `bge-m3` (1024-dim) | Ollama | RAG + KG |

---

## Authentication

**JWT-based with Microsoft OAuth 2.0:**

```
1. GET /api/auth/login          → redirect to Microsoft login
2. GET /api/auth/callback?code= → exchange code for tokens
                                  → create/update User row
                                  → create OAuthAccount row
                                  → return JWT (access_token)
3. All API requests             → Authorization: Bearer <jwt>
4. Anonymous users              → X-Session-ID: <uuid> header
                                  (stored in localStorage)
```

JWT payload: `{ sub: user_id, email, exp }`

Anonymous sessions can access conversations but cannot upload to
the company knowledge base.

---

## Deployment

**Docker Compose (local/staging):**
```yaml
services:
  db:       postgres:15 + pgvector
  backend:  FastAPI (port 8000)
  mcp:      MCP server (port 8001)
  frontend: React dev server (port 3000)
  nginx:    reverse proxy (port 80)
```

**Kubernetes (production):**
- Deployments: `alai-backend`, `alai-mcp`, `alai-frontend`
- ConfigMaps for env vars
- Secrets for `RAG_API_KEY`, `SECRET_KEY`, `ANTHROPIC_API_KEY`

**CI/CD:** Gitea Actions on `git.legal-ize.com/internal/alai`
- Push to `master` → build Docker image → deploy to K8s
- GitHub (`github.com/dahler/alai`) is a mirror — CI/CD does NOT watch it

**Environment variables (key ones):**
```
DATABASE_URL          postgresql+asyncpg://...
SECRET_KEY            JWT signing secret
OLLAMA_BASE_URL       http://mac-mini:11434
OLLAMA_TEXT_MODEL     gemma3:4b
OLLAMA_VISION_MODEL   qwen2.5vl
OLLAMA_AGENT_MODEL    qwen2.5:14b
OLLAMA_ROUTER_MODEL   gemma3:1b
RAG_API_KEY           Bearer token for /api/rag/query
ANTHROPIC_API_KEY     (optional) enables Claude as SmartLLM
OPENAI_API_KEY        (optional) enables GPT as SmartLLM fallback
DOCLING_BASE_URL      http://mac-mini:5001
```
