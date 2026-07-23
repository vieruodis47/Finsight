"""
experiments/rag/scorer.py — scores raw run records per METRICS.md v1, exactly.

One scorer for every variant. Implements:

  - Correctness: two-tier — deterministic numeric matcher (spec at the bottom
    of eval/judge_prompts.md), LLM judge R1 for judged facts and for logged
    numeric-extraction fallbacks. Question score = mean over expected_facts.
  - Retrieval quality: recall@k / precision@k / MRR vs expected_sources
    (match rule: ticker+form + fiscal-year window + section-hint keyword
    overlap; granularity recorded in the output).
  - Faithfulness: R2 against the LLM inputs captured at run time (the exact
    context each model call saw).
  - Citation accuracy: validity (programmatic) + support (R3, judged).
  - Cost: passthrough of tokens/latency/calls from the raw records.
  - Slicing: per question type + overall; post_cutoff subset; aggregation
    facts-found ratio.

Judge calls are blinded (no variant identity in any judge prompt), temp 0,
cached on disk keyed by (rubric, model, inputs) so re-scoring is free.

Usage:
    python experiments/rag/scorer.py --exp E-1 --eval experiments/rag/eval/questions.v1.jsonl
    python experiments/rag/scorer.py --exp E-2 --eval ... --variants naive,graph
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / "backend" / ".env.python")
except ImportError:
    pass

JUDGE_PROMPT_VERSION = 3  # v3: batched R1 + one combined R2/R3/relevance call per run
JUDGE_MODEL = os.getenv("GEMINI_JUDGE_MODEL", "gemini-2.5-flash")
R3_MAX_JUDGED = 2  # citation-support sample cap per answer (deterministic: first N valid tags)
JUDGE_MIN_INTERVAL_S = float(os.getenv("JUDGE_MIN_INTERVAL_S", "4.2"))  # 15 RPM cap

# ---------------------------------------------------------------------------
# Deterministic numeric matcher (judge_prompts.md spec — NOT a prompt)
# ---------------------------------------------------------------------------

_SCALE_WORDS = {
    "trillion": 1e12, "t": 1e12, "tn": 1e12,
    "billion": 1e9, "b": 1e9, "bn": 1e9,
    "million": 1e6, "m": 1e6, "mm": 1e6,
    "thousand": 1e3, "k": 1e3,
}

_NUM_RE = re.compile(
    r"(?<![\w.])\$?\s*(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"\s*(trillion|billion|million|thousand|tn|bn|mm|[tbmk])?(?![\w%])",
    re.IGNORECASE,
)
_PCT_RE = re.compile(
    r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(?:%|percent(?:age points?)?)", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(?:fy\s*'?|fiscal\s+(?:year\s+)?)?(20\d{2})\b", re.IGNORECASE)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def extract_numbers(sentence: str) -> list[float]:
    """All scaled numeric quantities in a sentence (non-percent)."""
    out = []
    for m in _NUM_RE.finditer(sentence):
        raw, scale = m.group(1), (m.group(2) or "").lower()
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if scale in _SCALE_WORDS:
            val *= _SCALE_WORDS[scale]
        out.append(val)
    return out


def extract_percents(sentence: str) -> list[float]:
    return [float(m.group(1)) for m in _PCT_RE.finditer(sentence)]


def sentence_years(sentence: str) -> set[str]:
    return set(_YEAR_RE.findall(sentence))


def gold_years(fiscal_period) -> set[str]:
    periods = fiscal_period if isinstance(fiscal_period, list) else [fiscal_period]
    years = set()
    for p in periods:
        years.update(re.findall(r"20\d{2}", str(p)))
    return years


def _fact_years(fact: dict, question_years: set[str]) -> set[str]:
    src = fact.get("source") or {}
    fy = src.get("fiscal_year")
    return {str(fy)} if fy else question_years


def match_numeric_fact(answer: str, fact: dict, question_years: set[str]) -> tuple:
    """
    Returns (score, detail) where score is 1.0 / 0.0 / None.
    None = ambiguous extraction -> caller falls back to judge R1 (logged).
    Wrong-period matches score 0 even when the number is right (spec rule 3).
    """
    gold_val = fact.get("value")
    if gold_val in (None, ""):
        return None, "gold value missing — authoring error, judge fallback"
    gold_val = float(gold_val)
    tol = float(fact.get("tolerance", 0.005))
    unit = (fact.get("unit") or "").upper()
    want_years = _fact_years(fact, question_years)

    is_pct = unit in ("%", "PCT", "PERCENT")
    found_wrong_period = False
    found_no_period = False

    for sent in split_sentences(answer):
        values = extract_percents(sent) if is_pct else extract_numbers(sent)
        hit = any(
            abs(v - gold_val) <= tol * abs(gold_val) if gold_val else abs(v) <= tol
            for v in values
        )
        if not hit:
            continue
        yrs = sentence_years(sent)
        if yrs & want_years:
            return 1.0, f"matched in-period ({sorted(yrs & want_years)})"
        if yrs:
            found_wrong_period = True
        else:
            found_no_period = True

    if found_no_period:
        return None, "value matched but no period reference in sentence — judge fallback"
    if found_wrong_period:
        return 0.0, "value matched only with wrong fiscal period"
    return 0.0, "no matching value found"


# ---------------------------------------------------------------------------
# Judge client (blinded, temp 0, disk-cached)
# ---------------------------------------------------------------------------

class Judge:
    def __init__(self, cache_path: Path, model: str = JUDGE_MODEL):
        self.model = model
        self.cache_path = cache_path
        self.cache: dict[str, dict] = {}
        self.calls = 0
        self.cache_hits = 0
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    self.cache[row["key"]] = row["value"]
                except Exception:
                    continue

    _last_call_at = 0.0

    def _throttle(self) -> None:
        wait = Judge._last_call_at + JUDGE_MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        Judge._last_call_at = time.monotonic()

    def _ask(self, system: str, user: str) -> dict:
        key = hashlib.sha256(
            f"{self.model}|v{JUDGE_PROMPT_VERSION}|{system}|{user}".encode()
        ).hexdigest()
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]

        from backend.data_extract.rag_variants.common import llm_json
        for attempt in range(3):
            self._throttle()
            out = llm_json(user, system=system, temperature=0.0, model=self.model)
            if isinstance(out, dict):
                break
            time.sleep(2 * (attempt + 1))
        else:
            out = {}
        self.calls += 1
        self.cache[key] = out
        with self.cache_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "value": out}) + "\n")
        return out

    # R1 — correctness, batched: ALL gold claims of one answer in one call (v2)
    def correctness_batch(self, question: str, claims: list[str], fiscal_period,
                          answer: str) -> list[dict]:
        """Returns one {'score': 0|1|2, 'reason': ...} dict per claim, in order."""
        system = ("You are a strict financial QA grader. Judge each gold claim "
                  "independently, only against that claim; do not reward "
                  "plausible-sounding content. Output JSON only.")
        numbered = "\n".join(f"({i + 1}) {c}" for i, c in enumerate(claims))
        user = (
            f"Question: {question}\n"
            f"(Consider fiscal period: {fiscal_period})\n\n"
            f"Gold claims the answer should contain:\n{numbered}\n\n"
            f"Answer to grade:\n{answer}\n\n"
            "Score EACH claim independently:\n"
            "2 = answer states the gold claim correctly, with the right fiscal period\n"
            "1 = answer states it partially/vaguely, or correct fact with unclear period\n"
            "0 = answer omits or contradicts the gold claim, or uses the wrong period\n\n"
            'Return: {"scores": [{"claim": 1, "score": 0|1|2, "evidence_quote": '
            '"<shortest quote>", "reason": "<one sentence>"}, ...]} '
            "(one entry per claim, in order)"
        )
        out = self._ask(system, user)
        rows = out.get("scores") if isinstance(out, dict) else None
        if not isinstance(rows, list):
            return [{"score": 0, "reason": "judge output unparseable"} for _ in claims]
        result = []
        for i in range(len(claims)):
            row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
            result.append({"score": row.get("score", 0) or 0,
                           "reason": row.get("reason", "")})
        return result

    # v3 combined call: R2 faithfulness + R3 citation support (sampled) +
    # chunk relevance for precision@k — one call per run.
    def combined_quality(self, question: str, retrieved_context: str, answer: str,
                         citation_items: list, relevance_previews: list) -> dict:
        """
        citation_items: [(sentence, tag, chunk_text), ...] (<= R3_MAX_JUDGED)
        relevance_previews: ["[TICK FORM] text...", ...]
        Returns {"faithfulness": int|None, "citations": [bool...], "relevant": [bool...]}
        """
        cit_block = "\n\n".join(
            f"(C{i+1}) Sentence: {s}\n    Cited chunk [{t}]: {c[:1500]}"
            for i, (s, t, c) in enumerate(citation_items)
        ) or "(none)"
        rel_block = "\n\n".join(
            f"(E{i+1}) {p}" for i, p in enumerate(relevance_previews)
        ) or "(none)"
        system = (
            "You audit a financial QA system. Perform THREE independent checks "
            "and output JSON only.\n"
            "CHECK 1 — Grounding: is every factual claim in the answer supported "
            "by the provided context? You do not care whether the answer is true, "
            "only whether the context supports it. "
            "2 = fully supported; 1 = minor unsupported details, none material; "
            "0 = at least one material claim absent from or contradicted by context.\n"
            "CHECK 2 — Citations: for each cited sentence, does its cited chunk "
            "support the sentence's factual content?\n"
            "CHECK 3 — Relevance: is each excerpt relevant to answering the "
            "question (contains information that helps answer it)?"
        )
        user = (
            f"Question: {question}\n\n"
            f"Retrieved context shown to the model:\n{retrieved_context}\n\n"
            f"Answer:\n{answer}\n\n"
            f"Citations to verify:\n{cit_block}\n\n"
            f"Excerpts to rate for relevance:\n{rel_block}\n\n"
            'Return: {"faithfulness": 0|1|2, "unsupported_claims": ["..."], '
            '"citations": [{"n": 1, "supported": true|false}, ...], '
            '"relevant": [true|false, ...]}  '
            "(citations: one entry per C-item in order; relevant: one boolean "
            "per E-item in order)"
        )
        out = self._ask(system, user)
        if not isinstance(out, dict):
            out = {}
        cits = out.get("citations")
        cit_flags = []
        if isinstance(cits, list):
            for i in range(len(citation_items)):
                row = cits[i] if i < len(cits) and isinstance(cits[i], dict) else {}
                cit_flags.append(bool(row.get("supported")))
        else:
            cit_flags = [False] * len(citation_items)
        rel = out.get("relevant")
        rel_flags = [bool(x) for x in rel][:len(relevance_previews)] if isinstance(rel, list) else []
        rel_flags += [False] * (len(relevance_previews) - len(rel_flags))
        faith = out.get("faithfulness")
        return {"faithfulness": faith if faith in (0, 1, 2) else None,
                "citations": cit_flags, "relevant": rel_flags}

    # R2 — faithfulness per answer (0/1/2) — kept for spot-check tooling
    def faithfulness(self, retrieved_context: str, answer: str) -> dict:
        system = ("You are auditing whether an answer is grounded in its source "
                  "context. You do not care whether the answer is *true* — only "
                  "whether it is *supported by the provided context*. "
                  "Output JSON only.")
        user = (
            f"Retrieved context shown to the model:\n{retrieved_context}\n\n"
            f"Answer:\n{answer}\n\n"
            "Score:\n"
            "2 = every factual claim about the company is supported by the context\n"
            "1 = minor unsupported details, none material to the conclusion\n"
            "0 = at least one material claim is absent from or contradicted by the context\n\n"
            'Return: {"score": 0|1|2, "unsupported_claims": ["..."], '
            '"reason": "<one sentence>"}'
        )
        return self._ask(system, user)

    # R3 — citation support per tagged sentence
    def citation_support(self, sentence: str, tag: str, chunk_text: str) -> dict:
        system = "You verify citations. Output JSON only."
        user = (
            f"Sentence with citation: {sentence}\n"
            f"Cited chunk [{tag}]:\n{chunk_text}\n\n"
            "Does the cited chunk support the sentence's factual content?\n"
            'Return: {"supported": true|false, "reason": "<one sentence>"}'
        )
        return self._ask(system, user)

    # Relevance (for precision@k on non-gold chunks) — batched per run
    def chunk_relevance(self, question: str, previews: list[str]) -> list[bool]:
        if not previews:
            return []
        system = ("You judge whether SEC filing excerpts are relevant to a "
                  "question. An excerpt is relevant if it contains information "
                  "that helps answer the question. Output JSON only.")
        numbered = "\n\n".join(f"({i+1}) {p}" for i, p in enumerate(previews))
        user = (
            f"Question: {question}\n\nExcerpts:\n{numbered}\n\n"
            'Return: {"relevant": [true|false, ...]}  '
            "(one boolean per excerpt, in order)"
        )
        out = self._ask(system, user)
        flags = out.get("relevant") if isinstance(out, dict) else None
        if not isinstance(flags, list):
            return [False] * len(previews)
        flags = [bool(x) for x in flags][:len(previews)]
        flags += [False] * (len(previews) - len(flags))
        return flags

    # R4 — pairwise A/B (used by the verdict step for close calls)
    def pairwise(self, question: str, gold_claims: list[str],
                 answer_a: str, answer_b: str) -> dict:
        system = ("You are comparing two answers to the same financial research "
                  "question. Prefer factual accuracy with correct fiscal periods, "
                  "then completeness, then clarity. Formatting niceness is NOT a "
                  "criterion. Output JSON only.")
        user = (
            f"Question: {question}\n"
            f"Gold facts: {json.dumps(gold_claims)}\n\n"
            f"Answer A:\n{answer_a}\n\n"
            f"Answer B:\n{answer_b}\n\n"
            'Return: {"winner": "A"|"B"|"tie", "reason": "<two sentences max>"}'
        )
        return self._ask(system, user)


# ---------------------------------------------------------------------------
# Retrieval matching (recall / precision / MRR)
# ---------------------------------------------------------------------------

_HINT_STOP = {"the", "a", "an", "of", "and", "or", "item", "-", "&", "to", "in",
              "for", "on", "section", "note", "notes"}

MATCH_GRANULARITY = (
    "chunk matches gold source iff ticker+form equal AND filing year within "
    "[fiscal_year, fiscal_year+1] (blank filing_date passes) AND >=50% of "
    "section_hint keywords appear in chunk text"
)


def _hint_keywords(hint: str) -> list[str]:
    toks = re.findall(r"[a-z0-9&]+", (hint or "").lower())
    return [t for t in toks if t not in _HINT_STOP and len(t) > 1]


def chunk_matches_source(chunk: dict, gold: dict) -> bool:
    if (chunk.get("ticker") or "").upper() != (gold.get("ticker") or "").upper():
        return False
    if (chunk.get("form") or "") != (gold.get("form") or ""):
        return False
    fy = gold.get("fiscal_year")
    fdate = chunk.get("filing_date") or ""
    if fy and fdate[:4].isdigit():
        if not (int(fy) <= int(fdate[:4]) <= int(fy) + 1):
            return False
    kws = _hint_keywords(gold.get("section_hint", ""))
    if not kws:
        return True
    text = (chunk.get("text") or "").lower()
    hits = sum(1 for kw in kws if kw in text)
    return hits >= math.ceil(len(kws) / 2)


def retrieval_metrics(sources: list[dict], expected: list[dict],
                      question: str, judge: Judge) -> dict:
    if not expected:
        return {"recall_at_k": None, "precision_at_k": None, "mrr": None,
                "retrieved": len(sources)}
    if not sources:
        return {"recall_at_k": 0.0, "precision_at_k": 0.0, "mrr": 0.0,
                "retrieved": 0}

    gold_found = [any(chunk_matches_source(c, g) for c in sources) for g in expected]
    recall = sum(gold_found) / len(expected)

    is_gold = [any(chunk_matches_source(c, g) for g in expected) for c in sources]
    non_gold_idx = [i for i, g in enumerate(is_gold) if not g]
    previews = [
        f"[{sources[i].get('ticker')} {sources[i].get('form')}] "
        f"{(sources[i].get('text') or '')[:300]}"
        for i in non_gold_idx
    ]
    relevant_flags = judge.chunk_relevance(question, previews)
    relevant = dict(zip(non_gold_idx, relevant_flags))
    precision = sum(
        1 for i in range(len(sources)) if is_gold[i] or relevant.get(i, False)
    ) / len(sources)

    mrr = 0.0
    for rank, g in enumerate(is_gold):
        if g:
            mrr = 1.0 / (rank + 1)
            break
    return {"recall_at_k": recall, "precision_at_k": precision, "mrr": mrr,
            "retrieved": len(sources)}


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

# One bracket may carry several chunk refs ("[AAPL 10-K #106, #116]") — the
# bracket-level regex grabs ticker+form+the ref blob, then the inner regex
# splits out each #N as its own tag.
_TAG_RE = re.compile(r"\[([A-Z][A-Z.\-]{0,6})\s+(10-[KQ])\s*((?:#\d+[,;\s]*)+)\]")
_TAG_NUM_RE = re.compile(r"#(\d+)")


def _extract_tags(sentence: str):
    """Yield (tag_string, (ticker, form, chunk_index)) for every ref."""
    for m in _TAG_RE.finditer(sentence):
        ticker, form, blob = m.group(1), m.group(2), m.group(3)
        for num in _TAG_NUM_RE.findall(blob):
            yield f"[{ticker} {form} #{num}]", (ticker, form, int(num))


def citation_metrics(answer: str, sources: list[dict], judge: Judge,
                     max_judged: int = R3_MAX_JUDGED) -> dict:
    source_keys = {(s.get("ticker", "").upper(), s.get("form", ""), int(s.get("chunk_index", -1)))
                   for s in sources}
    text_by_key = {
        (s.get("ticker", "").upper(), s.get("form", ""), int(s.get("chunk_index", -1))):
        s.get("text", "") for s in sources
    }

    tags = []
    for sent in split_sentences(answer):
        for tag_str, key in _extract_tags(sent):
            tags.append((sent, tag_str, key))

    if not tags:
        return {"citation_tag_count": 0, "citation_validity": None,
                "citation_support": None}

    valid = [(sent, tag, key) for sent, tag, key in tags if key in source_keys]
    validity = len(valid) / len(tags)

    supported = 0
    judged = 0
    for sent, tag, key in valid[:max_judged]:
        out = judge.citation_support(sent, tag.strip("[]"), text_by_key.get(key, "")[:3000])
        judged += 1
        if out.get("supported") is True:
            supported += 1
    support = (supported / judged) if judged else None
    return {"citation_tag_count": len(tags), "citation_validity": validity,
            "citation_support": support}


# ---------------------------------------------------------------------------
# Scoring one record
# ---------------------------------------------------------------------------

def score_record(rec: dict, q: dict, judge: Judge) -> dict:
    answer = rec.get("answer") or ""
    sources = rec.get("sources") or []
    errored = bool(rec.get("error")) or not answer.strip()
    question_years = gold_years(q.get("fiscal_period"))

    # First pass: deterministic numeric matching; collect judge-needed claims
    # (judged facts + logged numeric fallbacks) for ONE batched R1 call.
    per_fact = []
    judge_queue = []  # (index into per_fact, claim text)
    for fact in q.get("expected_facts", []):
        entry = {"claim": fact.get("claim", ""), "check": fact.get("check")}
        if errored:
            entry.update({"score": 0.0, "method": "errored_run"})
        elif fact.get("check") == "numeric":
            score, detail = match_numeric_fact(answer, fact, question_years)
            if score is None:
                claim = (f"{fact.get('claim')}: value {fact.get('value')} "
                         f"{fact.get('unit', '')}")
                entry.update({"score": None, "method": "numeric_fallback_judge",
                              "matcher_note": detail})
                judge_queue.append((len(per_fact), claim))
            else:
                entry.update({"score": score, "method": "numeric_matcher",
                              "matcher_note": detail})
        else:
            entry.update({"score": None, "method": "judge_r1"})
            judge_queue.append((len(per_fact), fact.get("claim", "")))
        per_fact.append(entry)

    if judge_queue:
        results = judge.correctness_batch(
            q["question"], [c for _, c in judge_queue],
            q.get("fiscal_period"), answer,
        )
        for (idx, _), res in zip(judge_queue, results):
            per_fact[idx]["score"] = (res.get("score", 0) or 0) / 2.0
            per_fact[idx]["judge_reason"] = res.get("reason", "")

    correctness = (sum(f["score"] for f in per_fact) / len(per_fact)) if per_fact else 0.0
    facts_found = sum(1 for f in per_fact if f["score"] > 0)

    # --- programmatic retrieval matching (no judge yet) ---
    expected = q.get("expected_sources", [])
    if not expected:
        ret = {"recall_at_k": None, "precision_at_k": None, "mrr": None,
               "retrieved": len(sources)}
        is_gold, non_gold_idx = [], []
    elif not sources:
        ret = {"recall_at_k": 0.0, "precision_at_k": 0.0, "mrr": 0.0, "retrieved": 0}
        is_gold, non_gold_idx = [], []
    else:
        gold_found = [any(chunk_matches_source(c, g) for c in sources) for g in expected]
        is_gold = [any(chunk_matches_source(c, g) for g in expected) for c in sources]
        non_gold_idx = [i for i, g in enumerate(is_gold) if not g]
        mrr = 0.0
        for rank, g in enumerate(is_gold):
            if g:
                mrr = 1.0 / (rank + 1)
                break
        ret = {"recall_at_k": sum(gold_found) / len(expected),
               "precision_at_k": None,  # filled after the combined judge call
               "mrr": mrr, "retrieved": len(sources)}

    # --- programmatic citation validity + sampled support items ---
    if errored:
        faith = None
        cites = {"citation_tag_count": 0, "citation_validity": None,
                 "citation_support": None}
    else:
        source_keys = {(s.get("ticker", "").upper(), s.get("form", ""),
                        int(s.get("chunk_index", -1))) for s in sources}
        text_by_key = {(s.get("ticker", "").upper(), s.get("form", ""),
                        int(s.get("chunk_index", -1))): s.get("text", "")
                       for s in sources}
        tags = []
        for sent in split_sentences(answer):
            for tag_str, key in _extract_tags(sent):
                tags.append((sent, tag_str, key))
        valid = [(s, t, k) for s, t, k in tags if k in source_keys]
        validity = (len(valid) / len(tags)) if tags else None
        citation_items = [(s, t.strip("[]"), text_by_key.get(k, ""))
                          for s, t, k in valid[:R3_MAX_JUDGED]]

        context = "\n\n=== CALL ===\n\n".join(rec.get("llm_call_inputs") or [])
        if not context and sources:
            context = "\n\n---\n\n".join((s.get("text") or "")[:3000] for s in sources)
        previews = [
            f"[{sources[i].get('ticker')} {sources[i].get('form')}] "
            f"{(sources[i].get('text') or '')[:300]}"
            for i in non_gold_idx
        ]

        combined = judge.combined_quality(
            q["question"], context[:40000] or "(no context captured)", answer,
            citation_items, previews,
        )
        faith = combined["faithfulness"]
        support = (sum(combined["citations"]) / len(citation_items)) if citation_items else None
        cites = {"citation_tag_count": len(tags), "citation_validity": validity,
                 "citation_support": support}
        if ret["precision_at_k"] is None and sources:
            relevant = dict(zip(non_gold_idx, combined["relevant"]))
            ret["precision_at_k"] = sum(
                1 for i in range(len(sources)) if is_gold[i] or relevant.get(i, False)
            ) / len(sources)

    return {
        "exp": rec.get("exp"), "variant": rec.get("variant"),
        "qid": rec.get("qid"), "repeat": rec.get("repeat"),
        "slice": q.get("type"), "post_cutoff": bool(q.get("post_cutoff")),
        "correctness": round(correctness, 4),
        "per_fact": per_fact,
        "facts_found": facts_found, "facts_expected": len(per_fact),
        **ret,
        "faithfulness": faith,
        **cites,
        "prompt_tokens": rec.get("prompt_tokens", 0),
        "completion_tokens": rec.get("completion_tokens", 0),
        "total_tokens": (rec.get("prompt_tokens", 0) or 0) + (rec.get("completion_tokens", 0) or 0),
        "latency_ms": rec.get("latency_ms", 0),
        "retrieval_calls": rec.get("retrieval_calls", 0),
        "llm_calls": rec.get("llm_calls", 0),
        "error": rec.get("error"),
        "judge_model": judge.model,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "match_granularity": MATCH_GRANULARITY,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def _std(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.stdev(xs), 4) if len(xs) > 1 else 0.0


def _p(xs, pct):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    idx = min(len(xs) - 1, max(0, int(round(pct / 100 * (len(xs) - 1)))))
    return xs[idx]


def aggregate(scored: list[dict]) -> dict:
    """Per-slice + overall aggregation for one variant."""
    def block(rows: list[dict]) -> dict:
        # per-question means first (repeats collapse), then mean/std across questions
        by_q = defaultdict(list)
        for r in rows:
            by_q[r["qid"]].append(r)
        q_corr = [_mean([r["correctness"] for r in v]) for v in by_q.values()]
        return {
            "n_questions": len(by_q),
            "n_runs": len(rows),
            "n_errors": sum(1 for r in rows if r.get("error")),
            "correctness_mean": _mean(q_corr),
            "correctness_std_across_questions": _std(q_corr),
            "recall_at_k": _mean([r["recall_at_k"] for r in rows]),
            "precision_at_k": _mean([r["precision_at_k"] for r in rows]),
            "mrr": _mean([r["mrr"] for r in rows]),
            "faithfulness_mean_0to2": _mean([r["faithfulness"] for r in rows]),
            "citation_validity": _mean([r["citation_validity"] for r in rows]),
            "citation_support": _mean([r["citation_support"] for r in rows]),
            "answers_with_citations": _mean(
                [1.0 if (r["citation_tag_count"] or 0) > 0 else 0.0 for r in rows]),
            "facts_found_ratio": (
                round(sum(r["facts_found"] for r in rows) /
                      max(1, sum(r["facts_expected"] for r in rows)), 4)),
            "tokens_per_q_mean": _mean([r["total_tokens"] for r in rows]),
            "prompt_tokens_mean": _mean([r["prompt_tokens"] for r in rows]),
            "completion_tokens_mean": _mean([r["completion_tokens"] for r in rows]),
            "latency_p50_ms": _p([r["latency_ms"] for r in rows], 50),
            "latency_p95_ms": _p([r["latency_ms"] for r in rows], 95),
            "retrieval_calls_mean": _mean([r["retrieval_calls"] for r in rows]),
            "llm_calls_mean": _mean([r["llm_calls"] for r in rows]),
        }

    slices = sorted({r["slice"] for r in scored})
    out = {"overall": block(scored)}
    for s in slices:
        out[s] = block([r for r in scored if r["slice"] == s])
    pc = [r for r in scored if r["post_cutoff"]]
    out["post_cutoff_subset"] = block(pc) if pc else {"n_questions": 0}
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Score RAG experiment results per METRICS.md v1")
    ap.add_argument("--exp", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--variants", default="", help="default: every .jsonl in results dir")
    args = ap.parse_args()

    results_dir = _REPO / "experiments" / "rag" / "results" / args.exp
    scores_dir = results_dir / "scores"
    scores_dir.mkdir(parents=True, exist_ok=True)

    questions = {}
    for line in Path(args.eval).read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            questions[q["id"]] = q

    if args.variants:
        names = [v.strip() for v in args.variants.split(",")]
    else:
        names = sorted(p.stem for p in results_dir.glob("*.jsonl")
                       if p.stem not in ("run_manifest", "judge_cache", "embed_cache"))

    judge = Judge(results_dir / "judge_cache.jsonl")
    summary = {"exp": args.exp, "judge_model": judge.model,
               "judge_prompt_version": JUDGE_PROMPT_VERSION,
               "match_granularity": MATCH_GRANULARITY, "variants": {}}

    for name in names:
        raw_path = results_dir / f"{name}.jsonl"
        if not raw_path.exists():
            print(f"[scorer] SKIP {name}: no raw results at {raw_path}")
            continue
        scored = []
        with (scores_dir / f"{name}.jsonl").open("w", encoding="utf-8") as out:
            for line in raw_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                q = questions.get(rec["qid"])
                if q is None:
                    print(f"[scorer] WARN {name}: unknown qid {rec['qid']}")
                    continue
                s = score_record(rec, q, judge)
                scored.append(s)
                out.write(json.dumps(s, ensure_ascii=False) + "\n")
                print(f"[scorer] {name} {rec['qid']} r{rec['repeat']} "
                      f"corr={s['correctness']} recall={s['recall_at_k']} "
                      f"faith={s['faithfulness']}")
        summary["variants"][name] = aggregate(scored)

    (results_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"[scorer] wrote {results_dir / 'summary.json'} "
          f"(judge calls={judge.calls}, cache hits={judge.cache_hits})")


if __name__ == "__main__":
    main()
