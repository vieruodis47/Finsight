"""
Gemini rate limiter + 429 backoff helpers (backend.data_extract.rag).

Deterministic: the limiter takes injectable clock/sleep, so no real time passes.
"""
from backend.data_extract.rag import RateLimiter, _is_rate_limit, _retry_delay_s


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_limiter_allows_burst_up_to_max_then_queues():
    fc = FakeClock()
    lim = RateLimiter(max_per_window=3, window_s=60.0, clock=fc.now, sleep=fc.sleep)
    # First `max` acquisitions are immediate.
    assert lim.acquire() == 0.0
    assert lim.acquire() == 0.0
    assert lim.acquire() == 0.0
    # The next one must wait until the oldest hit ages out of the window.
    waited = lim.acquire()
    assert 60.0 <= waited <= 60.1
    assert fc.t >= 60.0


def test_limiter_no_wait_when_spread_out():
    fc = FakeClock()
    lim = RateLimiter(max_per_window=2, window_s=60.0, clock=fc.now, sleep=fc.sleep)
    assert lim.acquire() == 0.0
    fc.t = 61.0                      # first hit is now outside the window
    assert lim.acquire() == 0.0      # so this is immediate
    assert lim.acquire() == 0.0      # window holds 1 -> still room for 1 more


def test_is_rate_limit_detects_429_and_resource_exhausted():
    assert _is_rate_limit(Exception("429 RESOURCE_EXHAUSTED. quota exceeded"))
    assert _is_rate_limit(Exception("RESOURCE_EXHAUSTED"))

    class E(Exception):
        code = 429
    assert _is_rate_limit(E("boom"))
    assert not _is_rate_limit(Exception("500 internal error"))


def test_retry_delay_parses_both_server_formats():
    # RetryInfo dict form
    assert _retry_delay_s(Exception("... 'retryDelay': '15s' ...")) == 15.0
    # human "retry in Ns" form
    assert _retry_delay_s(Exception("Please retry in 14.798795168s.")) == 14.798795168
    # none present
    assert _retry_delay_s(Exception("no delay here")) is None
