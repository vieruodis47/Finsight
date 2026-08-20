# FinSight Chat Latency — Phase 2 Plan (PLAN ONLY)

**Targets:** TTFT p95 < 800 ms, end-to-end p95 < 3 s, **no correctness/citation regressions.**
All "expected win" numbers are tied to Phase 1 (`PHASE1_REPORT.md`) plus Phase 2
read-only measurements recorded below. **Nothing here is implemented yet.**

## Phase 2 measurements that shaped this plan (read-only, real graph)

| probe | result |
|---|---|
| current `run_sparql` (single-fact, real 164,729-triple graph) | **11.1–11.6 s** (deterministic) |
| A1: BGP reorder + bind ticker/year as literals in-pattern | **3.4 s** (same result `88136.0`) |
| rdflib `prepareQuery` parse cost | **4.6 ms** (so parsing is NOT the cost) |
| prepared vs raw execution | identical 3.4 s → the cost is rdflib **join execution**, not parsing |
| A2: direct registry dict lookup `_registry[t]["metrics_by_year"][y][stmt][m]` | **0.39 µs**, value `88136.0` |

**Consequence:** A1 helps 3.3× but floors at ~3.4 s — it **cannot hit target for any
shape**. A2 is required for the hot path. The graph is a star schema
(`Company→Filing→Metric`); no query traverses a real relationship, so the A2 risk is
metric→field **mapping drift**, not lost joins.

---

## Workstream A — SPARQL / graph path (bottleneck #1, ~11 s, 62% of traffic)

### Query-shape inventory & A1/A2 assignment

| # | template | shape | join-reliant? | assign |
|---|---|---|---|---|
| 1 | `_sparql_single_company_year(t,y,m)` | 1 ticker · 1 year · 1 metric | no (single read) | **A2** |
| 2 | `_sparql_single_company(t,m)` | 1 ticker · 1 metric · all years | no (read + iterate years) | **A2** |
| 3 | `_sparql_multi_company_single_metric(ts,m)` | N tickers · 1 metric | no (union of single reads) | **A2** |
| 4 | `_sparql_single_company_multi_metric(t)` | 1 ticker · 5 metrics · all years | no (sibling fields of same filing) | **A2** (replicate margins/ratios) |
| 5 | `_sparql_multi_company_multi_metric(ts)` | N tickers · 5 metrics | no | **A2** (replicate margins/ratios) |
| 6 | `_sparql_single_metric_all(m)` | **ALL** companies · 1 metric · `ORDER BY value` | cross-company ranking | **A1** (keep on engine; see note) |

The "multi-metric" OPTIONALs (#4/#5) are not semantic joins — they read sibling fields
of one filing dict; in the registry that's one `metrics_by_year[y]` access. The only
genuine full-scan is #6 ("which company has the highest revenue"), which A1 barely
helps (no ticker to bind) — so #6 stays on rdflib for now, or migrates to A2 later as an
iterate-all-and-sort (lowest priority; rare query).

### A1 — "Filter down" (keep rdflib/SPARQL, push filters into the pattern + reorder BGP)
- **What:** rewrite templates so the selective triple is evaluated first
  (`?co fs:hasTicker "MSFT"` before `?co a fs:Company`) and ticker/year are bound as
  in-pattern literals, not trailing `FILTER`. rdflib evaluates BGP in written order with
  no cost-based reorder, so order is the lever.
- **Expected win:** **11.3 s → 3.4 s (measured)** per graph query. Applies to graph(15)
  + both(10). Does **not** reach target.
- **Effort:** Low (rewrite ~5 template strings). **Risk:** **Low** — same engine, same
  result semantics; validated identical on one shape, must be validated on all.
- **Role:** safe **interim** win shipped first for headroom, and the **permanent home for
  #6**. Also the **fallback** engine A2 defers to.
- **Verify:** for every template, assert rewritten rows == current rows on the golden set;
  re-run harness (graph + both blocks).

### A2 — "Engine replace" (bypass SPARQL for single-fact → in-memory registry)
- **What:** for shapes #1–#5, read straight from `_registry` (already in memory,
  populated at startup — the same source `build_graph` builds the RDF from). Map the
  SPARQL `metricName` → `(statement, field)` deterministically; assemble multi-metric /
  multi-year exactly as the current row set. **Keep the SPARQL path as a fallback**:
  if a lookup misses (unknown metric mapping, unusual shape) fall through to A1.
