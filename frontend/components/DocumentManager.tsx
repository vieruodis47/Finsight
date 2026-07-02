import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, FileText, Trash2, Loader2, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Document, IndexStatus } from '../types';
import { c, font } from '../theme';
import { extractCompany, buildContent, searchCompanies, SearchResult } from '../services/gemini';
import CompanyLogo from './CompanyLogo';
import SearchDropdown from './SearchDropdown';

interface DocumentManagerProps {
  documents: Document[];
  onAddDocument: (doc: Document) => void;
  onRemoveDocument: (id: string) => void;
  onFetched?: () => void;
}

const FF = font.ui;
type Form = '10-K' | '10-Q';

const selectStyle: React.CSSProperties = {
  fontSize: 13, padding: '8px 12px',
  border: `0.5px solid ${c.border}`,
  borderRadius: 7, outline: 'none',
  fontFamily: FF, color: c.text, background: c.bg,
  cursor: 'pointer', flexShrink: 0,
};

const DocumentManager: React.FC<DocumentManagerProps> = ({ documents, onAddDocument, onRemoveDocument, onFetched }) => {
  const [fetching, setFetching]   = useState(false);
  const [form, setForm]           = useState<Form>('10-K');
  const [error, setError]         = useState<string | null>(null);

  // Ticker input: inputValue is what the user sees; resolvedTicker is the
  // confirmed ticker from a dropdown selection. Manual edits clear resolvedTicker
  // so the debounced search re-runs on the new text.
  const [inputValue, setInputValue]         = useState('');
  const [resolvedTicker, setResolvedTicker] = useState<string | null>(null);
  const [suggestions, setSuggestions]       = useState<SearchResult[]>([]);
  const [showDrop, setShowDrop]             = useState(false);
  const [highlightIdx, setHighlightIdx]     = useState(-1);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Debounced search — skipped when a company has already been resolved from
  // the dropdown (resolvedTicker is set). Clears on manual typing via onChange.
  useEffect(() => {
    if (resolvedTicker) { setSuggestions([]); setShowDrop(false); return; }
    const q = inputValue.trim();
    if (!q) { setSuggestions([]); setShowDrop(false); return; }

    const timer = setTimeout(async () => {
      const results = await searchCompanies(q);
      setSuggestions(results);
      setShowDrop(results.length > 0);
      setHighlightIdx(-1);
    }, 200);

    return () => clearTimeout(timer);
  }, [inputValue, resolvedTicker]);

  const selectSuggestion = (s: SearchResult) => {
    setInputValue(s.name);
    setResolvedTicker(s.ticker);
    setShowDrop(false);
    setHighlightIdx(-1);
  };

  const handleTickerKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (showDrop && suggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHighlightIdx(i => Math.min(i + 1, suggestions.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHighlightIdx(i => Math.max(i - 1, -1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const chosen = highlightIdx >= 0 ? suggestions[highlightIdx] : suggestions[0];
        if (chosen) selectSuggestion(chosen);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        setShowDrop(false);
        setHighlightIdx(-1);
      }
    } else if (e.key === 'Enter') {
      handleFetchEdgar();
    }
  };

  const handleFetchEdgar = async () => {
    const t = (resolvedTicker || inputValue.trim()).toUpperCase();
    if (!t || fetching) return;
    setError(null);
    setFetching(true);
    try {
      const data = await extractCompany(t, form);
      onAddDocument({
        id: `doc-${Date.now()}`,
        name: `${t} ${data.form}`,
        uploadDate: new Date().toISOString().split('T')[0],
        size: data.char_count ? `${Math.round(data.char_count / 1024)} KB` : '—',
        content: buildContent(data.sections ?? {}),
        ticker: t,
        form: data.form,
        metrics: data.metrics,
        indexStatus: 'indexing',
        ...(data.sector ? { sector: data.sector } : {}),
      });
      setInputValue('');
      setResolvedTicker(null);
      onFetched?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Fetch failed. Is the backend running?');
    } finally {
      setFetching(false);
    }
  };

  const canFetch = inputValue.trim() && !fetching;

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: FF, background: c.bg }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <p style={{ fontSize: 15, fontWeight: 500, color: c.text, margin: '0 0 2px' }}>Document library</p>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>
          Fetch filings from SEC EDGAR — each is parsed and embedded into a searchable vector index for RAG chat.
        </p>
      </div>

      {/* Primary: fetch from EDGAR */}
      <div style={{ background: c.surface, borderRadius: 12, padding: '16px 18px', marginBottom: 12 }}>
        <p style={{ fontSize: 12, color: c.textMuted, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Fetch from SEC EDGAR
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>

          {/* Ticker input — positioning root for the autocomplete dropdown */}
          <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
            <input
              type="text"
              value={inputValue}
              onChange={e => {
                setInputValue(e.target.value);
                setResolvedTicker(null);
                if (error) setError(null);
              }}
              onKeyDown={handleTickerKeyDown}
              onFocus={e => {
                e.target.style.borderColor = c.brand;
                if (suggestions.length > 0 && !resolvedTicker) setShowDrop(true);
              }}
              onBlur={e => {
                e.target.style.borderColor = c.border;
                setTimeout(() => setShowDrop(false), 150);
              }}
              placeholder="Company name or ticker"
              style={{
                width: '100%', boxSizing: 'border-box', fontSize: 13,
                padding: '8px 12px',
                border: `0.5px solid ${c.border}`,
                borderRadius: 7, outline: 'none',
                fontFamily: FF, color: c.text, background: c.bg,
              }}
            />
            {showDrop && (
              <SearchDropdown
                suggestions={suggestions}
                highlightIdx={highlightIdx}
                onSelect={selectSuggestion}
                onHighlight={setHighlightIdx}
              />
            )}
          </div>

          <select
            value={form}
            onChange={e => setForm(e.target.value as Form)}
            style={selectStyle}
            aria-label="Filing type"
          >
            <option value="10-K">10-K</option>
            <option value="10-Q">10-Q</option>
          </select>

          <button
            onClick={handleFetchEdgar}
            disabled={!canFetch}
            style={{
              padding: '8px 16px', borderRadius: 7, fontSize: 13,
              background: canFetch ? c.brandDeep : c.border,
              color:      canFetch ? c.onBrand   : c.textFaint,
              border: 'none', cursor: canFetch ? 'pointer' : 'not-allowed',
              fontFamily: FF, fontWeight: 500, flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', gap: 6,
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => { if (canFetch) e.currentTarget.style.background = c.brandDeepHover; }}
            onMouseLeave={e => { if (canFetch) e.currentTarget.style.background = c.brandDeep; }}
          >
            {fetching
              ? <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Fetching…</>
              : 'Fetch filing'}
          </button>
        </div>

        {/* Resolved company hint */}
        {resolvedTicker && (
          <p style={{ fontSize: 11, color: c.textMuted, margin: '6px 0 0' }}>
            Will fetch <strong style={{ color: c.text }}>{resolvedTicker}</strong> · choose a form above then click Fetch filing
          </p>
        )}

        {/* Fetch error — honey warn tokens */}
        {error && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 8,
            marginTop: 10, padding: '8px 12px', borderRadius: 7,
            background: c.warnSurface, border: `0.5px solid ${c.warnBorder}`,
            fontSize: 12, color: c.warnFg, lineHeight: 1.5,
          }}>
            <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Divider */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '4px 0 14px' }}>
        <div style={{ flex: 1, height: '0.5px', background: c.border }} />
        <span style={{ fontSize: 12, color: c.textFaint }}>or upload a file</span>
        <div style={{ flex: 1, height: '0.5px', background: c.border }} />
      </div>

      {/* PDF upload — disabled, coming soon */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          border: `1px dashed ${c.border}`,
          borderRadius: 8, padding: '12px 16px', marginBottom: 24,
          cursor: 'default',
          background: 'transparent',
          color: c.textFaint, fontSize: 13,
          opacity: 0.6,
        }}
      >
        <input type="file" ref={fileInputRef} style={{ display: 'none' }} disabled />
        <UploadCloud size={18} color={c.textFaint} />
        PDF / TXT upload — coming soon
      </div>

      {/* Document list */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>Indexed documents</p>
        <span style={{ fontSize: 13, color: c.textFaint }}>
          {documents.length} {documents.length === 1 ? 'filing' : 'filings'}
        </span>
      </div>

      <div style={{ border: `0.5px solid ${c.border}`, borderRadius: 12, overflow: 'hidden' }}>
        {documents.length === 0 ? (
          <div style={{ padding: '32px 20px', textAlign: 'center' }}>
            <FileText size={22} color={c.textFaint} style={{ margin: '0 auto 8px', display: 'block' }} />
            <p style={{ fontSize: 13, color: c.textFaint, margin: 0 }}>No filings yet. Fetch from EDGAR above.</p>
          </div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {documents.map((doc, i) => (
              <DocRow
                key={doc.id}
                doc={doc}
                last={i === documents.length - 1}
                onRemove={() => onRemoveDocument(doc.id)}
              />
            ))}
          </ul>
        )}
      </div>

    </div>
  );
};

