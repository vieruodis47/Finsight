import React from 'react';
import { c, font } from '../theme';
import { SearchResult } from '../services/gemini';

interface SearchDropdownProps {
  suggestions: SearchResult[];
  highlightIdx: number;
  onSelect: (s: SearchResult) => void;
  onHighlight: (i: number) => void;
}

const SearchDropdown: React.FC<SearchDropdownProps> = ({ suggestions, highlightIdx, onSelect, onHighlight }) => {
  if (suggestions.length === 0) return null;
  return (
    <div style={{
      position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0,
      background: c.bg, border: `1px solid ${c.border}`, borderRadius: 8,
      boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
      overflow: 'hidden', zIndex: 20,
    }}>
      {suggestions.map((s, i) => {
        const active = i === highlightIdx;
        return (
          <button
            key={s.ticker}
            onMouseDown={e => e.preventDefault()} // keep input focused before click fires
            onClick={() => onSelect(s)}
            onMouseEnter={() => onHighlight(i)}
            onMouseLeave={() => onHighlight(-1)}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              width: '100%', padding: '9px 14px', border: 'none', textAlign: 'left',
              background: active ? c.brandTint : c.bg,
              cursor: 'pointer', fontFamily: font.ui,
              borderBottom: i < suggestions.length - 1 ? `0.5px solid ${c.borderFaint}` : 'none',
            }}
          >
            <span style={{ fontSize: 13, color: active ? c.brandDeep : c.text }}>{s.name}</span>
            <span style={{
              fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 6,
              background: active ? c.peer : c.surfaceAlt,
              color: active ? c.brandDeep : c.textMuted,
              marginLeft: 12, flexShrink: 0,
            }}>
              {s.ticker}
            </span>
          </button>
        );
      })}
    </div>
  );
};

export default SearchDropdown;
