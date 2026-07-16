import React, { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { c, font } from '../theme';
import { searchCompanies, SearchResult } from '../services/gemini';
import SearchDropdown from './SearchDropdown';
import { useDebounce } from '../utils/hooks';

interface PeerPickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (ticker: string) => void;
  exclude?: string[];         // uppercase tickers to omit from results
  align?: 'left' | 'right';   // edge to anchor the popover to (default 'right')
}

// Company-search popover backed by the existing /search endpoint. Panel-only
// and fully controlled: the parent renders the trigger and owns open/close
// (outside-click via useOnClickOutside), so the same picker serves both the
// topbar "Compare with peers" CTA (when no peer is loaded) and the in-view peer
// switcher. Selecting a suggestion is the ONLY way it emits a ticker, so a
// caller can trust onSelect always carries a real, non-empty, uppercase ticker.
const PeerPicker: React.FC<PeerPickerProps> = ({
  open, onClose, onSelect, exclude = [], align = 'right',
}) => {
  const [query, setQuery]             = useState('');
  const [suggestions, setSuggestions] = useState<SearchResult[]>([]);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  const excludeSet = React.useMemo(
    () => new Set(exclude.map(t => t.toUpperCase())),
    // exclude is a fresh array each render at some call sites; key on contents.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [exclude.join(',')],
  );

  // Reset + focus the input each time the popover opens.
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setSuggestions([]);
    setHighlightIdx(-1);
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  // Debounced search — 200 ms after the user stops typing, matching the
  // getting-started search feel. Excluded tickers (anchor, current peer) are
  // filtered out so you can't pick a company already on screen.
  const debounced = useDebounce(query, 200);
  useEffect(() => {
    const q = debounced.trim();
    if (!q) { setSuggestions([]); setHighlightIdx(-1); return; }
    let cancelled = false;
    searchCompanies(q).then(results => {
      if (cancelled) return;
      setSuggestions(results.filter(r => !excludeSet.has(r.ticker.toUpperCase())));
      setHighlightIdx(-1);
    });
    return () => { cancelled = true; };
  }, [debounced, excludeSet]);

  const choose = (s: SearchResult) => {
    onSelect(s.ticker.toUpperCase());
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx(i => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx(i => Math.max(i - 1, -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const chosen = highlightIdx >= 0 ? suggestions[highlightIdx] : suggestions[0];
      if (chosen) choose(chosen);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  if (!open) return null;

  return (
    <div
      style={{
        position: 'absolute', top: 'calc(100% + 6px)',
        // Cap to the viewport (minus a small gutter) so the 300px dropdown can't
        // overflow the page on a 320px phone when anchored near the screen edge.
        [align]: 0, width: 'min(300px, calc(100vw - 32px))', zIndex: 30,
      } as React.CSSProperties}
    >
      <div style={{ position: 'relative' }}>
        <Search
          size={16}
          color={c.textFaint}
          style={{ position: 'absolute', left: 11, top: 19, transform: 'translateY(-50%)', pointerEvents: 'none' }}
        />
        <input
          ref={inputRef}
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Search a company to compare…"
          aria-label="Search for a peer company"
          aria-autocomplete="list"
          aria-expanded={suggestions.length > 0}
          style={{
            width: '100%', height: 38, padding: '0 12px 0 34px', boxSizing: 'border-box',
            border: `1px solid ${c.border}`, borderRadius: 8, fontSize: 13,
            fontFamily: font.ui, color: c.text, outline: 'none', background: c.bg,
            boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
          }}
          onFocus={e => (e.currentTarget.style.borderColor = c.brand)}
          onBlur={e => (e.currentTarget.style.borderColor = c.border)}
        />
        <SearchDropdown
          suggestions={suggestions}
          highlightIdx={highlightIdx}
          onSelect={choose}
          onHighlight={setHighlightIdx}
        />
      </div>
    </div>
  );
};

export default PeerPicker;
