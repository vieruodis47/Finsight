// theme.ts — FinSight design tokens (Steel & honey)
// Single source of truth for color + fonts. Change a value here and it
// updates across every component that imports from this file.

export const c = {
  // ── Brand — steel ──────────────────────────────────────────────
  brand:          '#3E5C76', // sparklines, focus rings, peer subject bar, active accents
  brandDeep:      '#28425A', // primary buttons, ticker pill, strong brand fills
  brandDeepHover: '#1B3147', // hover state on primary buttons
  brandTint:      '#E4EBF1', // soft brand backgrounds (active pills, icon circles)
  brandLight:     '#6E8CA6', // mid steel — chart ramps / lighter data series
  onBrand:        '#FFFFFF', // text/icons sitting on brandDeep

  // ── Accent — honey ─────────────────────────────────────────────
  accent:     '#E0A53B', // honey fills (chips, highlight backgrounds)
  accentInk:  '#3D2900', // text/icons on a honey fill
  accentFg:   '#8A6410', // honey used AS a foreground icon/text on light bg (darkened for contrast)
  accentSoft: '#FBEFD6', // light honey tint

  // ── Directional (semantic only — never use for brand/category) ─
  pos:        '#16A34A', // favorable move
  neg:        '#DC2626', // unfavorable move (also the destructive/error red)
  posSurface: '#ECFDF3',
  posBorder:  '#BBF7D0',
  negSurface: '#FEF2F2',
  negBorder:  '#FECACA',

  // ── Warning / "could be better" (honey-family) ────────────────
  warnFg:      '#8A6410',
  warnSurface: '#FBF3E2',
  warnBorder:  '#F3DFB0',

  // ── Neutrals ───────────────────────────────────────────────────
  bg:          '#FFFFFF',
  surface:     '#F2F5F8', // primary neutral surface (cards, sidebar, bubbles)
  surfaceAlt:  '#F3F4F6', // segmented controls, inactive pills, subtle hovers
  hover:       '#EAECEF', // visible row hover on the cool sidebar surface
  border:      '#E5E7EB',
  borderFaint: '#F3F4F6',

  text:      '#111827', // primary text + metric values
  text2:     '#374151', // body copy / prose
  textMuted: '#6B7280', // secondary labels
  textFaint: '#9CA3AF', // tertiary / placeholder / disabled text

  // ── Charts ─────────────────────────────────────────────────────
  peer:      '#CBD5DF', // non-subject comparison bars / prior-period bars
} as const;

export const font = {
  ui:    "'Inter', system-ui, sans-serif",
  prose: "'Libre Baskerville', Georgia, serif",
} as const;

export const breakpoint = {
  tablet: 1024,
} as const;