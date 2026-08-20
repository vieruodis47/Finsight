"""
backend/obs.py — lightweight, dependency-optional latency instrumentation.

Phase 1 of the latency work needs per-stage timing for the chat pipeline
(classification, query embedding, RavenDB vector search, SPARQL, prompt
assembly, LLM time-to-first-token, generation) WITHOUT changing any answer or
citation behaviour. This module provides:

  * `collect()` — a context manager that binds a per-request `Timings`
    collector to a contextvar for the duration of one chat request.
  * `stage(name)` — a context manager that measures wall-clock (perf_counter)
    for a named stage and records it into the active collector, and ALSO opens
    an OpenTelemetry span when OTel is available and enabled.
  * `bind_context()` — returns a copied contextvars.Context so the active
    collector propagates into ThreadPoolExecutor worker threads (the "both"
    retrieval path fans graph + vector out across threads).

Design constraints:
  * Zero hard dependency: OpenTelemetry is imported behind try/except and only
    wired to a real exporter when FINSIGHT_OTEL=1, so the module is a no-op cost
    (a perf_counter pair + dict write) in normal runs.
  * Additive only: nothing here alters retrieval, generation, or citations. The
    per-request timings are surfaced in the chat stream's terminal `done` event
    under a `timings` key, which existing clients ignore.
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger("finsight.perf")

# --- OpenTelemetry (optional) ----------------------------------------------
# Spans are emitted only when the SDK is importable AND FINSIGHT_OTEL=1, so the
# common path pays nothing and CI/local runs without the OTel packages still work.
_tracer = None
if os.getenv("FINSIGHT_OTEL") == "1":
    try:  # pragma: no cover - exercised only when OTel is installed + enabled
        from opentelemetry import trace as _otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        if not isinstance(_otel_trace.get_tracer_provider(), TracerProvider):
            _provider = TracerProvider()
            _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            _otel_trace.set_tracer_provider(_provider)
        _tracer = _otel_trace.get_tracer("finsight.chat")
        logger.info("OpenTelemetry tracing enabled (console exporter)")
    except Exception as exc:  # pragma: no cover
        logger.warning("FINSIGHT_OTEL=1 but OpenTelemetry unavailable: %s", exc)
        _tracer = None


class Timings:
    """Ordered accumulator of stage -> milliseconds for one request.

    `add` sums repeated stages (e.g. two LLM segments in a "both" answer) so the
    reported number is the total time spent in that stage across the request.
    """

    __slots__ = ("stages", "_order", "meta")

    def __init__(self) -> None:
        self.stages: dict[str, float] = {}
        self._order: list[str] = []
        # Non-timing per-request telemetry (e.g. routing: classified vs served
        # path, whether the graph→vector fallback fired). Surfaced alongside the
        # stage timings in the chat `done` event.
        self.meta: dict[str, object] = {}

    def add(self, name: str, ms: float) -> None:
        if name not in self.stages:
            self._order.append(name)
        self.stages[name] = self.stages.get(name, 0.0) + ms

    def as_dict(self) -> dict[str, float]:
        # Round to 1 decimal ms; preserve first-seen order for readability.
        return {k: round(self.stages[k], 1) for k in self._order}


_current: "contextvars.ContextVar[Optional[Timings]]" = contextvars.ContextVar(
    "finsight_timings", default=None
)


@contextmanager
def collect() -> Iterator[Timings]:
    """Bind a fresh `Timings` collector for the duration of one request."""
    coll = Timings()
    token = _current.set(coll)
    try:
        yield coll
    finally:
        # A streaming response resumes this generator across different contexts
        # between next() calls (Starlette iterates a sync generator via the
        # threadpool), so the token can be "created in a different Context".
        # reset() then raises; fall back to clearing the var. Each request sets
        # its own collector at the top of its generator, so not restoring a prior
        # value is harmless (there is no nesting here).
        try:
            _current.reset(token)
        except ValueError:
            _current.set(None)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Time a named stage into the active collector (if any) and an OTel span."""
    coll = _current.get()
    span_cm = _tracer.start_as_current_span(name) if _tracer is not None else None
    if span_cm is not None:
        span_cm.__enter__()
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if coll is not None:
            coll.add(name, dt_ms)
        if span_cm is not None:
            span_cm.__exit__(None, None, None)


def set_meta(**kw: object) -> None:
    """Attach non-timing telemetry (routing decision, fallback flags) to the
    active request collector. No-op outside a `collect()` scope."""
    coll = _current.get()
    if coll is not None:
        coll.meta.update(kw)


def record(name: str, ms: float) -> None:
    """Record a pre-measured duration (for spans computed outside `stage`, e.g.
    time-to-first-token measured across a streaming loop)."""
    coll = _current.get()
    if coll is not None:
        coll.add(name, ms)


def bind_context() -> "contextvars.Context":
    """Snapshot the current context so the active collector propagates into
    worker threads: `pool.submit(bind_context().run, fn, *args)`."""
    return contextvars.copy_context()