- **Expected win:** **11.3 s → ~0 ms (0.39 µs measured)**. Graph-path TTFT then bounded
  only by LLM first token (~1.2 s median). **"both"-path TTFT collapses to retrieval
  (~150 ms)** because that path already leads with a deterministic text header (see B0).
- **Effort:** Medium (mapping table + assembly + fallback + shadow-compare harness).
  **Risk:** **Medium** — mapping/units/`computed_ratios` drift, `ORDER BY` semantics.
- **Reversibility mitigation:** ship behind a flag with a **shadow-compare window**
  (compute A2 + SPARQL, log mismatches, serve SPARQL) before flipping to serve A2.
  Flag-off reverts instantly.
- **Verify (mandatory, per Phase 3 constraint):** golden-answer **and citation** check
  re-run on **EVERY graph-routed question** — not a spot-check — plus the shadow-compare
  must show 0 value mismatches over the validation window.

---

## Workstream B — Gemini TTFT (bottleneck #2) — PARALLEL to A

After A lands, the ~1.2 s median / ~2.5 s mean / **~10 s tail** LLM first-token becomes
the p95. Sizing is against **p95**, not mean.

### B0 — Lead with a deterministic first token on graph/both (cheapest, biggest structural win)
- **What:** emit the deterministic header text segment (graph/"both" already have
  `"**From structured financial data …**"`) **before** the LLM segment on the pure-graph
  path too, so first token = retrieval-bound, not LLM-bound.
- **Expected win:** graph/both TTFT → retrieval time (~150 ms post-A2) instead of
  +~1.2 s LLM wait. Makes **TTFT p95 < 800 ms reachable for graph/both**.
- **Effort:** Low. **Risk:** Low (reorders existing segments; answer content unchanged).
  Note: shifts TTFT to "first *meaningful* token" — call this out honestly in metrics.
- **Verify:** harness TTFT on graph/both; answer bytes unchanged (diff full stream).

### B1 — Trim prompt/context payload (vector path)
- **What:** reduce prefill — e.g. k=5→3 chunks and/or cap chunk chars; the 64-line system
  prompt is constant (candidate for caching, B3).
- **Expected win:** modest on vector TTFT (lower prefill); **−200–400 ms median**, small
  p95. **Effort:** Low. **Risk:** **Medium** — fewer passages can drop citation coverage;
  gated by citation re-check.
- **Verify:** golden citation coverage must not regress; harness vector block.

### B2 — Hedged request for the tail (the p95 lever)
- **What:** if no token arrives within a trigger (~1.2–1.5 s), fire a second Gemini
  stream; take whichever yields first, cancel the other. Two independent samples rarely
  both hit the tail.
- **Expected win, p95-specific:** in Phase 1, ~2/15 warm vector calls hit ~10 s (~13%).
  Hedged p(both slow) ≈ 0.13² ≈ 1.7% → **vector TTFT p95 ~10 s → ~2–3 s**. Directly
  attacks p95/p99, not median. **Effort:** Medium. **Risk:** Medium — up to 2× tokens on
  the hedged fraction; must preserve single clean stream + citations (dedupe the losing
  stream). Reversible (flag).
- **Verify:** harness p95/p99 (needs ≥100 samples to be meaningful); token-cost delta logged.

### B3 — Prompt caching + endpoint/region investigation
- **What:** (a) Gemini context caching for the constant system prompt; (b) test Vertex
  **regional** endpoint vs API-key routing — the ~10 s spikes smell like API-side
  queueing/cold connection, not model compute.
- **Expected win:** caching small (system prompt is short); endpoint change could cut the
  tail cause at source (uncertain until measured). **Effort:** Low–Med. **Risk:** Low–Med
  (endpoint/model swap needs a golden re-eval). **Verify:** harness tail; golden eval if
  model/endpoint changes.

> **Honest target caveat:** even after A + B, the **pure-vector path** TTFT floor is
> Gemini's network first-token (~1.2 s median). **TTFT p95 < 800 ms is reachable for
> graph/both (A2 + B0) but likely NOT for pure-vector** without a faster/closer model.
> Decision for you: accept ~1.2–1.5 s vector TTFT, or invest in a co-located/faster LLM.

