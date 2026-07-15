// theme.ts — FinSight design tokens (Sapphire & slate)
// Single source of truth for color + fonts. Change a value here and it
// updates across every component that imports from this file. Kept flat and
// semantic so a dark variant can later be swapped in behind a toggle.

export const c = {
  // ── Brand — sapphire ───────────────────────────────────────────
  brand:          '#2563EB', // logo, sparklines, active-nav text, primary progress, hero/anchor card fill
  brandDeep:      '#2563EB', // primary buttons, ticker pill, strong brand fills (same sapphire)
  brandDeepHover: '#1D4ED8', // hover state on primary buttons (darker sapphire)
  brandTint:      '#EAF1FC', // active-nav row background / soft brand backgrounds
  brandLight:     '#60A5FA', // secondary progress-bar tier / lighter data series
  onBrand:        '#FFFFFF', // text/icons sitting on a sapphire fill (5.17:1 on #2563EB)
  onBrandMuted:   '#EDF4FE', // muted eyebrow/label text on a sapphire card (4.67:1 on #2563EB)

  // ── Secondary series — sapphire-light (peer / "B" entity) ──────
  // (Replaces the old honey accent. Fills only; peer TEXT uses accentFg.)
  accent:     '#60A5FA', // peer / secondary data-series fill (bars, lines)
  accentInk:  '#16202B', // text/icons sitting on a light-sapphire fill
  accentFg:   '#1D4ED8', // peer/label TEXT on a light bg — AA (6.70:1 on white)
  accentSoft: '#EAF1FC', // peer chip / soft secondary background

  // ── Directional (semantic only — never brand/category/UI) ──────
  pos:        '#16A34A', // favorable move (▲) — directional signal only
  neg:        '#DC2626', // unfavorable move (▼) — also destructive/error red
  posSurface: '#ECFDF3',
  posBorder:  '#BBF7D0',
  negSurface: '#FEF2F2',
  negBorder:  '#FECACA',

  // ── Warning / "could be better" (semantic caution — amber) ─────
  // Functional status, not brand/category; kept distinct from green/red.
  warnFg:      '#8A6410', // 4.86:1 on warnSurface
  warnSurface: '#FBF3E2',
  warnBorder:  '#F3DFB0',

  // ── Neutrals — slate ───────────────────────────────────────────
  bg:          '#FFFFFF', // card / panel background
  surface:     '#F3F6F9', // canvas/page + sidebar + subtle card fills
  surfaceAlt:  '#EEF2F6', // track / pill / segmented-control background
  hover:       '#E4EBF2', // visible row hover on the cool sidebar surface
  border:      '#DDE4EB', // card / panel border
  borderFaint: '#E8EDF2', // faint dividers

  text:        '#16202B', // ink — primary text + metric values
  text2:       '#33414F', // body copy / prose (10.4:1 on white)
  textMuted:   '#5D6C7C', // secondary labels — AA on light surfaces (≥4.78:1)
  textFaint:   '#636F7D', // eyebrow / tertiary / placeholder — AA on light surfaces (≥4.55:1)
  navInactive: '#4C5B6B', // inactive sidebar nav label (6.42:1 on sidebar)

  // ── Charts ─────────────────────────────────────────────────────
  peer:      '#C3CEDA', // non-subject comparison bars / prior-period bars
} as const;

// ── Categorical series palette (multi-series charts) ───────────────────────
// Single source of truth for distinguishing 2+ data series in one chart.
// Series differ by HUE, not just lightness (the old #2563EB/#60A5FA pair was two
// sapphires — indistinguishable in greyscale and for colour-vision-deficient
// users). Green/red are deliberately absent: those stay reserved for directional
// ▲/▼ signals, never category.
//
// Colour-blindness / greyscale check (report):
//   • The load-bearing pair is series[0] sapphire (#2563EB) vs series[1] amber
//     (#D97706) — the classic blue/orange pairing behind colour-blind-safe
//     palettes (cf. Okabe–Ito). Red-green deficiencies (deuteranopia,
//     protanopia) leave the blue↔yellow axis intact, so the two stay separable;
//     violet (#7C3AED) and teal (#0D9488) extend that without introducing a
//     red/green confusion pair.
//   • Greyscale: relative luminances are ≈0.15 (sapphire), 0.28 (amber),
//     0.09 (violet), 0.20 (teal) — every adjacent pair differs enough to read
//     in print. As a WCAG 1.4.1 belt-and-braces we ALSO cue lines by
//     strokeDasharray + distinct dot shapes (see `dash`/`shape`), so colour is
//     never the sole differentiator; legends sit adjacent to each chart.
//
// `ink` is the AA-on-white (≥4.5:1) text twin of each fill, for legend labels /
// column headers where the vivid fill would fail small-text contrast.
export const series = {
  fill:  ['#2563EB', '#D97706', '#7C3AED', '#0D9488'], // sapphire, amber, violet, teal
  ink:   ['#1D4ED8', '#B45309', '#6D28D9', '#0F766E'], // AA-on-white text variants
  dash:  ['',        '6 4',     '2 3',     '8 3 2 3'],  // stroke pattern per index
  shape: ['circle',  'square',  'triangle', 'diamond'], // Recharts scatter/dot shape
} as const;

// Convenience aliases for the anchor(A)/peer(B) two-series comparison views.
export const seriesA = { fill: series.fill[0], ink: series.ink[0], dash: series.dash[0] } as const;
export const seriesB = { fill: series.fill[1], ink: series.ink[1], dash: series.dash[1] } as const;

export const font = {
  ui:    "'Inter', system-ui, sans-serif",
  prose: "'Libre Baskerville', Georgia, serif",
} as const;

export const breakpoint = {
  tablet: 1024,
} as const;
