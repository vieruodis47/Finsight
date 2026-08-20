# FinSight chat latency baseline — 4/4 ok samples


## ALL PATHS  (n=4)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 634 | 10514 | 11854 | 102 | 12189 | 3390 |
| total ms | 646 | 10569 | 11914 | 103 | 12250 | 3411 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 103 | 40 | 3750 | 2920 | 3388 | 21 | 3409 |

## path = graph  (n=1)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 12189 | 12189 | 12189 | 12189 | 12189 | 12189 |
| total ms | 12250 | 12250 | 12250 | 12250 | 12250 | 12250 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | – | – | 11248 | 11249 | 12186 | 61 | 12247 |

## path = vector  (n=1)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 1025 | 1025 | 1025 | 1025 | 1025 | 1025 |
| total ms | 1048 | 1048 | 1048 | 1048 | 1048 | 1048 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 49 | 39 | – | 88 | 1024 | 23 | 1046 |

## Routing / fallback (workstream D)

- samples: 4
- graph-routed (classified graph/both): 3 (75% of traffic)
- graph→vector fallback fired: 2/3 (66.7% of graph-routed)
- hard fallbacks (router raised): 0
- fell back on: fb_uncovered_ticker(graph→none), fb_uncovered_ticker2(graph→none)
