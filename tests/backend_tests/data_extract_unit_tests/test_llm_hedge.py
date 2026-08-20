"""
B2 hedged-LLM-stream guardrails (backend.data_extract.rag._hedged_stream).

Proves the two required safety properties without any network:
  (b1) the abandoned (loser) attempt's tokens NEVER reach the output stream;
  (b2) the winner is a SINGLE coherent attempt (no interleaving), so citation
       validation (run on the accumulated text) always sees one generation;
  and the cost guardrail: at most `max_attempts` attempts are ever launched, and
  a hedge only fires when the first attempt stalls past the delay.
"""
import time

from backend.data_extract.rag import _hedged_stream


def _slow_then(tokens, first_delay):
    """A stream that waits `first_delay` before its first token, then yields fast."""
    def gen(_aid):
        def it():
            time.sleep(first_delay)
            for t in tokens:
                yield t
        return it()
    return gen


def test_loser_tokens_never_reach_output():
    # attempt 0 stalls past the hedge delay; attempt 1 (hedged in) answers first.
    # attempt 0's tokens are a DISJOINT set, so any leak would be detectable.
    launched = []
    def make(aid):
        if aid == 0:
            def it():
                time.sleep(0.30)
                yield "LOSER-1"; yield "LOSER-2"; yield "LOSER-3"
            return it()
        def it():
            yield "WIN-a"; yield "WIN-b"
        return it()

    out = list(_hedged_stream(make, hedge_delay_s=0.05, max_attempts=2,
                              on_attempt=launched.append))

    assert out == ["WIN-a", "WIN-b"]                 # winner is the sole source
    assert not any(t.startswith("LOSER") for t in out)  # (b1) loser fully discarded
    assert launched == [0, 1]                        # hedge fired exactly once (2 attempts)


def test_no_hedge_when_first_attempt_is_fast():
    launched = []
    def make(aid):
        def it():
            yield "A1"; yield "A2"
        return it()

    out = list(_hedged_stream(make, hedge_delay_s=0.20, max_attempts=2,
                              on_attempt=launched.append))

    assert out == ["A1", "A2"]
    assert launched == [0]        # no stall -> no hedge -> cost multiplier 1x


def test_output_is_a_single_coherent_attempt():
    # Even with both attempts producing, output equals exactly one attempt's tokens
    # (never interleaved), so end-of-stream citation validation sees one generation.
    def make(aid):
        toks = ["X1", "X2", "X3"] if aid == 0 else ["Y1", "Y2", "Y3"]
        delay = 0.30 if aid == 0 else 0.0
        return _slow_then(toks, delay)(aid)

    out = list(_hedged_stream(make, hedge_delay_s=0.05, max_attempts=2))
    assert out in (["X1", "X2", "X3"], ["Y1", "Y2", "Y3"])
    assert not (set(out) & {"X1"} and set(out) & {"Y1"})   # no interleaving


def test_winner_error_midstream_propagates():
    def make(aid):
        def it():
            yield "ok-1"
            raise RuntimeError("stream broke")
        return it()

    got = []
    try:
        for t in _hedged_stream(make, hedge_delay_s=0.20, max_attempts=1):
            got.append(t)
        assert False, "expected the mid-stream error to propagate"
    except RuntimeError as exc:
        assert "stream broke" in str(exc)
    assert got == ["ok-1"]   # partial tokens before the error still streamed


def test_first_attempt_error_before_token_falls_through_to_hedge():
    # attempt 0 errors before any token; attempt 1 must still win.
    def make(aid):
        if aid == 0:
            def it():
                raise RuntimeError("attempt 0 died")
                yield  # noqa: unreachable — makes this a generator
            return it()
        def it():
            yield "B1"; yield "B2"
        return it()

    out = list(_hedged_stream(make, hedge_delay_s=0.05, max_attempts=2))
    assert out == ["B1", "B2"]
