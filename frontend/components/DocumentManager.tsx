import React, { useState, useRef, useEffect } from 'react';
import {
  UploadCloud, FileText, Trash2, Loader2, AlertTriangle,
  CheckCircle2, Clock, RotateCcw,
} from 'lucide-react';
import { Document, IndexStatus } from '../types';
import { c, font } from '../theme';
import {
  extractCompany, buildContent, searchCompanies, SearchResult,
  uploadFile,
} from '../services/gemini';
import CompanyLogo from './CompanyLogo';
import { useDebounce } from '../utils/hooks';
import SearchDropdown from './SearchDropdown';

interface DocumentManagerProps {
  documents: Document[];
  onAddDocument: (doc: Document) => void;
  onRemoveDocument: (id: string) => void;
  onFetched?: () => void;
  onRetry: (doc: Document) => Promise<void>;
}

const FF = font.ui;

const ACCEPTED_TYPES = '.pdf,.txt,.text';
const MAX_MB = 50;

const DocumentManager: React.FC<DocumentManagerProps> = ({
  documents, onAddDocument, onRemoveDocument, onFetched, onRetry,
}) => {
  const statusCounts = {
    indexed:         documents.filter(d => d.indexStatus === 'indexed').length,
    indexing:        documents.filter(d => d.indexStatus === 'indexing').length,
    queued:          documents.filter(d => d.indexStatus === 'queued').length,
    waiting:         documents.filter(d => d.indexStatus === 'waiting_for_quota').length,
    failed:          documents.filter(d => d.indexStatus === 'failed').length,
  };
  const hasActiveJobs = statusCounts.indexing + statusCounts.queued + statusCounts.waiting > 0;

  const [fetching, setFetching]   = useState(false);
  const [error, setError]         = useState<string | null>(null);

  const [inputValue, setInputValue]         = useState('');
  const [resolvedTicker, setResolvedTicker] = useState<string | null>(null);
  const [suggestions, setSuggestions]       = useState<SearchResult[]>([]);
  const [showDrop, setShowDrop]             = useState(false);
  const [highlightIdx, setHighlightIdx]     = useState(-1);

  // Upload state
  const [uploading, setUploading]       = useState(false);
  const [uploadError, setUploadError]   = useState<string | null>(null);
  const [dragOver, setDragOver]         = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const debouncedInput = useDebounce(inputValue, 200);
  useEffect(() => {
    if (resolvedTicker) { setSuggestions([]); setShowDrop(false); return; }
    const q = debouncedInput.trim();
    if (!q) { setSuggestions([]); setShowDrop(false); return; }
    searchCompanies(q).then(results => {
      setSuggestions(results);
      setShowDrop(results.length > 0);
      setHighlightIdx(-1);
    });
  }, [debouncedInput, resolvedTicker]);

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
      const data = await extractCompany(t, '10-K');
      onAddDocument({
        id: `doc-${Date.now()}`,
        name: `${t} ${data.form}`,
        uploadDate: new Date().toISOString().split('T')[0],
        size: data.char_count ? `${Math.round(data.char_count / 1024)} KB` : '—',
        content: buildContent(data.sections ?? {}),
        ticker: t,
        form: data.form,
        metrics: data.metrics,
        indexStatus: 'queued',
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

  const handleUpload = async (file: File) => {
    if (uploading) return;
    setUploadError(null);

    if (file.size > MAX_MB * 1_048_576) {
      setUploadError(`File is too large (max ${MAX_MB} MB).`);
      return;
    }
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!['pdf', 'txt', 'text'].includes(ext)) {
      setUploadError('Only PDF and TXT files are supported.');
      return;
    }

    setUploading(true);
    try {
      const resp = await uploadFile(file);
      const sizeMB = (file.size / 1_048_576).toFixed(1);
      onAddDocument({
        id: `upload-${Date.now()}`,
        name: resp.filename,
        uploadDate: new Date().toISOString().split('T')[0],
        size: `${sizeMB} MB`,
        content: '',
        // No ticker/form/metrics — this is a plain uploaded document.
        indexStatus: 'queued',
        uploadDocId: resp.doc_id,
      });
    } catch (err) {
      // The backend returns a plain-text error body for 4xx responses.
      const raw = err instanceof Error ? err.message : String(err);
      // Strip the JSON wrapping FastAPI adds around detail strings.
      let msg = raw;
      try {
        const parsed = JSON.parse(raw);
        if (parsed?.detail) msg = parsed.detail;
      } catch { /* not JSON */ }
      setUploadError(msg);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  };

  const canFetch = inputValue.trim() && !fetching;

  return (
    <div style={{ padding: 22, height: '100%', overflowY: 'auto', fontFamily: FF, background: c.bg }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <p style={{ fontSize: 15, fontWeight: 500, color: c.text, margin: '0 0 2px' }}>Document library</p>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>
          Fetch filings from SEC EDGAR or upload a PDF/TXT — each is embedded into a
          searchable vector index for FinChat. Filings embed one at a time to stay within API rate limits.
        </p>
      </div>

      {/* Primary: fetch from EDGAR */}
      <div style={{ background: c.surface, borderRadius: 12, padding: '16px 18px', marginBottom: 12 }}>
        <p style={{ fontSize: 12, color: c.textMuted, margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Fetch from SEC EDGAR
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>

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

        {resolvedTicker && (
          <p style={{ fontSize: 11, color: c.textMuted, margin: '6px 0 0' }}>
            Will fetch <strong style={{ color: c.text }}>{resolvedTicker}</strong> · click Fetch filing
          </p>
        )}

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

      {/* PDF / TXT upload zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !uploading && fileInputRef.current?.click()}
        style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: 6,
          border: `1px dashed ${dragOver ? c.brand : c.border}`,
          borderRadius: 8, padding: '16px 20px', marginBottom: 8,
          cursor: uploading ? 'default' : 'pointer',
          background: dragOver ? c.brandTint : 'transparent',
          transition: 'border-color 0.15s, background 0.15s',
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES}
          onChange={handleFileInput}
          style={{ display: 'none' }}
        />
        {uploading ? (
          <>
            <Loader2 size={20} color={c.brand} style={{ animation: 'spin 1s linear infinite' }} />
            <span style={{ fontSize: 13, color: c.textMuted }}>Uploading…</span>
          </>
        ) : (
          <>
            <UploadCloud size={20} color={dragOver ? c.brand : c.textFaint} />
            <span style={{ fontSize: 13, color: dragOver ? c.brand : c.textMuted }}>
              Drop a PDF or TXT here, or click to browse
            </span>
            <span style={{ fontSize: 11, color: c.textFaint }}>Max {MAX_MB} MB · digital PDFs only (not scanned)</span>
          </>
        )}
      </div>

      {uploadError && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 8,
          marginBottom: 16, padding: '8px 12px', borderRadius: 7,
          background: c.warnSurface, border: `0.5px solid ${c.warnBorder}`,
          fontSize: 12, color: c.warnFg, lineHeight: 1.5,
        }}>
          <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{uploadError}</span>
        </div>
      )}

      {/* Queue summary banner — shown whenever any docs are still in-flight */}
      {documents.length > 0 && (hasActiveJobs || statusCounts.failed > 0) && (() => {
        const parts: string[] = [];
        if (statusCounts.indexed > 0) parts.push(`${statusCounts.indexed} indexed`);
        if (statusCounts.indexing > 0) parts.push(`${statusCounts.indexing} indexing`);
        if (statusCounts.queued > 0) parts.push(`${statusCounts.queued} queued`);
        if (statusCounts.waiting > 0) parts.push(`${statusCounts.waiting} waiting for quota`);
        if (statusCounts.failed > 0) parts.push(`${statusCounts.failed} failed`);
        const isWarning = statusCounts.waiting > 0 || statusCounts.failed > 0;
        return (
          <div style={{
            padding: '6px 12px', borderRadius: 7,
            marginTop: uploadError ? 0 : 8, marginBottom: 10,
            background: isWarning ? c.warnSurface : c.surfaceAlt,
            border: `0.5px solid ${isWarning ? c.warnBorder : c.border}`,
            fontSize: 11, color: isWarning ? c.warnFg : c.textMuted,
          }}>
            {parts.join(' · ')}
          </div>
        );
      })()}

      {/* Document list */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10, marginTop: (documents.length === 0 || (!hasActiveJobs && statusCounts.failed === 0)) && !uploadError ? 8 : 0 }}>
        <p style={{ fontSize: 13, color: c.textMuted, margin: 0 }}>Indexed documents</p>
        <span style={{ fontSize: 13, color: c.textFaint }}>
          {documents.length} {documents.length === 1 ? 'filing' : 'filings'}
        </span>
      </div>

      <div style={{ border: `0.5px solid ${c.border}`, borderRadius: 12, overflow: 'hidden' }}>
        {documents.length === 0 ? (
          <div style={{ padding: '32px 20px', textAlign: 'center' }}>
            <FileText size={22} color={c.textFaint} style={{ margin: '0 auto 8px', display: 'block' }} />
            <p style={{ fontSize: 13, color: c.textFaint, margin: 0 }}>No filings yet. Fetch from EDGAR or upload a file above.</p>
          </div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {documents.map((doc, i) => (
              <DocRow
                key={doc.id}
                doc={doc}
                last={i === documents.length - 1}
                onRemove={() => onRemoveDocument(doc.id)}
                onRetry={() => onRetry(doc)}
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

  if (status === 'queued') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 11, padding: '2px 7px', borderRadius: 10,
        background: c.accentSoft, color: c.accentFg,
      }}>
        <Clock size={10} style={{ flexShrink: 0 }} />
        Queued
      </span>
    );
  }

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
        fontSize: 11, padding: '2px 7px', borderRadius: 10,
        background: c.brandTint, color: c.brand,
      }} title={chunks ? `${chunks} chunks stored` : undefined}>
        <CheckCircle2 size={10} style={{ flexShrink: 0 }} />
        {chunks ? `${chunks} chunks` : 'Indexed'}
      </span>
    );
  }

  if (status === 'waiting_for_quota') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 11, padding: '2px 7px', borderRadius: 10,
        background: c.warnSurface, color: c.warnFg,
      }} title="Daily Gemini quota exhausted — will auto-retry on a schedule">
        <Clock size={10} style={{ flexShrink: 0 }} />
        Waiting for quota
      </span>
    );
  }

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 11, padding: '2px 7px', borderRadius: 10,
      background: c.warnSurface, color: c.warnFg,
    }} title={error ?? 'Indexing failed'}>
      <AlertTriangle size={10} style={{ flexShrink: 0 }} />
      Index failed
    </span>
  );
};

