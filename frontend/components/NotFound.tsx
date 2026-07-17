import React from 'react';
import { Compass, Home } from 'lucide-react';
import { c, font } from '../theme';

// Rendered when the URL doesn't match any real route (a mistyped or stale deep
// link). Shows a readable "not found" page with a way back home — never a blank
// screen or a crash. Sits inside the app shell, so the sidebar/nav stay usable.
const NotFound: React.FC<{ path?: string; onHome: () => void }> = ({ path, onHome }) => (
  <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: c.bg, fontFamily: font.ui }}>
    <div role="alert" style={{ maxWidth: 440, textAlign: 'center' }}>
      <div style={{ width: 48, height: 48, borderRadius: 12, background: c.surfaceAlt, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
        <Compass size={24} color={c.textMuted} />
      </div>
      <p style={{ fontSize: 18, fontWeight: 600, color: c.text, margin: '0 0 6px' }}>Page not found</p>
      <p style={{ fontSize: 13, color: c.textMuted, lineHeight: 1.6, margin: '0 0 18px' }}>
        {path ? <>The address <code style={{ background: c.surfaceAlt, padding: '1px 6px', borderRadius: 4, color: c.text2 }}>{path}</code> doesn’t match any page.</> : 'That address doesn’t match any page.'}
        {' '}It may have been mistyped or moved.
      </p>
      <button
        onClick={onHome}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 44,
          padding: '10px 18px', borderRadius: 8, fontSize: 14, fontWeight: 500,
          background: c.brandDeep, color: c.onBrand, border: 'none', cursor: 'pointer', fontFamily: font.ui,
        }}
        onMouseEnter={e => (e.currentTarget.style.background = c.brandDeepHover)}
        onMouseLeave={e => (e.currentTarget.style.background = c.brandDeep)}
      >
        <Home size={15} /> Back to Dashboard
      </button>
    </div>
  </div>
);

export default NotFound;
