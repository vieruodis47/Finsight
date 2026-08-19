# FinSight Chat Latency — Phase 1 Baseline Report

**Date:** 2026-08-19 · **Scope:** streaming chat (`/api/chat/stream`) · **Env:** local
(macOS, single instrumented server on :8001, CPU torch venv) against the real
**RavenDB Cloud free-tier** + 6,321-chunk / 228-company corpus. Gemini
`gemini-3.1-flash-lite` via API key.

Targets (agreed): **TTFT p95 < 800 ms**, **end-to-end p95 < 3 s**, no correctness/citation regressions.

> Local measurement was chosen for accurate **stage decomposition**. It does **not**
> reproduce Cloud Run scale-to-zero cold-start or CPU throttling — those are
> characterized analytically in §5 and flagged for a Cloud Run run.

---

## 1. Request path (HTTP entry → streamed token)

```
Browser (ChatInterface → ChatContext.runQuery → gemini.ts askFinSightStream)
  → POST /api/chat/stream  (NDJSON stream)
  → Node/Express (server.js:210) streamingApiForwarder  [pyProxy.js:55]  (unbuffered pipe, ~ms)
  → Python/FastAPI rag.py:chat_stream → _chat_event_stream
        ├─ classify_question()            regex, ~0 ms         (router.py:534)
        ├─ retrieve ("bird" phase):                             (router.py:prepare_chat_stream)
        │    • vector: embed_texts() bge-m3 in-proc → RavenDB vector.search()  (embeddings.py:search)
        │    • graph : run_sparql() over in-memory rdflib graph                (rdf_graph.py)
        │    • both  : graph ∥ vector via ThreadPoolExecutor(2)
        ├─ generate_stream() Gemini generate_content_stream → yield token deltas
        └─ done event: sources + valid_citations + timings
```

Everything up to the first `generate_stream` delta is **pre-first-token** and defines TTFT.
Router classification is **regex, not an LLM call** (good). Node proxy adds negligible
streaming overhead. The harness hits Python directly (:8001) to isolate the pipeline.

## 2. Instrumentation added (additive, reversible)

- **`backend/obs.py`** — contextvar stage timers + guarded OpenTelemetry spans
  (no-op unless `FINSIGHT_OTEL=1`). Zero behavior change.
- Wired into `embeddings.search()` (`embed`, `vector_search`), the router
  (`classify`, `graph`; collector propagated into the "both" thread pool via
  `bind_context()`), and `rag.py` (`retrieval_total`, `ttft`, `generation`, `total`).
- Per-stage numbers ship in the `done` event's new **`timings`** field (existing
  clients ignore unknown keys). The Phase 1/3 harness reads them straight off the wire.
- Harness: `experiments/perf/bench_chat.py` + `questions.jsonl` (8 Qs across
  graph/vector/both). Re-run verbatim in Phase 3 for before/after deltas.

## 3. Baseline numbers (warm, n=40; 5 reps × 8 Qs)

| path (n) | TTFT p50 | TTFT p95 | total p50 | total p95 | dominant stage (mean) |
|---|---|---|---|---|---|
| **all (40)** | **10,684 ms** | **15,060 ms** | 11,282 ms | 18,718 ms | graph 10,360 |
| graph (15) | 11,614 ms | 20,044 ms | 12,226 ms | 20,137 ms | **run_sparql 10,685** |
| vector (15) | 1,395 ms | 10,204 ms* | 2,734 ms | 10,321 ms* | LLM TTFT ~2,490 |
| both (10) | 9,894 ms | 11,308 ms | 13,515 ms | 19,092 ms | **run_sparql ~9,875** |

Per-stage mean (ms): `classify 0 · embed 154(vec)/3,826(both) · vector_search 73–135 · graph 10,685 · LLM-first-token ~2,490 · generation 124(graph)/611(vec)/3,964(both)`

\* vector p95 is inflated by two ~10 s **Gemini first-token spikes** (retrieval was ~230 ms those runs); median Gemini TTFT ≈ 1.2 s.