// --- Document row -----------------------------------------------------------

const DocRow: React.FC<{
  doc: Document;
  last: boolean;
  onRemove: () => void;
  onRetry: () => Promise<void>;
}> = ({ doc, last, onRemove, onRetry }) => {
  const [hovered, setHovered] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const ticker = doc.ticker || doc.name.match(/^([A-Za-z]{1,5})/)?.[1]?.toUpperCase();
  const isUpload = !!doc.uploadDocId;

  const lower = doc.name.toLowerCase();
  const tag = isUpload
    ? (lower.endsWith('.pdf') ? 'PDF' : 'TXT')
    : (doc.form ?? '10-K');
  const tagStyle: React.CSSProperties = isUpload
    ? { background: c.surfaceAlt, color: c.textMuted }
    : { background: c.brandTint, color: c.brand };

  // Show retry for failed or quota-waiting docs that have a retryable key.
  const canRetry = (doc.indexStatus === 'failed' || doc.indexStatus === 'waiting_for_quota')
    && (doc.uploadDocId || (doc.ticker && doc.form));

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  };

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
      <CompanyLogo ticker={isUpload ? undefined : ticker} size={36} radius={7} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          fontSize: 13, fontWeight: 500, color: c.text,
          margin: '0 0 4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {doc.name}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: c.textFaint, flexWrap: 'wrap' }}>
          <span>{doc.size}</span>
          <span>·</span>
          <span>Added {doc.uploadDate}</span>
          <span>·</span>
          <IndexBadge status={doc.indexStatus} chunks={doc.indexChunks} error={doc.indexError} />
          {canRetry && (
            <button
              onClick={handleRetry}
              disabled={retrying}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 3,
                fontSize: 11, padding: '2px 7px', borderRadius: 10,
                background: retrying ? c.surfaceAlt : c.warnSurface,
                color: retrying ? c.textFaint : c.warnFg,
                border: `0.5px solid ${c.warnBorder}`,
                cursor: retrying ? 'default' : 'pointer',
                fontFamily: FF,
              }}
            >
              <RotateCcw size={9} style={{
                flexShrink: 0,
                ...(retrying ? { animation: 'spin 1s linear infinite' } : {}),
              }} />
              {retrying ? 'Queuing…' : 'Retry'}
            </button>
          )}
        </div>
      </div>

      <span style={{
        ...tagStyle,
        fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 500, flexShrink: 0,
      }}>
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
