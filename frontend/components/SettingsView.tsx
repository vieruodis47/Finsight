import React from 'react';
import { Info } from 'lucide-react';
import { c, font } from '../theme';

// Minimal Settings page. It exists so the Settings nav item points at a real
// destination instead of being a dead control (it previously had no onClick).
// There are no user-configurable options yet — FinSight keeps no server-side
// account state and loaded filings live in the session. Replace this with real
// settings (or remove the nav item) when there's something to configure.
const SettingsView: React.FC = () => (
  <div style={{ padding: 22, height: '100%', overflowY: 'auto', background: c.bg, fontFamily: font.ui }}>
    <div style={{ marginBottom: 20 }}>
      <p style={{ fontSize: 15, fontWeight: 500, color: c.text, margin: '0 0 2px' }}>Settings</p>
      <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>Workspace preferences.</p>
    </div>
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, maxWidth: 560, background: c.bg, border: `0.5px solid ${c.border}`, borderRadius: 10, padding: '16px 18px', color: c.textMuted, fontSize: 13, lineHeight: 1.6 }}>
      <Info size={16} color={c.textFaint} style={{ flexShrink: 0, marginTop: 1 }} />
      <span>
        There are no configurable settings yet. Your loaded companies and filings
        live in this browser session and appear in the sidebar — remove a company
        there to clear it. Preferences will show up here as they’re added.
      </span>
    </div>
  </div>
);

export default SettingsView;
