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

export const font = {
  ui:    "'Inter', system-ui, sans-serif",
  prose: "'Libre Baskerville', Georgia, serif",
} as const;

export const breakpoint = {
  tablet: 1024,
} as const;
