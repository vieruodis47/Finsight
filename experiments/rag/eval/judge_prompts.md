# Judge Prompts — v3 (2026-07-10)

Versioned rubrics for all LLM-judged scoring. Every result file records `judge_prompt_version: 3` and the judge model id. Changing any prompt = v4 of this file; scores across versions are not comparable.

**v2→v3 history (both revisions made 2026-07-10 BEFORE any valid judging ran — the only v2-stamped scores were produced by a scorer bug that routed judge calls to the generation model, and were deleted):**
1. (v2) R1 is issued as ONE batched call per answer scoring ALL gold claims (same rubric per claim, per-claim scores returned); rubric semantics unchanged.
2. (v3) R2 faithfulness, R3 citation support, and the chunk-relevance check for precision@k are issued as ONE combined call per answer with three independently-instructed checks. Rubric wording preserved per check.
3. (v3) R3 citation support sampled: max 2 tagged sentences per answer (deterministic: first 2 valid tags in answer order, uniform across variants).
4. (v3) Judge model = `gemma-4-31b-it` for ALL experiments (temp 0). Chosen 2026-07-10 pre-scoring after the 2.5-generation models proved closed to new API users (404) and gemini-3.5-flash returned 503s: gemma is a different model family from the generator (blinding intact), returns clean rubric JSON (probe-verified), and its free-tier daily quota comfortably fits all judging under ONE judge — which also removes the per-experiment judge split originally planned here.

Rationale: free-tier budget measured 2026-07-10 — generate_content = 15 RPM and 500 requests/day/model. Separate-call judging (~6 calls/run × 720 runs) cannot fit; combined-call judging (~1.6 calls/run) fits each experiment in one model-day.

## Blinding protocol (applies to every judged call)

1. The judge NEVER sees: variant name, config, trace, latency, or anything identifying which architecture produced an answer. Strip before judging.
2. Pairwise comparisons randomize A/B order per question AND run each pair in both orders; a "win" must survive order-swap (else score it a tie).
3. Judge model: fixed per experiment, recorded in the pre-registration. It may be the same family as the generator but must never be the variant under test itself.
4. Judge temperature 0.

---

## R1 — Correctness rubric (batched: all expected_facts of one answer per call)

SYSTEM: You are a strict financial QA grader. Judge each gold claim independently, only against that claim; do not reward plausible-sounding content. Output JSON only.

USER:
```
Question: {question}
(Consider fiscal period: {fiscal_period})

Gold claims the answer should contain:
(1) {claim_1}
(2) {claim_2}
...

Answer to grade:
{answer}

Score EACH claim independently:
2 = answer states the gold claim correctly, with the right fiscal period
1 = answer states it partially/vaguely, or correct fact with unclear period
0 = answer omits or contradicts the gold claim, or uses the wrong period

Return: {"scores": [{"claim": 1, "score": 0|1|2, "evidence_quote": "<shortest quote>", "reason": "<one sentence>"}, ...]}  (one entry per claim, in order)
```

## R2 — Faithfulness rubric (per answer)

SYSTEM: You are auditing whether an answer is grounded in its source context. You do not care whether the answer is *true* — only whether it is *supported by the provided context*. Output JSON only.

USER:
```
Retrieved context shown to the model:
{retrieved_context}

Answer:
{answer}

Score:
2 = every factual claim about the company is supported by the context
1 = minor unsupported details, none material to the conclusion
0 = at least one material claim is absent from or contradicted by the context

Return: {"score": 0|1|2, "unsupported_claims": ["..."], "reason": "<one sentence>"}
```

## R3 — Citation support (per tagged sentence)

(Validity — tag refers to a chunk that exists in this run's retrieved set — is checked programmatically first; R3 judges only valid tags.)

SYSTEM: You verify citations. Output JSON only.

USER:
```
Sentence with citation: {sentence}
Cited chunk [{tag}]:
{chunk_text}

Does the cited chunk support the sentence's factual content?
Return: {"supported": true|false, "reason": "<one sentence>"}
```

## R4 — Pairwise A/B (close calls: overall correctness delta < 0.05)

SYSTEM: You are comparing two answers to the same financial research question. Prefer factual accuracy with correct fiscal periods, then completeness, then clarity. Formatting niceness is NOT a criterion. Output JSON only.

USER:
```
Question: {question}
Gold facts: {expected_facts_claims}

Answer A:
{answer_a}

Answer B:
{answer_b}

Return: {"winner": "A"|"B"|"tie", "reason": "<two sentences max>"}
```

---

## Numeric matcher spec (deterministic — NOT a prompt; implement in code)

For `check: "numeric"` facts, no LLM is involved:
1. Extract all numeric quantities from the answer with units/scale normalization ($391.0B == $391,035 million == 391035000000 USD).
2. A fact matches if some extracted value is within `tolerance` (relative) of gold `value` AND the surrounding sentence references the gold fiscal period (year string or unambiguous period phrase).
3. Wrong-period matches score 0 even when the number is right.
4. If extraction is ambiguous (no parseable number near a period reference), fall back to R1 with the numeric claim spelled out — and log the fallback.

## Human spot-check

Per experiment: sample ~10% of judged items (stratified across variants and rubrics), a human re-scores them blind, disagreements logged in the experiment report with the judge's reason vs the human's. Persistent disagreement pattern = revise prompts (v2), rerun affected scoring.
