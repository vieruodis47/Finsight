import React, { useState, useRef, useEffect } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { c, font } from '../theme';
import { useElementWidth, usePrefersReducedMotion } from '../utils/hooks';

export interface CarouselSlide {
  key: string;
  label: string;         // announced + shown, e.g. "Revenue vs Net income"
  node: React.ReactNode; // one chart panel (keeps its own description below the chart)
}

// Slides-per-view is driven by the CAROUSEL CONTAINER's width, never
// window.innerWidth — collapsing the sidebar changes the available width without
// changing the window size, and a chart in a 3-up row is only ~1/3 as wide.
function perViewFor(width: number): number {
  if (width >= 1200) return 3;
  if (width >= 768) return 2;
  return 1;
}

/**
 * Responsive chart carousel used at every breakpoint. Charts are grouped into
 * "slides" of `perView` charts (3-up ≥1200px, 2-up ≥768px, 1-up below), with
 * swipe + prev/next buttons + dot indicators. No auto-advance, no looping.
 *
 * Layout: every chart stays in a single flat flex track (never regrouped into
 * different DOM nodes on resize, so stateful charts and their fetches are not
 * remounted). Each chart is `flex: 0 0 (100/perView)%` and the track is
 * translated by `slide * 100%`. Because slides are translated — never
 * display:none — every chart keeps its laid-out width, so each
 * ResponsiveContainer measures a real, non-zero size even off-screen and even
 * after perView changes (its ResizeObserver re-fires on the width change).
 *
 * A11y: real <button>s (tab-reachable, focus-visible), arrow-key nav, a polite
 * live region announcing "Slide N of M: <chart labels>", off-screen slides made
 * `inert` (their charts + <select>s are not tab-reachable), 44px controls, and
 * the transition dropped under prefers-reduced-motion.
 */
