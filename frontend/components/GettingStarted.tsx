import React, { useRef, useState, useEffect } from 'react';
import { Search, TrendingUp, Layers, MessageSquare } from 'lucide-react';
import { c, font } from '../theme';
import { searchCompanies, SearchResult } from '../services/gemini';
import SearchDropdown from './SearchDropdown';

interface GettingStartedProps {
  onAddCompany: (query: string) => void;
}

interface Example {
  name: string;
  ticker: string;
}

interface Step {
  icon: React.ComponentType<{ size?: number; color?: string }>;
  title: string;
  sub: string;
}

const EXAMPLES: Example[] = [
  { name: 'Apple', ticker: 'AAPL' },
  { name: 'Nike', ticker: 'NKE' },
  { name: 'Walmart', ticker: 'WMT' },
];

const STEPS: Step[] = [
  { icon: Search,        title: 'Search EDGAR',   sub: 'find any public filer' },
  { icon: Layers,        title: 'Fetch and index', sub: '10-K and 10-Q parsed' },
  { icon: MessageSquare, title: 'Ask anything',    sub: 'summarize and compare' },
];

const GettingStarted: React.FC<GettingStartedProps> = ({ onAddCompany }) => {
  const [query, setQuery]               = useState('');
  const [suggestions, setSuggestions]   = useState<SearchResult[]>([]);
  const [showDrop, setShowDrop]         = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  // Debounced search — fires 200 ms after the user stops typing.
  useEffect(() => {
    const q = query.trim();
    if (!q) { setSuggestions([]); setShowDrop(false); return; }

    const timer = setTimeout(async () => {
      const results = await searchCompanies(q);
      setSuggestions(results);
      setShowDrop(results.length > 0);
      setHighlightIdx(-1);
    }, 200);

    return () => clearTimeout(timer);
  }, [query]);

  const selectSuggestion = (s: SearchResult) => {
    setShowDrop(false);
    setHighlightIdx(-1);
    onAddCompany(s.ticker);
  };

  // Submit: prefer the arrow-key-highlighted item, then the first suggestion,
  // then fall back to raw query (works for exact tickers typed directly).
  const submit = () => {
    const q = query.trim();
    if (!q) { inputRef.current?.focus(); return; }
    const chosen = highlightIdx >= 0 ? suggestions[highlightIdx] : suggestions[0];
    onAddCompany(chosen ? chosen.ticker : q.toUpperCase());
    setShowDrop(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIdx(i => Math.min(i + 1, suggestions.length - 1));
      setShowDrop(true);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIdx(i => Math.max(i - 1, -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      submit();
    } else if (e.key === 'Escape') {
      setShowDrop(false);
      setHighlightIdx(-1);
    }
  };

  return (
    <div style={{ height: '100%', background: c.bg, fontFamily: font.ui, display: 'flex', flexDirection: 'column' }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', borderBottom: `1px solid ${c.borderFaint}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <TrendingUp size={18} color={c.brand} />
          <span style={{ fontWeight: 500, fontSize: 15, color: c.text }}>FinSight</span>
        </div>
        <span style={{ fontSize: 12, color: c.textFaint }}>No companies yet</span>
      </div>

      {/* Hero */}
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        padding: '2.5rem 1rem', textAlign: 'center',
      }}>
        <h1 style={{ margin: '0 0 10px', fontSize: 22, fontWeight: 500, color: c.text }}>
          Start with a company
        </h1>
        <p style={{ color: c.text2, maxWidth: 440, margin: '0 0 1.75rem', lineHeight: 1.7, fontSize: 15 }}>
          Search any public company. FinSight pulls its latest 10-K and 10-Q from SEC EDGAR,
          indexes them, and lets you ask questions, summarize, and compare.
        </p>

        {/* Search row + dropdown — wrapper is the positioning root */}
        <div style={{ position: 'relative', width: '100%', maxWidth: 480, marginBottom: 16 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ position: 'relative', flex: 1 }}>
              <Search
                size={18}
                color={c.textFaint}
                style={{ position: 'absolute', left: 13, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
              />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={e => {
                  e.target.style.borderColor = c.brand;
                  if (suggestions.length > 0) setShowDrop(true);
                }}
                onBlur={e => {
                  e.target.style.borderColor = c.border;
                  setTimeout(() => setShowDrop(false), 150);
                }}
                placeholder="Company name or ticker — try 'Coca-Cola' or 'NVDA'"
                aria-label="Search for a company"
                aria-autocomplete="list"
                aria-expanded={showDrop}
                style={{
                  width: '100%', height: 40, padding: '0 12px 0 38px', boxSizing: 'border-box',
                  border: `1px solid ${c.border}`, borderRadius: 8, fontSize: 14,
                  fontFamily: font.ui, color: c.text, outline: 'none', background: c.bg,
                }}
              />
            </div>
            <button
              onClick={submit}
              style={{
                height: 40, padding: '0 18px', background: c.brandDeep, color: c.onBrand,
                border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 500,
                fontFamily: font.ui, cursor: 'pointer', whiteSpace: 'nowrap',
                transition: 'background 0.15s', flexShrink: 0,
              }}
              onMouseEnter={e => (e.currentTarget.style.background = c.brandDeepHover)}
              onMouseLeave={e => (e.currentTarget.style.background = c.brandDeep)}
            >
              Add company
            </button>
          </div>

          {showDrop && (
            <SearchDropdown
              suggestions={suggestions}
              highlightIdx={highlightIdx}
              onSelect={selectSuggestion}
              onHighlight={setHighlightIdx}
            />
          )}
        </div>

        {/* Example chips — bypass the search box and load directly */}
        <div style={{ width: '100%', maxWidth: 480, marginBottom: '2.5rem' }}>
          <p style={{ fontSize: 13, color: c.textFaint, margin: '0 0 10px' }}>For example</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
            {EXAMPLES.map(ex => (
              <button
                key={ex.ticker}
                onClick={() => onAddCompany(ex.ticker)}
                style={{
                  border: `1px solid ${c.border}`, borderRadius: 999, padding: '7px 14px',
                  fontSize: 14, background: c.surface, fontFamily: font.ui,
                  cursor: 'pointer', color: c.text, transition: 'background 0.1s, border-color 0.1s',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = c.brandTint;
                  e.currentTarget.style.borderColor = c.brand;
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = c.surface;
                  e.currentTarget.style.borderColor = c.border;
                }}
              >
                {ex.name}&nbsp;<span style={{ color: c.textMuted }}>{ex.ticker}</span>
              </button>
            ))}
          </div>
        </div>

        {/* How it works */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: 16, width: '100%', maxWidth: 560,
          borderTop: `1px solid ${c.borderFaint}`, paddingTop: '1.75rem',
        }}>
          {STEPS.map(step => {
            const Icon = step.icon;
            return (
              <div key={step.title} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                <Icon size={22} color={c.textMuted} />
                <span style={{ fontSize: 14, fontWeight: 500, color: c.text }}>{step.title}</span>
                <span style={{ fontSize: 13, color: c.textFaint }}>{step.sub}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default GettingStarted;
