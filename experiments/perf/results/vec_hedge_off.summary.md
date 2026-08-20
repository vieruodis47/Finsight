# FinSight chat latency baseline — 12/30 ok samples


## ALL PATHS  (n=12)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 711 | 1665 | 1897 | 466 | 1955 | 884 |
| total ms | 1714 | 2516 | 2597 | 773 | 2618 | 1636 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 103 | 47 | – | – | 151 | 881 | 751 | 1633 |

## path = vector  (n=12)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 711 | 1665 | 1897 | 466 | 1955 | 884 |
| total ms | 1714 | 2516 | 2597 | 773 | 2618 | 1636 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 103 | 47 | – | – | 151 | 881 | 751 | 1633 |

## Routing / fallback (workstream D)

- samples: 12
- graph-routed (classified graph/both): 0 (0% of traffic)
- fallback: n/a
- hard fallbacks (router raised): 0