// --- Index status badge -----------------------------------------------------

const IndexBadge: React.FC<{ status: IndexStatus | undefined; chunks?: number; error?: string }> = ({
  status, chunks, error,
}) => {
  if (!status) return null;

  if (status === 'indexing') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 11, color: c.textMuted,
      }}>
        <Loader2 size={11} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
        Indexing…
      </span>
    );
  }

  if (status === 'indexed') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 11,
        padding: '2px 7px', borderRadius: 10,
        background: c.brandTint, color: c.brand,
      }} title={chunks ? `${chunks} chunks stored` : undefined}>
        <CheckCircle2 size={10} style={{ flexShrink: 0 }} />
        {chunks ? `${chunks} chunks` : 'Indexed'}
      </span>
    );
  }

  // failed — honey warn, not red (red = financial direction only)
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 11,
      padding: '2px 7px', borderRadius: 10,
      background: c.warnSurface, color: c.warnFg,
    }} title={error ?? 'Indexing failed'}>
      <AlertTriangle size={10} style={{ flexShrink: 0 }} />
      Index failed
    </span>
  );
};

// --- Document row -----------------------------------------------------------

const DocRow: React.FC<{ doc: Document; last: boolean; onRemove: () => void }> = ({ doc, last, onRemove }) => {
  const [hovered, setHovered] = useState(false);

  const ticker = doc.ticker || doc.name.match(/^([A-Za-z]{1,5})/)?.[1]?.toUpperCase();

  const lower = doc.name.toLowerCase();
  const is10K = doc.form ? doc.form === '10-K' : (lower.includes('10k') || lower.includes('10-k') || lower.includes('annual'));
  const tag = doc.form || (is10K ? '10-K' : '10-Q');
  const tagStyle: React.CSSProperties = is10K
    ? { background: c.brandTint, color: c.brand }
    : { background: c.accentSoft, color: c.accentFg };

  return (
    <li
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '12px 16px',
        borderBottom: last ? 'none' : `0.5px solid ${c.border}`,
        background: hovered ? c.surface : c.bg,
        transition: 'background 0.1s',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <CompanyLogo ticker={ticker} size={36} radius={7} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontSize: 13, fontWeight: 500, color: c.text, margin: '0 0 4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {doc.name}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: c.textFaint, flexWrap: 'wrap' }}>
          <span>{doc.size}</span>
          <span>·</span>
          <span>Added {doc.uploadDate}</span>
          <span>·</span>
          <IndexBadge status={doc.indexStatus} chunks={doc.indexChunks} error={doc.indexError} />
        </div>
      </div>

      <span style={{ ...tagStyle, fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 500, flexShrink: 0 }}>
        {tag}
      </span>

      <button
        onClick={onRemove}
        title="Remove"
        style={{
          width: 28, height: 28, borderRadius: 6,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          border: 'none', cursor: 'pointer', flexShrink: 0,
          background: hovered ? c.negSurface : 'transparent',
          color: hovered ? c.neg : c.textFaint,
          opacity: hovered ? 1 : 0,
          transition: 'opacity 0.15s, background 0.1s, color 0.1s',
          fontFamily: font.ui,
        }}
      >
        <Trash2 size={15} />
      </button>
    </li>
  );
};

export default DocumentManager;
