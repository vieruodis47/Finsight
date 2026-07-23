import React, { useId } from 'react';
import { c, font } from '../theme';

// Accessible wrapper for a single chart + its auto-generated description.
//
// The description text is COMPUTED server-side (deterministic templating from the
// plotted series — see backend/analysis/descriptions.py), never LLM-authored, so
// it always matches the numbers on screen.
//
// Accessibility (per WCAG): the chart itself is an unlabeled <svg>, useless to a
// screen reader. We wrap it in a role="img" container carrying the description as
// aria-label, so AT announces the trend instead of "graphic". The same text is
// shown as a visible <figcaption> for everyone; it's aria-hidden so AT doesn't
// read it twice (the aria-label already carries it).
export const ChartFigure: React.FC<{
  description?: string;
  children: React.ReactNode;
}> = ({ description, children }) => {
  const label = description?.trim() || undefined;
  return (
    <figure style={{ margin: 0 }}>
      <div role={label ? 'img' : undefined} aria-label={label}>
        {children}
      </div>
      {label && (
        <figcaption
          aria-hidden="true"
          style={{
            marginTop: 8,
            fontSize: 12,
            lineHeight: 1.55,
            color: c.textMuted,
            fontFamily: font.ui,
          }}
        >
          {label}
        </figcaption>
      )}
    </figure>
  );
};

// Standalone caption when the chart wrapper can't be nested in a <figure>
// (e.g. inside an existing Panel that already owns layout). Renders the visible
// text and returns an id the caller can point aria-describedby at.
export const useChartCaption = (text?: string) => {
  const id = useId();
  const node = text?.trim() ? (
    <p
      id={id}
      style={{
        margin: '8px 0 0',
        fontSize: 12,
        lineHeight: 1.55,
        color: c.textMuted,
        fontFamily: font.ui,
      }}
    >
      {text}
    </p>
  ) : null;
  return { id: text?.trim() ? id : undefined, node };
};
