# FinSight chat latency baseline — 1/30 ok samples


## ALL PATHS  (n=1)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 1302 | 1302 | 1302 | 1302 | 1302 | 1302 |
| total ms | 1335 | 1335 | 1335 | 1335 | 1335 | 1335 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 55 | 46 | – | – | 102 | 1300 | 33 | 1333 |

## path = vector  (n=1)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 1302 | 1302 | 1302 | 1302 | 1302 | 1302 |
| total ms | 1335 | 1335 | 1335 | 1335 | 1335 | 1335 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 55 | 46 | – | – | 102 | 1300 | 33 | 1333 |

## Routing / fallback (workstream D)

- samples: 1
- graph-routed (classified graph/both): 0 (0% of traffic)
- fallback: n/a
- hard fallbacks (router raised): 0
