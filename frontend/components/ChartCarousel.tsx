import React, { useState, useRef } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { c, font } from '../theme';
import { usePrefersReducedMotion } from '../utils/hooks';

export interface CarouselSlide {
  key: string;
  label: string;         // announced + shown, e.g. "Revenue vs Net income"
  node: React.ReactNode; // the chart panel (keeps its own description below the chart)
}

/**
 * Mobile chart carousel: one chart per view, swipeable, with prev/next buttons
 * and dot indicators. Desktop callers render their normal grid instead — this
 * component is only mounted below the mobile breakpoint.
 *
 * Recharts-in-carousel correctness: every slide is `flex: 0 0 100%` and stays in
 * layout (translated, never display:none), so each chart's ResponsiveContainer
 * always measures a real width and renders at non-zero height — even slides that
 * aren't currently visible.
 *
 * A11y: real <button>s (tab-reachable, focus-visible ring), arrow-key nav, a
 * polite live region announcing "Chart N of M: label", off-screen slides made
 * `inert` (not tab-reachable, including their <select>s), and the slide
 * transition dropped under prefers-reduced-motion.
 */
export const ChartCarousel: React.FC<{ slides: CarouselSlide[]; label?: string }> = ({
  slides,
  label = 'Analysis charts',
}) => {
  const [index, setIndex] = useState(0);
  const reduced = usePrefersReducedMotion();
  const touchStartX = useRef<number | null>(null);
  const n = slides.length;

  const clamp = (i: number) => Math.max(0, Math.min(n - 1, i));
  const go = (i: number) => setIndex(clamp(i));

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); go(index + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(index - 1); }
  };
  const onTouchStart = (e: React.TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(dx) > 40) go(index + (dx < 0 ? 1 : -1)); // left swipe → next
    touchStartX.current = null;
  };

  // 44×44 primary controls (WCAG 2.5.5).
  const navBtn = (disabled: boolean): React.CSSProperties => ({
    width: 44, height: 44, flexShrink: 0,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 8, border: `0.5px solid ${c.border}`,
    background: disabled ? c.surfaceAlt : c.bg,
    color: disabled ? c.textFaint : c.text,
    cursor: disabled ? 'not-allowed' : 'pointer',
  });

  return (
    <div
      role="group"
      aria-roledescription="carousel"
      aria-label={label}
      onKeyDown={onKeyDown}
      style={{ display: 'flex', flexDirection: 'column', gap: 12, fontFamily: font.ui }}
    >
      {/* Polite live region — announces the active slide to assistive tech. */}
      <p
        aria-live="polite"
        style={{ position: 'absolute', width: 1, height: 1, margin: -1, padding: 0, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0 }}
      >
        Chart {index + 1} of {n}: {slides[index]?.label}
      </p>

      {/* Viewport + sliding track */}
      <div style={{ overflow: 'hidden', width: '100%' }}>
        <div
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
          style={{
            display: 'flex',
            alignItems: 'flex-start', // each card sizes to its own content, not the tallest slide
            transform: `translateX(-${index * 100}%)`,
            transition: reduced ? 'none' : 'transform 0.3s ease',
          }}
        >
          {slides.map((s, i) => {
            const active = i === index;
            return (
              <div
                key={s.key}
                role="group"
                aria-roledescription="slide"
                aria-label={`Chart ${i + 1} of ${n}: ${s.label}`}
                aria-hidden={active ? undefined : true}
                inert={active ? undefined : true}
                style={{ flex: '0 0 100%', minWidth: '100%', boxSizing: 'border-box' }}
              >
                {s.node}
              </div>
            );
          })}
        </div>
      </div>

      {/* Controls: prev · position/label · next, with dot indicators below. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%' }}>
          <button type="button" aria-label="Previous chart" onClick={() => go(index - 1)} disabled={index === 0} style={navBtn(index === 0)}>
            <ChevronLeft size={20} />
          </button>
          <span style={{ flex: 1, textAlign: 'center', fontSize: 12, color: c.textMuted }}>
            <strong style={{ color: c.text, fontWeight: 600 }}>{index + 1}</strong> / {n} · {slides[index]?.label}
          </span>
          <button type="button" aria-label="Next chart" onClick={() => go(index + 1)} disabled={index === n - 1} style={navBtn(index === n - 1)}>
            <ChevronRight size={20} />
          </button>
        </div>

        {/* Dots: 24×44 tap targets (WCAG 2.5.8) with a small visual pill inside;
            full 44×44 per dot would overflow 320px once you have 6–9 charts, so
            the hit area is kept ≥24px and the row wraps if needed. */}
        <div role="tablist" aria-label="Choose chart" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 4 }}>
          {slides.map((s, i) => {
            const active = i === index;
            return (
              <button
                key={s.key}
                type="button"
                role="tab"
                aria-selected={active}
                aria-label={`Go to chart ${i + 1}: ${s.label}`}
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
    </div>
  );
};

export default ChartCarousel;