export const ChartCarousel: React.FC<{ slides: CarouselSlide[]; label?: string }> = ({
  slides,
  label = 'Analysis charts',
}) => {
  const [containerRef, width] = useElementWidth<HTMLDivElement>();
  const reduced = usePrefersReducedMotion();
  const total = slides.length;

  const perView = perViewFor(width);
  const numSlides = Math.max(1, Math.ceil(total / perView));

  const [slide, setSlide] = useState(0);
  // The first chart index currently in view — the anchor we keep visible when
  // perView changes (e.g. sidebar collapse turns a 3-up into a 2-up).
  const firstChart = useRef(0);
  const prevPerView = useRef(perView);
  const touchStartX = useRef<number | null>(null);

  const go = (s: number) => {
    const clamped = Math.max(0, Math.min(numSlides - 1, s));
    firstChart.current = clamped * perView;
    setSlide(clamped);
  };

  // When perView changes, keep the previously-visible first chart in view rather
  // than snapping to slide 0.
  useEffect(() => {
    if (prevPerView.current !== perView) {
      prevPerView.current = perView;
      const target = Math.min(Math.floor(firstChart.current / perView), Math.ceil(total / perView) - 1);
      firstChart.current = target * perView;
      setSlide(Math.max(0, target));
    }
  }, [perView, total]);

  // Keep the active slide in range if the slide count shrinks.
  useEffect(() => {
    setSlide(s => {
      const clamped = Math.min(s, numSlides - 1);
      firstChart.current = clamped * perView;
      return clamped;
    });
  }, [numSlides, perView]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); go(slide + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(slide - 1); }
  };
  const onTouchStart = (e: React.TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(dx) > 40) go(slide + (dx < 0 ? 1 : -1)); // left swipe → next
    touchStartX.current = null;
  };

  const atStart = slide === 0;
  const atEnd = slide >= numSlides - 1;

  // 44×44 primary controls (WCAG 2.5.5).
  const navBtn = (disabled: boolean): React.CSSProperties => ({
    width: 44, height: 44, flexShrink: 0,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 8, border: `0.5px solid ${c.border}`,
    background: disabled ? c.surfaceAlt : c.bg,
    color: disabled ? c.textFaint : c.text,
    cursor: disabled ? 'not-allowed' : 'pointer',
  });

  // Labels of the charts on the active slide, for the live-region announcement.
  const activeLabels = slides
    .slice(slide * perView, slide * perView + perView)
    .map(s => s.label)
    .join(', ');

  return (
    <div
      ref={containerRef}
      className="chart-carousel"
      // Focusable so Left/Right arrows work "when the carousel has focus" — and
      // robustly: navigating to an end disables that nav button (dropping its
      // focus), so relying on a focused button alone would strand keyboard users.
      tabIndex={0}
      role="group"
      aria-roledescription="carousel"
      aria-label={label}
      onKeyDown={onKeyDown}
      style={{ display: 'flex', flexDirection: 'column', gap: 12, fontFamily: font.ui }}
    >
      {/* Polite live region — announces the active slide + its charts. */}
      <p
        aria-live="polite"
        style={{ position: 'absolute', width: 1, height: 1, margin: -1, padding: 0, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0 }}
      >
        Slide {slide + 1} of {numSlides}: {activeLabels}
      </p>

      {/* Viewport + sliding track */}
      <div style={{ overflow: 'hidden', width: '100%' }}>
        <div
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
          style={{
            display: 'flex',
            alignItems: 'stretch',
            transform: `translateX(-${slide * 100}%)`,
            transition: reduced ? 'none' : 'transform 0.3s ease',
          }}
        >
          {slides.map((s, i) => {
            const onActiveSlide = Math.floor(i / perView) === slide;
            return (
              <div
                key={s.key}
                role="group"
                aria-roledescription="slide"
                aria-label={`${s.label} (chart ${i + 1} of ${total})`}
                aria-hidden={onActiveSlide ? undefined : true}
                inert={onActiveSlide ? undefined : true}
                style={{
                  flex: `0 0 ${100 / perView}%`,
                  maxWidth: `${100 / perView}%`,
                  minWidth: 0,
                  boxSizing: 'border-box',
                  padding: '0 6px',
                }}
              >
                {s.node}
              </div>
            );
          })}
        </div>
      </div>

      {/* Controls — hidden entirely when everything fits on one slide. */}
      {numSlides > 1 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%' }}>
            <button type="button" aria-label="Previous slide" onClick={() => go(slide - 1)} disabled={atStart} style={navBtn(atStart)}>
              <ChevronLeft size={20} />
            </button>
            <span style={{ flex: 1, textAlign: 'center', fontSize: 12, color: c.textMuted }}>
              <strong style={{ color: c.text, fontWeight: 600 }}>{slide + 1}</strong> / {numSlides}
            </span>
            <button type="button" aria-label="Next slide" onClick={() => go(slide + 1)} disabled={atEnd} style={navBtn(atEnd)}>
              <ChevronRight size={20} />
            </button>
          </div>

          {/* Dots reflect SLIDE count (recomputed with perView). 24×44 tap
              targets (WCAG 2.5.8) with a small visual pill inside; a full 44px
              width per dot would overflow narrow screens once there are several
              slides, so the hit area is ≥24px and the row wraps if needed. */}
          <div role="tablist" aria-label="Choose slide" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 4 }}>
            {Array.from({ length: numSlides }, (_, i) => {
              const active = i === slide;
              return (
                <button
                  key={i}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-label={`Go to slide ${i + 1} of ${numSlides}`}
                  onClick={() => go(i)}
                  style={{
                    width: 24, height: 44, padding: 0, border: 'none', background: 'transparent',
                    cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <span
                    style={{
                      width: active ? 22 : 10, height: 10, borderRadius: 5, display: 'block',
                      background: active ? c.brand : c.border,
                      transition: reduced ? 'none' : 'width 0.2s, background 0.2s',
                    }}
                  />
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default ChartCarousel;
