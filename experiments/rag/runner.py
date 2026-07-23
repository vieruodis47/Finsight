"""
experiments/rag/runner.py — shared eval runner for ALL RAG variants.

Implements the run protocol from .claude/agents/rag-experiment.md and the raw
record format from experiments/rag/README.md. One runner for every variant —
never forked per architecture.

Usage (from repo root, venv active, RavenDB + Gemini creds available):

    python experiments/rag/runner.py --exp E-1 --variants naive \
        --eval experiments/rag/eval/questions.v1.jsonl --repeats 3 --k 5

    python experiments/rag/runner.py --exp E-2 \
        --variants naive,graph,hyde,agentic,modular \
        --eval experiments/rag/eval/questions.v1.jsonl --repeats 3

Behavior:
  - n repeats per question per variant; errors/timeouts recorded, never skipped.
  - Resume-safe: existing (variant, qid, repeat) lines are not re-run.
  - Per-call timeout (default 300s) enforced via worker thread.
  - config_hash covers variant configs + eval set digest + k + model, so a
    result file is traceable to the exact substrate that produced it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

JUDGE_PROMPT_VERSION = 2


def _load_questions(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate question ids in eval set"
    return rows


def _config_hash(variant_configs: dict, eval_digest: str, k: int, repeats: int) -> str:
    payload = json.dumps(
        {"configs": variant_configs, "eval": eval_digest, "k": k,
         "repeats": repeats, "judge_prompt_version": JUDGE_PROMPT_VERSION},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Infrastructure-failure signatures: these records are re-run on resume
# (quota exhaustion is an environment artifact, not a variant failure — same
# logic as SCHEMA.md's unindexed-filing rule). Genuine variant errors
# (timeouts, code faults) are kept and score 0 per METRICS.md.
_INFRA_ERROR_MARKERS = ("DailyQuotaExceededError", "PerMinuteQuotaError",
                        "RESOURCE_EXHAUSTED", "429")


def _existing_keys(out_path: Path) -> set:
    """Load completed (qid, repeat) pairs; purge quota-artifact records from
    the file so they are re-run instead of baked in by resume."""
    done = set()
    if not out_path.exists():
        return done
    kept_lines = []
    purged = 0
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        err = r.get("error") or ""
        if err and any(m in err for m in _INFRA_ERROR_MARKERS):
            purged += 1
            continue
        kept_lines.append(line)
        done.add((r["qid"], r["repeat"]))
    if purged:
        out_path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""),
                            encoding="utf-8")
        print(f"[runner] purged {purged} quota-artifact records from {out_path.name} "
              f"(will re-run); kept {len(kept_lines)}")
    return done


def _call_with_timeout(fn, timeout_s: float, **kwargs):
    """Run fn in a worker thread; on timeout return None (caller records it)."""
    box: dict = {}

    def worker():
        try:
            box["result"] = fn(**kwargs)
        except Exception as e:  # variant contract catches internally, but belt+braces
            box["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return None, "timeout"
    return box.get("result"), box.get("error")


def main() -> None:
    ap = argparse.ArgumentParser(description="FinSight RAG experiment runner")
    ap.add_argument("--exp", required=True, help="experiment id, e.g. E-1")
    ap.add_argument("--variants", required=True, help="comma-separated registry names")
    ap.add_argument("--eval", required=True, help="path to questions.v<N>.jsonl")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds per call")
    ap.add_argument("--questions", default="", help="optional comma-separated qid filter")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="pause between calls (rate-limit kindness)")
    args = ap.parse_args()

    from backend.data_extract.rag_variants import registry

    eval_path = Path(args.eval)
    questions = _load_questions(eval_path)
    if args.questions:
        keep = set(args.questions.split(","))
        questions = [q for q in questions if q["id"] in keep]
    eval_digest = hashlib.sha256(eval_path.read_bytes()).hexdigest()[:16]

    variant_names = [v.strip() for v in args.variants.split(",") if v.strip()]
    variant_fns = {name: registry.get(name) for name in variant_names}

    # config hash: pull each variant's CONFIG via a probe of the module attr
    configs = {}
    for name in variant_names:
        mod = sys.modules[variant_fns[name].__module__]
        cfg = None
        for attr in ("CONFIG", f"CONFIG_{name.split('_')[-1].upper()}"):
            cfg = getattr(mod, attr, None)
            if isinstance(cfg, dict) and cfg.get("variant") == name:
                break
            cfg = None
        if cfg is None:  # prompting module holds several configs
            for attr in dir(mod):
                val = getattr(mod, attr)
                if isinstance(val, dict) and val.get("variant") == name:
                    cfg = val
                    break
        configs[name] = cfg or {"variant": name}
    config_hash = _config_hash(configs, eval_digest, args.k, args.repeats)

    results_dir = _REPO / "experiments" / "rag" / "results" / args.exp
    results_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "exp": args.exp,
        "eval_file": str(eval_path),
        "eval_digest": eval_digest,
        "k": args.k,
        "repeats": args.repeats,
        "variants": variant_names,
        "configs": configs,
        "config_hash": config_hash,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (results_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    total = len(variant_names) * len(questions) * args.repeats
    done_count = 0
    print(f"[runner] {args.exp}: {len(questions)} questions x "
          f"{len(variant_names)} variants x {args.repeats} repeats = {total} runs "
          f"(config {config_hash})")

    for name in variant_names:
        fn = variant_fns[name]
        out_path = results_dir / f"{name}.jsonl"
        done = _existing_keys(out_path)
        with out_path.open("a", encoding="utf-8") as out:
            for q in questions:
                for rep in range(1, args.repeats + 1):
                    if (q["id"], rep) in done:
                        done_count += 1
                        continue
                    t0 = time.perf_counter()
                    result, err = _call_with_timeout(
                        fn, args.timeout, question=q["question"], k=args.k
                    )
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)

                    if result is None:
                        record = {
                            "exp": args.exp, "variant": name, "qid": q["id"],
                            "repeat": rep, "answer": "", "sources": [],
                            "trace": [], "llm_call_inputs": [],
                            "prompt_tokens": 0, "completion_tokens": 0,
                            "latency_ms": elapsed_ms, "retrieval_calls": 0,
                            "llm_calls": 0, "config_hash": config_hash,
                            "judge_prompt_version": JUDGE_PROMPT_VERSION,
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "error": err or "unknown",
                        }
                    else:
                        record = {
                            "exp": args.exp, "variant": name, "qid": q["id"],
                            "repeat": rep, "answer": result.answer,
                            "sources": result.sources, "trace": result.trace,
                            "llm_call_inputs": result.call_inputs,
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                            "latency_ms": result.latency_ms,
                            "retrieval_calls": result.retrieval_calls,
                            "llm_calls": result.llm_calls,
                            "config_hash": config_hash,
                            "judge_prompt_version": JUDGE_PROMPT_VERSION,
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "error": result.error,
                        }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
                    done_count += 1
                    status = "ERR " if record["error"] else "ok  "
                    print(f"[runner] {done_count}/{total} {status} {name} "
                          f"{q['id']} r{rep} {record['latency_ms']}ms "
                          f"pt={record['prompt_tokens']} ct={record['completion_tokens']}")
                    time.sleep(args.sleep)

    print(f"[runner] complete: {done_count}/{total} runs in {results_dir}")


if __name__ == "__main__":
    main()
