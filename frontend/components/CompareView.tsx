import React, { useRef, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { c, font } from '../theme';
import { useOnClickOutside } from '../utils/hooks';
import PeerPicker from './PeerPicker';

interface CompareViewProps {
  anchor: string;
  peer: string;
  // Stable cycle array (sidebar order, anchor removed, deep-linked peer at the
  // tail) — always contains `peer`. Built in App so ordering is deterministic.
  peers: string[];
  onBack: () => void;
  onSelectPeer: (peer: string) => void;
}

// Nav controls for the comparison view. Three distinct controls, never merged:
//   1. "← {anchor}"     — back to the anchor's company view
//   2. "‹ {peer} ›"     — cycle the peer (only rendered at 3+ peers; below that
//                          chevrons would be dead/toggle, so we show just the
//                          name and rely on the picker)
//   3. peer picker      — search any SEC company; available at every peer count
// The metrics panel and price chart land in later diffs, below this header.
const CompareView: React.FC<CompareViewProps> = ({ anchor, peer, peers, onBack, onSelectPeer }) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerWrapRef = useRef<HTMLDivElement>(null);
  useOnClickOutside(pickerWrapRef, () => setPickerOpen(false), pickerOpen);

  const n = peers.length;
  const idx = Math.max(0, peers.indexOf(peer)); // peer is always in `peers`
  const showCycler = n >= 3;
  const prevPeer = n > 0 ? peers[(idx - 1 + n) % n] : peer;
  const nextPeer = n > 0 ? peers[(idx + 1) % n] : peer;

  const chevronBtn: React.CSSProperties = {
    width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 6, border: `0.5px solid ${c.border}`, background: c.bg,
    cursor: 'pointer', color: c.textMuted, padding: 0,
  };

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: font.ui, boxSizing: 'border-box' }}>

      {/* ── Nav controls ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>

        {/* 1. Back to anchor */}
        <button
          onClick={onBack}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px 0 9px',
            borderRadius: 7, border: `0.5px solid ${c.border}`, background: c.bg,
            fontSize: 13, fontWeight: 500, color: c.text, cursor: 'pointer', fontFamily: font.ui,
          }}
          onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
          onMouseLeave={e => (e.currentTarget.style.background = c.bg)}
        >
          <ArrowLeft size={15} />
          {anchor}
        </button>

        <span style={{ fontSize: 13, color: c.textFaint }}>vs</span>

        {/* 2. Peer — cycler at 3+, otherwise a static name */}
        {showCycler ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              aria-label="Previous peer"
              onClick={() => onSelectPeer(prevPeer)}
              style={chevronBtn}
              onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; }}
              onMouseLeave={e => { e.currentTarget.style.background = c.bg; e.currentTarget.style.color = c.textMuted; }}
            >
              <ChevronLeft size={16} />
            </button>
            <span style={{ fontSize: 14, fontWeight: 600, color: c.brandDeep, minWidth: 44, textAlign: 'center' }}>
              {peer}
            </span>
            <button
              aria-label="Next peer"
              onClick={() => onSelectPeer(nextPeer)}
              style={chevronBtn}
              onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; }}
              onMouseLeave={e => { e.currentTarget.style.background = c.bg; e.currentTarget.style.color = c.textMuted; }}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        ) : (
          <span style={{ fontSize: 14, fontWeight: 600, color: c.brandDeep }}>{peer}</span>
        )}

        {/* 3. Peer picker — always available */}
        <div ref={pickerWrapRef} style={{ position: 'relative' }}>
          <button
            onClick={() => setPickerOpen(o => !o)}
            aria-haspopup="listbox"
            aria-expanded={pickerOpen}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px',
              borderRadius: 7, border: `0.5px solid ${c.border}`, background: pickerOpen ? c.hover : c.bg,
              fontSize: 13, color: c.textMuted, cursor: 'pointer', fontFamily: font.ui,
            }}
            onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
            onMouseLeave={e => { if (!pickerOpen) e.currentTarget.style.background = c.bg; }}
          >
            <Search size={14} />
            Change peer
          </button>
          <PeerPicker
            open={pickerOpen}
            onClose={() => setPickerOpen(false)}
            onSelect={onSelectPeer}
            exclude={[anchor, peer]}
            align="left"
          />
        </div>
      </div>

      {/* ── Metrics panel + price chart land here in the next diffs ── */}
      <p style={{ fontSize: 13, color: c.textMuted, marginTop: 20 }}>
        Comparing <strong style={{ color: c.text }}>{anchor}</strong> vs{' '}
        <strong style={{ color: c.brandDeep }}>{peer}</strong>.
      </p>
    </div>
  );
};

export default CompareView;
