# ALAI — Changelog

> Format: newest first. Each entry includes what changed, why, and which files.

---

## 2026-09-16

### feat: Context-aware routing via LLM with conversation history

**Why:** The router previously used heuristics (prefix matching on the last
3 user messages) to detect editing intent continuity. This broke when the
user switched topics — e.g., asking an SOP question after several editing
turns, or when a context statement appeared between edit requests.

**What changed:** The last 4 conversation turns are now injected directly
into the SmartLLM router prompt. The LLM reads the full context and decides
whether the current message is:
- Continuing an editing session → `direct_answer`
- A new SOP/policy question → `rag_search`
- A general question → `direct_answer`

**Files changed:**
- `backend/app/router/service.py` — Added `_build_context_block()`,
  updated `_PROMPT` with `{context_block}` section, removed heuristic
  context-inheritance bypass block
- `backend/test_router.py` — Updated tests to reflect new design

---

### fix: Router scans last 3 user turns for editing intent (superseded above)

**Why:** Previous version only checked the immediately preceding user message.
If user said "this is legal document" between two editing requests, intent
was lost. Fixed to scan last 3 user messages — then replaced entirely by
the LLM-context approach above.

---

### feat: Router bypasses RAG for text-editing tasks

**Why:** "Fix this sentence: ..." was being classified as `rag_search` (85%
confidence) because the router's LLM saw a KB was present and defaulted to
searching it. Text editing never needs company documents.

**What changed:**
- Added `_EDIT_PREFIXES` tuple with 25+ editing keywords
- Hard-coded bypass in `RouterService.classify()` — no LLM call needed
- Added Step 2a to LLM prompt explaining editing is always `direct_answer`
- Added `_QUESTION_WORDS` tuple for context-aware checks

**Files changed:**
- `backend/app/router/service.py`
- `backend/test_router.py` (new file)

---

### fix: Message objects not serializable in rewrite_query

**Why:** `msg_service.get_recent_context()` returns SQLAlchemy `Message` ORM
objects. The `rewrite_query()` method called `m.get("content")` which only
works on dicts, causing `AttributeError`.

**Root cause:** `list(prev_history)` preserved ORM objects instead of
converting them.

**Fix:** Explicit dict conversion before passing to `rewrite_query()`:
```python
context_for_rewrite = [
    {"role": m.role, "content": m.content} for m in prev_history
] + [{"role": "user", "content": data.content}]
```

**Files changed:**
- `backend/app/routers/messages.py` (line ~501)

---

### feat: Query rewriting (agentic RAG Option 1)

**Why:** User queries like "update website" would miss the correct document
because the vector search needed expanded terms. Query rewriting lets the
LLM expand abbreviations, add synonyms, and produce richer search queries
before hitting the vector store.

**What changed:**
- `AIService.rewrite_query(query, history)` — new method using LLM to
  produce ONE improved search query (max 25 words, Bahasa Indonesia/English)
- `messages.py` — query rewriting called before RAG block; both KG hybrid
  search and plain RAG search now use `search_query` instead of `data.content`
- Recent history loaded once (`pre_history_dicts`) and reused for both
  routing context and query rewriting — avoids double DB call
- `AIService.generate_title()` — locked to English/Bahasa Indonesia only
  (previously matched user language, causing German titles for "hello")

**Files changed:**
- `backend/app/services/ai.py`
- `backend/app/routers/messages.py`

---

### fix: Backend Starlette version conflict

**Why:** MCP SDK upgraded Starlette to 1.6.0, which is incompatible with
FastAPI 0.109.2 (`Router.__init__() got an unexpected keyword argument 'on_startup'`).

**Fix:** Pin Starlette to compatible version:
```
pip install "starlette==0.36.3"
```

**Important:** Always start backend with venv Python:
```
backend\venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
```
Using system Python311 causes a ~22 GB memory spike (sentence-transformers
loads global ML weights).

---

### feat: MCP OAuth 2.0 support

**Why:** Claude.ai requires OAuth 2.0 with dynamic client registration
(RFC 7591), PKCE (RFC 7636), and authorization-code flow for remote MCP
servers. The original server had no OAuth endpoints.

**What changed:** Complete rewrite of `mcp_server/main.py`:
- `InMemoryOAuthProvider` — auto-approves every `/authorize` request
- `MCPServer` instantiated with `auth_server_provider` + `AuthSettings`
- SDK auto-mounts: `/.well-known/oauth-authorization-server`, `/register`,
  `/authorize`, `/token`, `/revoke`

**Files changed:**
- `mcp_server/main.py`

---

### feat: Soft warm cream UI theme

**Why:** User requested removal of dark background in favor of a warm,
readable theme suitable for document work.

**Color tokens:**
```css
--dark-bg:      #faf8f5   (page background)
--dark-sidebar: #f0ece6   (sidebar)
--dark-chat:    #e8e0d8   (chat area)
--dark-input:   #faf8f5   (input field)
--dark-hover:   #b45309   (amber accent)
--dark-text:    #292524   (dark brown text)
--dark-muted:   #78716c   (secondary text)
```

**Files changed:**
- `frontend/src/index.css` — CSS custom properties
- `frontend/tailwind.config.js` — Tailwind color tokens + glow shadows
- `frontend/src/components/Sidebar.tsx` — amber gradient
- `frontend/src/pages/Home.tsx`, `Login.tsx` — amber gradient
- `frontend/src/pages/Documents.tsx` — amber badges
- `frontend/src/pages/DocumentGraph.tsx` — amber node colors
- `frontend/src/pages/KnowledgeGraph.tsx` — amber node colors

---

### feat: Improved citation display and document viewer

**Why:** User requested better citation UI — clearer source references and
a richer modal for viewing cited document passages.

**What changed:**
- `CiteBadge` — amber superscript style `[1]`
- Sources section — full-width list with doc icon + filename
- `DocumentViewerModal` — amber "Cited passage" panel + full chunk list
- Code blocks — `oneLight` theme with language label + Copy button
- Inline code — amber tint (`bg-amber-50 border border-amber-200`)
- Tables — rounded border with styled headers

**Files changed:**
- `frontend/src/components/chat/ChatMessage.tsx`

---

## Ongoing conventions

### Git remotes
- `origin` → `github.com/dahler/alai` (mirror, not CI/CD)
- `legal-ize` → `git.legal-ize.com/internal/alai` (CI/CD watches this)

Always push to both:
```
git push origin master
git push legal-ize master
```

### Conversation history limits
- Router context: last 4 messages (injected into LLM prompt)
- LLM answer context: last 6 messages (`get_recent_context(limit=6)`)
- Query rewriting context: last 6 messages (reused from above)
- RAG context hard cap: 24 000 characters

### Title generation
Titles are always in **English or Bahasa Indonesia** regardless of the
user's message language. The LLM prompt explicitly forbids other languages.
