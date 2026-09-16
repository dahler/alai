# ALAI — Testing Guide

> Last updated: 2026-09-16

---

## Table of Contents

1. [Running Tests](#running-tests)
2. [Router Classification Tests](#router-classification-tests)
3. [RAG Pipeline Tests](#rag-pipeline-tests)
4. [Query Rewriting Tests](#query-rewriting-tests)
5. [Chat & Streaming Tests](#chat--streaming-tests)
6. [Citation & Source Display Tests](#citation--source-display-tests)
7. [MCP Integration Tests](#mcp-integration-tests)
8. [Authentication Tests](#authentication-tests)
9. [Regression Checklist](#regression-checklist)
10. [How to Update Tests After a Change](#how-to-update-tests-after-a-change)

---

## Running Tests

### Pre-push check (run this before every push)

Single script that runs all automated checks:

```powershell
.\scripts\check.ps1
```

What it runs:
1. **Backend router tests** — `backend\test_router.py` (31 cases, no server needed)
2. **Frontend build** — `tsc && vite build` (catches TypeScript errors and broken imports)
3. **Backend import check** — `backend\scripts\import_check.py` (catches syntax errors and circular imports)

Expected output ends with:
```
ALL CHECKS PASSED -- safe to push
```

If any step fails, the script exits with code 1 and lists what failed.

### Individual checks

```powershell
# Router tests only
cd backend
.\venv\Scripts\python.exe test_router.py

# Frontend build only
cd frontend
npm run build

# Backend imports only
cd backend
.\venv\Scripts\python.exe scripts\import_check.py
```

### RAG quality test (requires running backend + Ollama)

```powershell
.\backend\venv\Scripts\python.exe test_rag_claude.py `
    --api-url http://localhost:8000 `
    --api-key <RAG_API_KEY>
```

### Backend health check

```powershell
curl http://localhost:8000/health
# Expected: {"status": "ok", "ollama": true, "db": true}
```

### Start backend (development)

```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
```

> **Warning:** Never use `python` or `Python311\python.exe` — causes 22 GB
> memory spike from global sentence-transformers installation.

---

## Router Classification Tests

**File:** `backend/test_router.py`

Tests the hard-coded bypass rules without needing a live model. The
LLM-based context-aware path requires a live server and is covered by
the manual scenarios below.

### Automated cases (31 total)

| Category | Examples | Expected |
|----------|---------|---------|
| Edit prefix bypass | "fix this sentence: ...", "translate this:" | `direct_answer` |
| Edit prefix bypass (capitalised) | "Fix this:", "Please fix..." | `direct_answer` |
| Indonesian edit bypass | "perbaiki kalimat ini:", "terjemahkan ke bahasa inggris" | `direct_answer` |
| Greeting bypass | "hi", "thanks!", "selamat pagi" | `direct_answer` |
| Must reach LLM | "what is the SOP?", "who approves procurement?" | `None` (LLM) |
| Ambiguous plain text | "In connection with PT Antara..." | `None` (LLM + context) |
| Context block format | History with edit turn → block contains "User: fix..." | contains substring |

### Manual scenario: Editing session continuity

1. Start a new conversation
2. Send: `"fix this sentence: We hereby gives notice and warning"`
3. Verify: Response is a corrected sentence (no RAG sources shown)
4. Send: `"this is a legal document"`
5. Verify: Response acknowledges context (no RAG)
6. Send: `"The termination of the Agreement shall not waive payment obligations."`
7. **Expected:** System fixes/improves the pasted sentence — does NOT search RAG
8. Check server logs: should show `[ROUTER] DIRECT (text-editing bypass)` or
   `action=direct_answer ... reason=...`

### Manual scenario: Topic switch resets editing context

1. Continue the editing session above (after step 7)
2. Send: `"what is the SOP for updating the company website?"`
3. **Expected:** RAG search runs, sources appear at bottom
4. Check logs: `action=rag_search`

### Manual scenario: Plain text without edit history

1. Start a fresh conversation (no editing history)
2. Send: `"The termination of the Agreement shall not waive payment."`
3. **Expected:** LLM handles it generically (may ask what you want to do)
4. No RAG sources should appear (it's a pasted legal sentence, not a question)

---

## RAG Pipeline Tests

### Upload and retrieval test

1. Upload a PDF document via Documents page
2. Wait for processing status to show "embedded"
3. Open a new chat, ask a question about content in that document
4. **Expected:**
   - Sources section appears at bottom of response
   - Numbered citations [1], [2] appear inline in the text
   - Clicking a citation opens the DocumentViewerModal
   - The cited passage panel shows the actual text from the document

### Source citation accuracy test

1. Upload `002-SKEP-SM-PRODUCT-XI-2023_SOP_Pembaruan_Situs_Web_Antara_ETP.pdf`
2. Ask: `"what is the procedure for updating the Antara ETP website?"`
3. **Expected:**
   - Document appears in sources
   - Answer describes the actual SOP steps
   - If chunks are empty (scanned PDF), open citation modal and check chunk text

> **Known issue:** Scanned PDFs without OCR produce empty chunks. Re-upload
> with OCR-processed PDF if this occurs.

### Query rewriting test

Watch the backend logs when sending a RAG question:

```
[CHAT] Original query : update website
[CHAT] Rewritten query: Standar Operasional Prosedur pembaruan situs web Antara ETP
```

The rewritten query should be more descriptive than the original. If both
lines are identical, `rewrite_query()` returned the original (either the model
produced empty output or > 300 chars).

### Context cap test

1. Upload a very large document (> 100 pages)
2. Ask a question about it
3. Check logs for: `Context too large (...) — extracting relevant sections`
4. **Expected:** Response still generated (focused extraction kicked in)

---

## Query Rewriting Tests

### Rewrite expansion test

Send these queries and check backend logs for `Rewritten query:`:

| Original | Expected rewrite direction |
|---------|--------------------------|
| `"SOP website"` | Expands to full Indonesian term |
| `"limit pengadaan"` | Adds "batas", "ambang", "threshold" synonyms |
| `"who PIC project X"` | Expands PIC to "Person In Charge / penanggung jawab" |
| `"hello"` | Should NOT be rewritten (greeting bypass fires first) |
| `"fix this sentence: ..."` | Should NOT be rewritten (edit bypass fires first) |

### History context test

1. Ask: `"what is the SOP?"`
2. Then ask: `"what about step 3?"`
3. Check logs — rewritten query should expand "step 3" using the SOP context
   from the previous turn (not just "step 3" verbatim)

---

## Chat & Streaming Tests

### Basic streaming test

1. Send any message
2. **Expected:** Text appears character by character (streaming)
3. Input field is disabled while streaming
4. Scroll position follows new text

### Long response test

1. Ask: `"explain the entire procurement SOP in detail"`
2. **Expected:** No timeout, full response arrives, no truncation

### Image attachment test

1. Attach a PNG/JPG image and send with the message
2. **Expected:**
   - Router logs: `VISION (image attached)`
   - Model used: `qwen2.5vl`
   - Response describes/analyzes the image

### Document attachment test

1. Attach a PDF (< 50 pages) and ask a question about it
2. **Expected:**
   - Document text included in context
   - Response references document content directly
   - No RAG sources shown (attachment path, not KB path)

### Multi-turn context test

1. Ask: `"My name is Ahmad"`
2. Ask: `"What is my name?"`
3. **Expected:** "Ahmad" (from conversation history, last 6 messages)
4. Ask 7+ more messages, then: `"What is my name?"`
5. **Expected:** May not remember (older than 6-message window)

---

## Citation & Source Display Tests

### Citation rendering test

1. Enable RAG (upload a document)
2. Ask a question that retrieves sources
3. **Expected in response:**
   - Inline amber superscript badges: [1], [2]
   - "Sources" section at bottom with filenames
   - Each source has a document icon + filename

### Document viewer modal test

1. Click any source number in the Sources section
2. **Expected:**
   - Modal opens with amber "Cited passage" panel at top
   - Full chunk list shown below
   - The cited chunk is highlighted with amber left border
   - Other chunks listed for context

### Code block test

1. Ask: `"write a Python hello world"`
2. **Expected:**
   - Code block has language label ("python") in header bar
   - "Copy" button in header
   - `oneLight` theme (light background)
   - Clicking Copy copies code to clipboard

---

## MCP Integration Tests

### OAuth discovery test

```powershell
curl https://mcp-alai.antaragpt.com/.well-known/oauth-authorization-server
```

**Expected:** JSON with `issuer`, `authorization_endpoint`, `token_endpoint`,
`registration_endpoint`.

### Claude.ai connection test

1. Open Claude.ai → Settings → Integrations → Add MCP Server
2. Enter URL: `https://mcp-alai.antaragpt.com`
3. **Expected:** OAuth flow completes, tool `search_documents` appears
4. Ask Claude: `"use my ALAI knowledge base to find SOP for website updates"`
5. **Expected:** Tool call appears in Claude's response, returns RAG results

### RAG API key test

```powershell
curl -X POST https://api-alai.antaragpt.com/api/rag/query `
     -H "Authorization: Bearer <RAG_API_KEY>" `
     -H "Content-Type: application/json" `
     -d '{"query": "what is the SOP for website updates?", "top_k": 3}'
```

**Expected:** JSON with `answer`, `sources[]`, `chunks[]`

---

## Authentication Tests

### Microsoft OAuth test

1. Open app in incognito window
2. Click Login → redirects to Microsoft
3. Complete Microsoft login
4. **Expected:** Redirected back, logged in, conversations list loads

### Anonymous session test

1. Open app without logging in
2. Send a chat message
3. **Expected:** Message works, conversation saved to anonymous session
4. Refresh page → conversation still accessible (session ID in localStorage)
5. Login → anonymous conversations not merged (expected behavior)

### JWT expiry test

1. Login and note the token expiry (default 7 days)
2. Manually expire token (change system clock or wait)
3. **Expected:** 401 error, redirect to login page

---

## Regression Checklist

**Run `.\scripts\check.ps1` before every push.** It covers steps 1-3 automatically.

### Automated (covered by check.ps1)
- [ ] `scripts\check.ps1` exits 0 — all 3 checks green
- [ ] Router bypass tests: 31/31 pass
- [ ] Frontend build: `tsc && vite build` succeeds with no errors
- [ ] Backend imports: all key modules load without errors

### Router (manual)
- [ ] "fix this sentence: ..." → `direct_answer`, no RAG sources
- [ ] "what is the SOP?" → `rag_search`, sources appear
- [ ] Editing session (3+ turns) then SOP question → switches to `rag_search`

### RAG
- [ ] Upload PDF → status shows "embedded"
- [ ] Ask question about document → correct sources cited
- [ ] Backend logs show `Rewritten query:` line
- [ ] `Original query` and `Rewritten query` logged separately

### Chat
- [ ] Streaming works (text appears progressively)
- [ ] Last 6 messages used as context (not more, not less)
- [ ] Title generated in English or Bahasa Indonesia (not German, French, etc.)
- [ ] Image upload → `qwen2.5vl` model used (check logs)

### UI
- [ ] Warm cream theme (no dark backgrounds)
- [ ] Citation badges appear as amber superscripts
- [ ] Document viewer modal opens on source click
- [ ] Code blocks have copy button

### Deployment
- [ ] Push to `legal-ize` remote (not just `origin`)
- [ ] K8s pod restarts and comes back healthy
- [ ] `curl https://api-alai.antaragpt.com/health` returns 200

---

## How to Update Tests After a Change

1. **Router logic change** → update `_EDIT_PREFIXES`, `_GREETINGS`, or prompt
   in `service.py`, then add the new case to `BYPASS_CASES` or
   `CONTEXT_BLOCK_CASES` in `test_router.py` and re-run.

2. **New API endpoint** → add a manual scenario in the relevant section above
   with exact request and expected response.

3. **RAG retrieval change** → add a query to the Query Rewriting Tests section
   with the expected rewrite direction.

4. **UI change** → add a step to the relevant UI test section describing what
   to click and what to see.

5. **After adding tests:** run `test_router.py`, verify pass count in the
   header of this file, and update `docs/CHANGELOG.md` with what changed.
