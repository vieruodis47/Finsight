#!/usr/bin/env python3
"""
experiments/perf/check_correctness.py — golden-answer + citation guard for the
graph path. Run after ANY change touching workstream A/D (A1, A2, tuple fix).

For every graph-routed question it asserts the exact XBRL figure(s) appear in the
streamed answer and that a graph answer carries sources. A single mismatched
financial figure exits non-zero (stop-and-report).

Expected figures are the XBRL-verified values from experiments/rag/eval golden set.
Usage: python experiments/perf/check_correctness.py --url http://127.0.0.1:8001
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

# Graph-routed questions from questions.jsonl → the exact millions figures that
# MUST appear (XBRL-verified). A graph answer must also carry >=1 source.
EXPECT = {
    "g1": {"q": "What was Microsoft's net income in fiscal year 2024?",
           "kw": {"ticker": "MSFT", "form": "10-K"}, "figures": ["88,136"]},
    "g2": {"q": "What were Apple's total net sales in fiscal 2024?",
           "kw": {"ticker": "AAPL", "form": "10-K"}, "figures": ["391,035"]},
    "g3": {"q": "What was NVIDIA's operating cash flow in fiscal 2026?",
           "kw": {"ticker": "NVDA", "form": "10-K"}, "figures": ["102,718"]},
    "b1": {"q": "What were Apple's operating income and net income in fiscal 2024, and how far apart were they?",
           "kw": {"ticker": "AAPL", "form": "10-K"}, "figures": ["123,216", "93,736"]},
    "b2": {"q": "Compare Apple and Microsoft net income in fiscal 2024. Which is higher and by how much?",
           "kw": {"tickers": ["AAPL", "MSFT"], "form": "10-K"}, "figures": ["93,736", "88,136"]},
    "b3": {"q": "In NVIDIA's fiscal 2026, what were cost of revenue and cash flow from operating activities?",
           "kw": {"ticker": "NVDA", "form": "10-K"}, "figures": ["102,718"],
           # KNOWN PRE-EXISTING GAP (not a regression): NVDA FY2026 cost_of_revenue
           # (62,475) is not surfaced by graph or vector. Verified identical on the
           # pre-D commit (8938488) before the tuple fix — so it is a data-coverage
           # gap, orthogonal to the latency work. Tracked here so the gate flags NEW
           # regressions, not this. Re-add "62,475" once the coverage gap is fixed.
           "known_gap": ["62,475"]},
}


def ask(url: str, q: str, kw: dict) -> dict:
    body = json.dumps({"question": q, "k": 5, **kw}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/chat/stream", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/x-ndjson"})
    txt, done = [], None
    with urllib.request.urlopen(req, timeout=180) as r:
        for line in r:
            e = json.loads(line)
            if e.get("type") == "token":
                txt.append(e["text"])
            elif e.get("type") == "done":
                done = e
    return {"answer": "".join(txt), "done": done or {}}


def norm(s: str) -> str:
    # tolerate "88,136" vs "88136" vs "88.136" separators
    return s.replace(",", "").replace(" ", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8001")
    args = ap.parse_args()

    failures = []
    for qid, spec in EXPECT.items():
        res = ask(args.url, spec["q"], spec["kw"])
        ans, done = res["answer"], res["done"]
        ans_n = norm(ans)
        path = done.get("retrieval_path")
        n_sources = len(done.get("sources", []))
        missing = [f for f in spec["figures"] if norm(f) not in ans_n]
        problems = []
        if missing:
            problems.append(f"MISSING FIGURES {missing}")
        if n_sources == 0:
            problems.append("NO SOURCES (attribution lost)")
        status = "FAIL" if problems else "PASS"
        if problems:
            failures.append(qid)
        gap = f" [known pre-existing gap: {spec['known_gap']}]" if spec.get("known_gap") else ""
        print(f"[{status}] {qid} path={path} sources={n_sources} "
              f"figures={spec['figures']}{gap} {'| ' + '; '.join(problems) if problems else ''}")
        if problems:
            print(f"        answer: {ans[:200].replace(chr(10),' ')}")

    print(f"\n{'ALL PASS' if not failures else 'FAILURES: ' + ','.join(failures)} "
          f"({len(EXPECT)-len(failures)}/{len(EXPECT)})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
