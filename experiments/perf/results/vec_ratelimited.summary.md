# FinSight chat latency baseline — 30/30 ok samples


## ALL PATHS  (n=30)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 902 | 18515 | 21067 | 707 | 21316 | 3058 |
| total ms | 1954 | 18855 | 21351 | 730 | 21610 | 4001 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 98 | 45 | – | – | 144 | 3056 | 942 | 3997 |

## path = vector  (n=30)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 902 | 18515 | 21067 | 707 | 21316 | 3058 |
| total ms | 1954 | 18855 | 21351 | 730 | 21610 | 4001 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 98 | 45 | – | – | 144 | 3056 | 942 | 3997 |

## Routing / fallback (workstream D)

- samples: 30
- graph-routed (classified graph/both): 0 (0% of traffic)
- fallback: n/a
- hard fallbacks (router raised): 0
