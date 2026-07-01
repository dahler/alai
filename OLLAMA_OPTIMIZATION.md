# Ollama Inference Optimization — ALAI Backend

**Target hardware:** Mac mini M4 Pro, 24 GB unified memory
**Ollama server:** `http://192.168.23.20:11434`
**Date:** 2026-07-01

This document explains why inference is currently slow and lists concrete
fixes, ordered by impact. All numbers below were measured directly against
the running server.

---

## Configured models

| Role | Setting | Model | Size (Q4) | Notes |
|---|---|---|---|---|
| Chat / text | `OLLAMA_TEXT_MODEL` | `gemma3:4b` | 3.34 GB | non-reasoning |
| Vision | `OLLAMA_VISION_MODEL` | `qwen2.5vl:7b` | 5.97 GB | images only |
| Router | `OLLAMA_ROUTER_MODEL` | `gemma3:1b` | 0.82 GB | **defined but never used** |
| Agent / planner | `OLLAMA_AGENT_MODEL` | `qwen3:8b` | 5.23 GB | **reasoning model** |
| Embeddings | `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | 0.27 GB | 768-dim |

---

## How models are used today

Every user message flows through:

```
RouterService.classify()      → SmartLLM
pipeline.py: intent analysis  → SmartLLM
pipeline.py: planner          → SmartLLM
loop.py: tool detection       → AIService (use_agent_model=True)
loop.py: report/file content  → SmartLLM (num_predict up to 8192)
final answer render           → AIService
```

`SmartLLM` defaults to `OLLAMA_AGENT_MODEL` (`qwen3:8b`) whenever no model is
passed. **Almost every stage above therefore runs the 8B model.** A single
agentic request fires `qwen3:8b` 3–5 times **sequentially** before the user
sees an answer.

---

## Root causes (measured)

### 1. `qwen3:8b` "thinks" on every call — and the thinking is discarded

`qwen3` is a reasoning model. `app/ai/ollama.py` explicitly sets
`think: True` for it, and even `SmartLLM` (which omits the parameter) still
gets thinking because **Ollama enables it by default for qwen3**.

| Call | Time | Detail |
|---|---|---|
| qwen3:8b, trivial prompt, **think ON** | **7.16 s** | 294 gen tokens, 948 thinking chars |
| qwen3:8b, same prompt, **think OFF** | **1.57 s** | 65 tokens — **4.5× faster** |
| qwen3:8b routing classify (SmartLLM-style, no think param) | **5.68 s** | 518 thinking chars for a one-line JSON answer |

Per-token speed is identical (~41 tok/s) with or without thinking — thinking
just generates a large pile of **extra tokens that are then thrown away**.

Worse: in `chat_stream`, the `<think>…</think>` block is buffered and
stripped, so the user stares at a blank screen for the entire thinking
duration. Across 3–5 SmartLLM calls per request, this is **25–60 s of pure
dead time**.

### 2. The configured router model is never used

`OLLAMA_ROUTER_MODEL = "gemma3:1b"` is defined but **nothing reads it**.
`RouterService.__init__` calls `SmartLLM(timeout=30.0)` with no model
argument, so it falls through to the 8B agent model. Trivial
classification / intent / language tasks run on the slow reasoning model
instead of the 1B model that is **3× faster and does not think**:

| Model | Throughput |
|---|---|
| gemma3:1b | **121 tok/s** |
| gemma3:4b | 62 tok/s |
| qwen3:8b | 41 tok/s |

### 3. Memory thrashing from too many pinned models

Everything uses `keep_alive: -1` (pin forever) at `num_ctx: 16384`.
Pinning `gemma3:4b` + `qwen2.5vl:7b` (6 GB) + `qwen3:8b` (5.2 GB) +
`nomic-embed-text` + `gemma3:1b`, each with a 16k-token KV cache,
overcommits the 24 GB. When a request needs an evicted model it reloads
from disk — measured **1.7–3.0 s cold-load penalty** per swap.

---

## Fixes — highest impact first

### 1. Turn off thinking (biggest single win, ~4× on every LLM stage)

- `app/ai/ollama.py`: the `supports_think` block sets
  `payload["think"] = True`. For interactive chat you almost never want the
  discarded reasoning — set it to `False` (or delete the block).
- `app/services/smart_llm.py` — `_ollama()`: explicitly send
  `"think": False` in the request JSON so router/planner/content calls stop
  reasoning.
- **Alternative:** set `OLLAMA_AGENT_MODEL = "qwen2.5:7b"` (already installed,
  non-reasoning, same ~41 tok/s but zero thinking overhead).

### 2. Actually use `gemma3:1b` for routing / intent / language

```python
# RouterService.__init__
self._llm = SmartLLM(ollama_model=settings.OLLAMA_ROUTER_MODEL, timeout=30.0)
```

Do the same for the intent-analysis and language stages in `pipeline.py`.
Reserve `qwen3:8b` / `qwen2.5:7b` only for the final planner + content
generation. Cuts each routing stage from ~5.7 s to under 1 s.

### 3. Right-size `num_ctx` per call instead of a flat 16384

- Router / title / tool-detection: ≤ 4096
- Normal chat: 8192
- Large-document RAG / report generation: 16384 (only here)

Smaller KV caches mean faster prefill **and** less memory pressure, so
models stay resident.

### 4. Reduce the pinned-model set and cap generation

- Use a finite `keep_alive` (e.g. `"10m"`) so idle models release memory.
- Set server env `OLLAMA_MAX_LOADED_MODELS` so Ollama does not overcommit.
- Consolidating text + agent onto one `qwen2.5:7b` leaves just
  `{1b router, 7b general, 7b-vl vision, embed}` — fits 24 GB comfortably.
- Drop `num_predict` from 8192 → ~2048 for chat (keep higher only for
  report JSON).

### 5. Server-side tuning on the Mac mini

Enable in the Ollama service environment:

```
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
```

Shrinks the KV cache and speeds attention, especially at long context.

### 6. Collapse sequential LLM calls (architectural)

The pipeline runs router → intent → planner as three separate round-trips
that could be a single combined classification + plan call. Fewer
round-trips = less load-swap latency and fewer thinking passes.

---

## Expected outcome

For a typical agentic request:

- Disabling thinking: ~4× per LLM stage
- Routing on `gemma3:1b`: ~5 s → < 1 s per stage

Realistically this takes a request from **~60–90 s down to ~15–25 s**,
before the memory-thrashing fixes remove the swap stalls on top.

Fixes **#1 and #2** need no infrastructure work and deliver the largest
speedup — they are the recommended starting point.

---

## Side note (correctness, not performance)

Embeddings were switched to `nomic-embed-text` (768-dim), but
`RAG_EMBEDDING_DIM` in `app/config.py` is still `1024` (the old `bge-m3`
value). This mismatch will fail the embedding health check and likely the
pgvector column width. Worth fixing separately from the performance work.
