# FinSight chat latency baseline — 16/16 ok samples


## ALL PATHS  (n=16)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 2048 | 11855 | 14477 | 186 | 15133 | 4805 |
| total ms | 9372 | 18572 | 22779 | 633 | 23831 | 9245 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 130 | 56 | 0 | 0 | 117 | 4802 | 4439 | 9242 |

## path = graph  (n=6)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 6640 | 9607 | 9892 | 539 | 9964 | 5687 |
| total ms | 6770 | 9748 | 10048 | 633 | 10123 | 5808 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | – | – | 0 | 0 | 1 | 5684 | 120 | 5805 |

## path = vector  (n=6)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 6381 | 14040 | 14914 | 1394 | 15133 | 6997 |
| total ms | 7134 | 14071 | 14933 | 1679 | 15148 | 7514 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 127 | 57 | – | – | 185 | 6994 | 516 | 7511 |

## path = both  (n=4)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 188 | 209 | 212 | 186 | 212 | 193 |
| total ms | 15734 | 22779 | 23620 | 12685 | 23831 | 16996 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 135 | 55 | 0 | 0 | 191 | 191 | 16802 | 16993 |

## Routing / fallback (workstream D)

- samples: 16
- graph-routed (classified graph/both): 10 (62% of traffic)
- graph→vector fallback fired: 0/10 (0.0% of graph-routed)
- hard fallbacks (router raised): 0
