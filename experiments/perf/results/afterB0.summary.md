# FinSight chat latency baseline — 3/16 ok samples


## ALL PATHS  (n=3)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 5 | 2449 | 2667 | 4 | 2721 | 910 |
| total ms | 2266 | 2705 | 2744 | 650 | 2754 | 1890 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 165 | 46 | 0 | 0 | 71 | 906 | 978 | 1884 |

## path = graph  (n=2)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 4 | 5 | 5 | 4 | 5 | 4 |
| total ms | 1458 | 2186 | 2250 | 650 | 2266 | 1458 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | – | – | 0 | 0 | 1 | 1 | 1453 | 1454 |

## path = vector  (n=1)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 2721 | 2721 | 2721 | 2721 | 2721 | 2721 |
| total ms | 2754 | 2754 | 2754 | 2754 | 2754 | 2754 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 165 | 46 | – | – | 212 | 2717 | 28 | 2746 |

## Routing / fallback (workstream D)

- samples: 3
- graph-routed (classified graph/both): 2 (67% of traffic)
- graph→vector fallback fired: 0/2 (0.0% of graph-routed)
- hard fallbacks (router raised): 0
