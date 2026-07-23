"""
experiments/rag/pairwise.py — R4 pairwise A/B protocol for close calls
(METRICS.md rule 5: overall correctness delta < 0.05).

For each question: baseline answer vs challenger answer (repeat 1 of each),
judged in BOTH orders (blinded, randomized labels); a win must survive the
order swap, else it is a tie (judge_prompts.md blinding protocol rule 2).

Usage:
    python experiments/rag/pairwise.py --exp E-3 --baseline naive \
        --challengers prompt_minimal,prompt_fewshot,ctx_metadata,prompt_quote_first \
        --eval experiments/rag/eval/questions.v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / "backend" / ".env.python")
except ImportError:
    pass


def load_answers(exp_dir: Path, variant: str) -> dict:
    """qid -> answer text (repeat 1; empty answers excluded)."""
    out = {}
    for line in (exp_dir / f"{variant}.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["repeat"] == 1 and r.get("answer") and not r.get("error"):
            out[r["qid"]] = r["answer"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--challengers", required=True)
    ap.add_argument("--eval", required=True)
    args = ap.parse_args()

    sys.path.insert(0, str(_REPO / "experiments" / "rag"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "scorer", _REPO / "experiments" / "rag" / "scorer.py")
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)

    exp_dir = _REPO / "experiments" / "rag" / "results" / args.exp
    judge = scorer.Judge(exp_dir / "judge_cache.jsonl")

    questions = {}
    for line in Path(args.eval).read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            questions[q["id"]] = q

    base_answers = load_answers(exp_dir, args.baseline)
    report = {"exp": args.exp, "baseline": args.baseline,
              "judge_model": judge.model, "pairs": {}}

    for challenger in [c.strip() for c in args.challengers.split(",")]:
        ch_answers = load_answers(exp_dir, challenger)
        tally = Counter()
        detail = []
        for qid, q in sorted(questions.items()):
            a, b = base_answers.get(qid), ch_answers.get(qid)
            if not a or not b:
                tally["skipped"] += 1
                continue
            claims = [f.get("claim", "") for f in q.get("expected_facts", [])]
            # order 1: baseline as A; order 2: challenger as A
            r1 = judge.pairwise(q["question"], claims, a, b)
            r2 = judge.pairwise(q["question"], claims, b, a)
            w1 = r1.get("winner")   # A=baseline, B=challenger
            w2 = r2.get("winner")   # A=challenger, B=baseline
            if w1 == "A" and w2 == "B":
                outcome = "baseline"
            elif w1 == "B" and w2 == "A":
                outcome = "challenger"
            else:
                outcome = "tie"     # disagreement across orders = tie by protocol
            tally[outcome] += 1
            detail.append({"qid": qid, "outcome": outcome,
                           "order1": w1, "order2": w2,
                           "reason1": r1.get("reason", ""),
                           "reason2": r2.get("reason", "")})
            print(f"[pairwise] {challenger} {qid}: {outcome} (o1={w1}, o2={w2})")
        report["pairs"][challenger] = {"tally": dict(tally), "detail": detail}

    out_path = exp_dir / "pairwise.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[pairwise] wrote {out_path}")
    for ch, res in report["pairs"].items():
        print(f"  {args.baseline} vs {ch}: {res['tally']}")


if __name__ == "__main__":
    main()