---

## Workstream C — Verify "both"-path GIL contention (#4) resolves after A

- **Do not assume.** Phase 1 showed warm `embed` ballooning 154 ms → 3,826 ms on "both"
  while the 11 s SPARQL saturated the sibling thread. A2 makes that sibling ~0 ms.
- **Plan:** after A2, **re-run the harness "both" block and read the `embed` stage**.
  Expected: `embed` back to ~150 ms. **Only if `embed` stays > ~300 ms** do we pursue
  separate work (move embedding to a worker process, or serialize retrieve→embed).
- **Effort:** trivial (measurement). **Risk:** none (measurement only).

---

## Workstream D — Fix `_graph_prompt` tuple-arity bug + measure fallback rate (EARLY)

- **Bug:** graph-miss early-returns are 3-tuples (router.py 1450/1454/1469/1477/1481);
  success is a 4-tuple (1542); callers unpack 4 → `ValueError` → whole request thrown onto
  pure vector, discarding the router decision and (on "both") the concurrent graph half.
- **Fix:** return `None, "", [], None` on all early exits. **Effort:** trivial.
  **Risk:** **Low**, but it **changes behavior**: graph-miss now takes the intended clean
  vector fallback (no exception, no lost "both" half) → validate with golden + citation
  re-check.
- **Measure fallback rate (why it matters):** some "graph-classified" traffic may not be
  exercising the graph today, which inflates/deflates the true cost of the 62%. Add a
  counter (in `obs`) incremented when the fallback fires; run the golden set + a broader
  uncovered-company set; report %. In the Phase 1 golden run the fallback did **not** fire
  (all graph-classified Qs returned `path=graph` with sources) — but coverage-edge and
  uncovered-company questions are exactly what trips it, so measure before trusting 62%.
- **Do first:** it's a correctness fix and it calibrates the denominator A is optimizing.

---

## Workstream E — Cloud Run cold-start (#3) — SEPARATE, deployed-env only

Explicitly **out of the local latency plan.** Distinct workstream, measured against a real
revision:
- **min-instances ≥ 1** to kill scale-to-zero cold start (amortize the bge-m3 ~12.6 s load
  + graph ~1.3 s rebuild into container startup, not per request).
- **CPU allocation:** `--cpu-always-allocated` (or min-instances) so the in-process embed +
  (until A2) SPARQL aren't throttled between requests; sizing vs the single-core contention
  seen in C.
- **Concurrency** setting vs per-request CPU.
- Model weights already baked into the image (Dockerfile.python) → cold = load-from-disk,
  not download.
- **Verify:** deploy a revision; measure p95/p99 under scale-to-zero vs min-instances=1.
  (Project note: scale-to-zero has bitten a background worker before.)

---

## Recommended sequencing

1. **D** — fix tuple bug + add fallback counter. *(correctness; calibrates the 62% denominator; trivial)*
2. **A1** — BGP reorder/bind. *(safe 3.3× interim across graph+both; low risk)*
3. **A2** — registry lookup for #1–#5 behind a flag + shadow-compare. *(the real fix → sub-ms; exhaustive golden+citation re-check)*
4. **C** — re-measure "both" `embed`; branch only if contention persists.
5. **B** in **parallel from step 2** (independent of A): **B0** (lead token, unlocks graph/both target) → **B1** (context trim) → **B2** (hedging, the vector p95 lever) → **B3** (caching/endpoint).
6. **E** — separately, on a deployed revision.

Each Phase 3 change: **one change per commit**, each with a **before/after benchmark from
`bench_chat.py`**, and for **anything in workstream A**, the **golden-answer + citation
check re-run on EVERY graph-routed question** (not a spot-check).

## Reversible vs one-way-door

- **Reversible (revert commit / flip flag):** D fix, A1 (query strings), A2 (flag + SPARQL
  fallback kept), B0, B2 (flag), C, E (deploy settings), all obs instrumentation.
- **Reversible-with-re-eval (changes what the model sees / answer quality):** B1 context
  trim, B3 model/endpoint change — reversible in code but require a golden citation/answer
  re-eval before and after.
- **One-way-door to avoid:** deleting the SPARQL path in A2 (don't — keep it as the
  fallback), and any citation/attribution change (out of scope — must be preserved).
