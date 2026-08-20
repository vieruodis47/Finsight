#!/usr/bin/env python3
"""
experiments/perf/bench_chat.py — Phase 1 latency baseline harness for FinSight chat.

Drives the streaming chat endpoint (/api/chat/stream) with a representative set of
questions spanning all three router paths (graph / vector / both), measures
client-observed time-to-first-token (TTFT) and total latency, and reads the
server's per-stage `timings` object straight off the terminal `done` event (added
in backend/obs.py + rag.py). Computes p50/p95/p99 overall and per path.

This is the SAME harness Phase 3 re-runs for before/after deltas, so keep it
deterministic and side-effect free (it only reads answers; it never mutates data).

Usage:
    python experiments/perf/bench_chat.py --url http://127.0.0.1:8001 --reps 5
    python experiments/perf/bench_chat.py --cold-only          # single cold pass
Outputs:
    experiments/perf/results/<label>.raw.jsonl   one line per request
    experiments/perf/results/<label>.summary.md  human-readable percentile report
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
Q_FILE = HERE / "questions.jsonl"
OUT_DIR = HERE / "results"

STAGE_KEYS = ["classify", "embed", "vector_search", "sparql", "graph", "retrieval_total",
              "ttft", "generation", "total"]


def load_questions(path: Path = Q_FILE) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def routing_summary(rows: list[dict]) -> str:
    """Report the true graph→vector fallback rate (workstream D)."""
    ok = [r for r in rows if not r.get("error")]
    graph_routed = [r for r in ok if r.get("routing", {}).get("graph_routed")]
    fb = [r for r in graph_routed if r["routing"].get("graph_fallback")]
    hard = [r for r in ok if r.get("routing", {}).get("hard_fallback")]
    lines = ["\n## Routing / fallback (workstream D)\n"]
    n = len(ok)
    lines.append(f"- samples: {n}")
    lines.append(f"- graph-routed (classified graph/both): {len(graph_routed)} "
                 f"({100*len(graph_routed)/n:.0f}% of traffic)" if n else "- graph-routed: 0")
    denom = len(graph_routed)
    lines.append(f"- graph→vector fallback fired: {len(fb)}/{denom} "
                 f"({100*len(fb)/denom:.1f}% of graph-routed)" if denom else "- fallback: n/a")
    lines.append(f"- hard fallbacks (router raised): {len(hard)}")
    if fb:
        lines.append("- fell back on: " + ", ".join(
            f"{r['id']}({r['routing'].get('classified')}→{r['routing'].get('served')})" for r in fb))
    return "\n".join(lines) + "\n"


def ask(url: str, q: dict, timeout: float = 180.0) -> dict:
    """Fire one streaming chat request; return timing + path (client + server)."""
    payload = {"question": q["question"], "k": q.get("k", 5)}
    if q.get("ticker"):
        payload["ticker"] = q["ticker"]
    if q.get("tickers"):
        payload["tickers"] = q["tickers"]
    if q.get("form"):
        payload["form"] = q["form"]
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat/stream",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
    )
    t0 = time.perf_counter()
    client_ttft = None
    n_tokens = 0
    done = None
    err = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            evt = json.loads(line)
            et = evt.get("type")
            if et == "token":
                n_tokens += 1
                if client_ttft is None:
                    client_ttft = (time.perf_counter() - t0) * 1000.0
            elif et == "done":
                done = evt
            elif et == "error":
                err = evt.get("message")
    client_total = (time.perf_counter() - t0) * 1000.0
    timings = (done or {}).get("timings", {})
    return {
        "id": q["id"],
        "expect_path": q.get("expect_path"),
        "path": (done or {}).get("retrieval_path"),
        "client_ttft_ms": round(client_ttft, 1) if client_ttft else None,
        "client_total_ms": round(client_total, 1),
        "n_tokens": n_tokens,
        "n_sources": len((done or {}).get("sources", [])),
        "n_valid_citations": len((done or {}).get("valid_citations", [])),
        "error": err,
        "timings": timings,
        "routing": (done or {}).get("routing", {}),
    }


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarize(rows: list[dict]) -> str:
    ok = [r for r in rows if not r.get("error")]
    lines = []
    lines.append(f"# FinSight chat latency baseline — {len(ok)}/{len(rows)} ok samples\n")

    def block(title: str, subset: list[dict]) -> None:
        if not subset:
            return
        ttft = [r["client_ttft_ms"] for r in subset if r["client_ttft_ms"]]
        total = [r["client_total_ms"] for r in subset]
        lines.append(f"\n## {title}  (n={len(subset)})\n")
        lines.append("| metric | p50 | p95 | p99 | min | max | mean |")
        lines.append("|---|---|---|---|---|---|---|")
        for name, xs in [("TTFT ms", ttft), ("total ms", total)]:
            if xs:
                lines.append(f"| {name} | {pct(xs,.5):.0f} | {pct(xs,.95):.0f} | "
                             f"{pct(xs,.99):.0f} | {min(xs):.0f} | {max(xs):.0f} | "
                             f"{statistics.mean(xs):.0f} |")
        # Per-stage means (from server timings) — the decomposition.
        lines.append("\nPer-stage mean (ms), server-measured:")
        lines.append("| " + " | ".join(STAGE_KEYS) + " |")
        lines.append("|" + "---|" * len(STAGE_KEYS))
        cells = []
        for kkey in STAGE_KEYS:
            vals = [r["timings"].get(kkey) for r in subset if r["timings"].get(kkey) is not None]
            cells.append(f"{statistics.mean(vals):.0f}" if vals else "–")
        lines.append("| " + " | ".join(cells) + " |")

    block("ALL PATHS", ok)
    for path in ("graph", "vector", "both"):
        block(f"path = {path}", [r for r in ok if r["path"] == path])
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8001")
    ap.add_argument("--reps", type=int, default=5, help="measured reps per question (warm)")
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--cold-only", action="store_true", help="one cold pass, no warm reps")
    ap.add_argument("--questions", default=str(Q_FILE), help="path to questions .jsonl")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    questions = load_questions(Path(args.questions))
    rows: list[dict] = []

    # --- COLD pass: first hit per path pays model-load / graph-build one-time costs.
    print("== COLD pass (first request per path; model load + graph build) ==")
    cold_seen = set()
    for q in questions:
        if q["expect_path"] in cold_seen:
            continue
        cold_seen.add(q["expect_path"])
        r = ask(args.url, q)
        r["phase"] = "cold"
        r["rep"] = 0
        rows.append(r)
        t = r["timings"]
        print(f"  [cold {(r['path'] or 'ERR'):>6}] {q['id']}: TTFT={r['client_ttft_ms']}ms "
              f"total={r['client_total_ms']}ms embed={t.get('embed','-')} "
              f"vsearch={t.get('vector_search','-')} graph={t.get('graph','-')}")

    if not args.cold_only:
        print("\n== WARM-UP (1x each, discarded) ==")
        for q in questions:
            ask(args.url, q)

        print(f"\n== WARM measurement ({args.reps} reps/question) ==")
        for rep in range(1, args.reps + 1):
            for q in questions:
                r = ask(args.url, q)
                r["phase"] = "warm"
                r["rep"] = rep
                rows.append(r)
                t = r["timings"]
                print(f"  [warm r{rep} {(r['path'] or 'ERR'):>6}] {q['id']}: "
                      f"TTFT={r['client_ttft_ms']}ms total={r['client_total_ms']}ms "
                      f"retr={t.get('retrieval_total','-')} gen={t.get('generation','-')}")

    raw_path = OUT_DIR / f"{args.label}.raw.jsonl"
    raw_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    warm = [r for r in rows if r.get("phase") == "warm"]
    summary = summarize(warm if warm else rows) + routing_summary(warm if warm else rows)
    sum_path = OUT_DIR / f"{args.label}.summary.md"
    sum_path.write_text(summary)
    print("\n" + summary)
    print(f"raw:     {raw_path}")
    print(f"summary: {sum_path}")


if __name__ == "__main__":
    main()
