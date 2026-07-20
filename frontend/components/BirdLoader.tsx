import React from 'react';
import { c, font } from '../theme';

// ── Shared flying-bird loader ─────────────────────────────────────────────────
// Single source of truth for FinSight's sapphire-gull loading indicator. Used by
// FinChat ("Fetching an answer…") and by each Dashboard widget while it fetches.
//
// The wing-flap and fly-across keyframes live in index.html (.finch-fly /
// .finch-wing--l / .finch-wing--r) so both variants share one definition AND one
// `prefers-reduced-motion` rule — under reduced motion the fly + flap are zeroed
// there, leaving a static bird for every consumer of this component.
//
//   variant="full"  fly-across a ~150px track (chat bubble + large chart panels)
//   variant="sm"    a small bird flapping IN PLACE (metric cards — no 150px track
//                   to fly across inside a compact card)
//
// The host element is role="status" aria-live="polite"; pass `ariaLabel` for a
// concise per-widget announcement ("Loading revenue"). The SVG is aria-hidden.
// `label` is the OPTIONAL visible caption (default none for cards; FinChat passes
// "Fetching an answer…"). `delayMs` staggers the flap so a grid of "sm" birds
// isn't in lockstep (reads calm, not chaotic).

export type BirdVariant = 'sm' | 'full';

interface BirdLoaderProps {
  variant?: BirdVariant;
  label?: string;
  ariaLabel?: string;
  delayMs?: number;
}

// Two stroked wings meeting at the body (12,11); each flaps about that root via
// the .finch-wing--l/--r classes. `delayMs` offsets the flap when supplied.
const Wings: React.FC<{ width: number; height: number; delayMs?: number }> = ({ width, height, delayMs }) => {
  const delay = delayMs ? { animationDelay: `${delayMs}ms` } : undefined;
  return (
    <svg aria-hidden="true" width={width} height={height} viewBox="0 0 24 18" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path className="finch-wing finch-wing--l" style={delay} d="M2 6 Q 7 4 12 11"  stroke={c.brand}      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path className="finch-wing finch-wing--r" style={delay} d="M22 6 Q 17 4 12 11" stroke={c.brandLight} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

const BirdLoader: React.FC<BirdLoaderProps> = ({ variant = 'full', label, ariaLabel = 'Loading', delayMs }) => {
  const isSm = variant === 'sm';
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={ariaLabel}
      style={{ display: 'inline-flex', alignItems: 'center', gap: isSm ? 8 : 10 }}
    >
      {isSm ? (
        // In-place bird: just the flapping wings, no fly track.
        <span style={{ display: 'inline-flex' }}>
          <Wings width={20} height={15} delayMs={delayMs} />
        </span>
      ) : (
        // Fly-across: a 150px track the bird translates over (see .finch-fly).
        <span style={{ position: 'relative', display: 'inline-block', width: 150, height: 26, flexShrink: 0 }}>
          <span className="finch-fly" style={{ position: 'absolute', left: 0, top: 4, display: 'inline-block', willChange: 'transform' }}>
            <Wings width={24} height={18} />
          </span>
        </span>
      )}
      {label && <span style={{ fontSize: 13, color: c.textMuted, fontFamily: font.ui }}>{label}</span>}
    </div>
  );
};

export default BirdLoader;
