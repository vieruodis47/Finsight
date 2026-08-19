# FinSight chat latency baseline — 40/40 ok samples


## ALL PATHS  (n=40)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 10684 | 15060 | 21575 | 471 | 23502 | 8529 |
| total ms | 11282 | 18718 | 22044 | 877 | 23566 | 9796 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 1623 | 98 | 10360 | 6561 | 8526 | 1267 | 9792 |

## path = graph  (n=15)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 11614 | 20044 | 22810 | 11012 | 23502 | 13437 |
| total ms | 12226 | 20137 | 22880 | 11138 | 23566 | 13561 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | – | – | 10685 | 10685 | 13434 | 124 | 13558 |

## path = vector  (n=15)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 1395 | 10204 | 10413 | 471 | 10466 | 2721 |
| total ms | 2734 | 10321 | 10661 | 877 | 10746 | 3334 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 154 | 73 | – | 228 | 2718 | 611 | 3329 |

## path = both  (n=10)

| metric | p50 | p95 | p99 | min | max | mean |
|---|---|---|---|---|---|---|
| TTFT ms | 9894 | 11308 | 11421 | 8492 | 11449 | 9877 |
| total ms | 13515 | 19092 | 19550 | 10985 | 19665 | 13843 |

Per-stage mean (ms), server-measured:
| classify | embed | vector_search | graph | retrieval_total | ttft | generation | total |
|---|---|---|---|---|---|---|---|
| 0 | 3826 | 135 | 9874 | 9875 | 9875 | 3964 | 13839 |