**Cold (first request per path):** graph 13.7 s · vector 18.0 s (embed model-load **12.6 s** + first RavenDB 4.9 s) · both 8.6 s.

**Every warm number is far over target** (TTFT p95 800 ms): best case (vector p50) is ~1.75×; graph/both are 14–25×.

## 4. Ranked bottlenecks (by measured impact on TTFT)

1. **`run_sparql()` over rdflib — ~11 s per query, deterministic, RECURRING (not cold).**
   Localized precisely: on the real 164,729-triple graph, `run_sparql` = 11.2–11.6 s
   every call (rebuild is a one-time 1.3 s). Hits **graph + both = 25/40 (62%)** of
   traffic and single-handedly sets overall p50 TTFT to ~10.7 s.
   *Cause:* the SPARQL matches `?co a fs:Company … ?f … ?m …` across **all 220
   companies × filings × metrics**, then `FILTER`s to one ticker/year *after* the join
   — rdflib materializes the full cross-product regardless of the single fact wanted.
   The metrics already live in `_registry` in memory. **Biggest lever in the app.**

2. **Gemini time-to-first-token — ~1.2 s median, ~2.5 s mean, spikes to ~10 s.**
   Affects 100% of queries. Even with #1 fixed, this alone keeps the vector path over
   the 800 ms TTFT target and causes the vector p95 blowups.

3. **Cold start — embed model load ~12.6 s + graph rebuild ~1.3 s (first request only).**
   On Cloud Run scale-to-zero, every cold container pays this (plus image pull /
   container init on top — see §5).

4. **CPU/GIL contention on the "both" path.** Warm `embed` balloons 154 ms → **3,826 ms**
   when it runs concurrently with the 11 s SPARQL in the sibling thread. The
   parallelism is real but undercut by single-core contention; fixing #1 largely
   dissolves this.

5. **RavenDB Cloud vector_search — 73–135 ms warm. NOT a significant warm bottleneck.**
   (Cold first hit ~4.9 s; free-tier tail spikes possible but did not dominate.)

Not bottlenecks: router classification (regex, ~0 ms), Node proxy, prompt assembly,
citation validation.

## 5. Cloud Run cold-start / throttling (out of local scope — flagged)

Not reproducible locally. On scale-to-zero, expect per-cold-request: container/image
pull + Python import + **bge-m3 model load (~12.6 s measured)** + first graph rehydrate
(~1.3 s) + first RavenDB TLS handshake. CPU throttling (Cloud Run gives full vCPU only
during request unless `--cpu-always-allocated`) will further slow the in-process
embedding and — until fixed — the 11 s SPARQL. Recommend a follow-up run against a
deployed revision to quantify p95/p99 under scale-to-zero. *(Note: this has bitten a
background worker before per the project brief.)*

## 6. Correctness / citation baseline (preserved)

40/40 samples returned answers; instrumentation is additive. Spot-check:
MSFT net income → `$88,136M` (matches golden d002), graph path, XBRL attribution.
Apple supply-chain → vector path, 5 sources, valid citations `[1,2,3,4]`, SEC URLs intact.

## 7. Latent bugs found (documented, NOT changed in Phase 1)

- **`_graph_prompt` tuple-arity mismatch** (router.py 1450/1454/1469/1477/1481 return
  3-tuples; success at 1542 returns a 4-tuple; callers unpack 4). A graph-miss throws
  `ValueError`, which propagates up and forces the **whole** request onto pure vector —
  discarding the router decision and, on "both", the concurrent graph half. Correctness-
  of-routing + latency impact. (Common covered-metric case hits the 4-tuple path and works.)

## 8. Reproduce / teardown

- Run: `.venv-perf/bin/python experiments/perf/bench_chat.py --url http://127.0.0.1:8001 --reps 5`
- Server: instrumented on :8001 (venv, CPU torch). Stale :8000 left untouched.
- Reversible: instrumentation is additive; `.venv-perf/` and the `finsight-export.ravendbdump`
  are disposable; no product behavior changed.
