# FinSight chat latency baseline — 24/24 ok samples


## ALL PATHS  (n=24)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 12404 | 24589 | 25853 | 904 | 26202 | 13476 |
| total ms | 20666 | 28608 | 32848 | 1145 | 34063 | 17712 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 1592 | 106 | 10858 | 6870 | 13474 | 4235 | 17709 |

## path = graph  (n=9)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 22426 | 24435 | 24632 | 12404 | 24681 | 20066 |
| total ms | 22430 | 24504 | 24713 | 12478 | 24766 | 20150 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | – | – | 11285 | 11286 | 20064 | 84 | 20148 |

## path = vector  (n=9)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 2757 | 24019 | 25766 | 904 | 26202 | 9058 |
| total ms | 3368 | 24035 | 25789 | 1145 | 26227 | 9548 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 137 | 83 | – | 221 | 9056 | 489 | 9545 |

## path = both  (n=6)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 10174 | 11604 | 11635 | 8906 | 11643 | 10219 |
| total ms | 26644 | 32742 | 33799 | 20551 | 34063 | 26299 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 3775 | 140 | 10216 | 10217 | 10217 | 16079 | 26296 |

## Routing / fallback (workstream D)

- samples: 24
- graph-routed (classified graph/both): 15 (62% of traffic)
- graph→vector fallback fired: 0/15 (0.0% of graph-routed)
- hard fallbacks (router raised): 0
