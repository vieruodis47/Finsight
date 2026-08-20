# FinSight chat latency baseline — 16/16 ok samples


## ALL PATHS  (n=16)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 2133 | 7297 | 8413 | 437 | 8692 | 2945 |
| total ms | 4337 | 49609 | 108415 | 844 | 123117 | 13634 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 564 | 56 | 1680 | 1680 | 1156 | 2942 | 10688 | 13630 |

## path = graph  (n=6)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 3485 | 7667 | 8487 | 743 | 8692 | 3871 |
| total ms | 3604 | 7805 | 8660 | 844 | 8874 | 3959 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | – | – | 2040 | 2040 | 2041 | 3868 | 88 | 3955 |

## path = vector  (n=6)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 2082 | 6649 | 6796 | 831 | 6832 | 3148 |
| total ms | 2784 | 6965 | 7081 | 906 | 7110 | 3629 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 156 | 51 | – | – | 208 | 3145 | 479 | 3624 |

## path = both  (n=4)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 1267 | 2035 | 2037 | 437 | 2038 | 1252 |
| total ms | 19840 | 108415 | 120177 | 9815 | 123117 | 43153 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | sparql | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|---|
| 0 | 1176 | 62 | 1141 | 1141 | 1249 | 1250 | 41900 | 43149 |

## Routing / fallback (workstream D)

- samples: 16
- graph-routed (classified graph/both): 10 (62% of traffic)
- graph→vector fallback fired: 0/10 (0.0% of graph-routed)
- hard fallbacks (router raised): 0
