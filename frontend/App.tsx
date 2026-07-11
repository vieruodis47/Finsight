import React, { useState } from 'react';
import {
  LayoutDashboard, Files, MessageSquare, BarChart3,
  TrendingUp, Building2, Plus, Settings,
  PanelLeftClose, PanelLeftOpen,
  HelpCircle, X, ArrowLeftRight,
} from 'lucide-react';
import { ViewState, Document, IndexStatus } from './types';
import { c, font } from './theme';
import HelpView from './components/HelpView';
import Dashboard from './components/Dashboard';
import DocumentManager from './components/DocumentManager';
import ChatInterface from './components/ChatInterface';
import AnalysisView from './components/AnalysisView';
import CompareView from './components/CompareView';
import PeerPicker from './components/PeerPicker';
import SplashScreen from './components/SplashScreen';
import GettingStarted from './components/GettingStarted';
import {
  extractCompany, buildContent,
  getIngestStatus, retryIngest,
  getUploadStatus, retryUpload,
  fetchMetrics,
} from './services/gemini';
import { companyKey } from './utils/company';
import { useIsTablet, useRoute, useOnClickOutside } from './utils/hooks';

const NAV_ITEMS: { view: ViewState; label: string; icon: React.ReactNode }[] = [
  { view: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={17} /> },
  { view: 'documents', label: 'Documents',  icon: <Files size={17} /> },
  { view: 'chat',      label: 'FinChat', icon: <MessageSquare size={17} /> },
  { view: 'analysis',  label: 'Analysis',   icon: <BarChart3 size={17} /> },
  { view: 'help', label: 'Help', icon: <HelpCircle size={17} /> },
];

const TOPBAR_SUBTITLES: Record<ViewState, string> = {
  dashboard: 'Financial research workspace',
  documents: 'Upload and manage filings',
  chat:      'Ask questions across your loaded filings',
  analysis:  'Metrics, charts, and peer comparisons',
  help: 'Tips for getting the best answers from FinSight',
};

const FF = font.ui;

const App: React.FC = () => {
  const isTablet = useIsTablet();
  const { route, navigate }                 = useRoute();
  const [showSplash, setShowSplash]         = useState(true);
  const [currentView, setCurrentView]       = useState<ViewState>('dashboard');
  const [documents, setDocuments]           = useState<Document[]>([]);
  const [collapsed, setCollapsed]           = useState(false);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [comparePickerOpen, setComparePickerOpen] = useState(false);
  const comparePickerWrapRef = React.useRef<HTMLDivElement>(null);
  useOnClickOutside(comparePickerWrapRef, () => setComparePickerOpen(false), comparePickerOpen);

  React.useEffect(() => { setCollapsed(isTablet); }, [isTablet]);

  // Single place that changes "which company is selected" — always updates
  // the URL, which then flows back into state via the effect below.
  const navigateToCompany = (ticker: string) => navigate(`/company/${encodeURIComponent(ticker)}`);

  // Single writer for the compare route. Guard: a falsy anchor or peer is
  // dropped rather than routed, so no caller (topbar CTA, cycler, or picker)
  // can ever produce /compare/x/undefined.
  const navigateToCompare = (anchor: string, peer: string) => {
    if (!anchor || !peer) return;
    navigate(`/compare/${encodeURIComponent(anchor)}/${encodeURIComponent(peer)}`);
  };

  // Switch to a top-level nav view. On a /compare route this MUST also leave the
  // route: the page-content switch below renders CompareView whenever
  // route.name === 'compare', taking precedence over currentView — so setting
  // currentView alone would change state that never renders (the sidebar would
  // look dead). navigate('/') clears the compare route so renderView() runs.
  // Not needed on /company routes: those don't override currentView.
  const selectView = (view: ViewState) => {
    setCurrentView(view);
    if (route.name === 'compare') navigate('/');
  };

  const [hoveredCompany, setHoveredCompany] = useState<string | null>(null);

  const handleAddDocument = (doc: Document) => {
    setDocuments(prev => [doc, ...prev]);
    setSelectedTicker(companyKey(doc));
  };
  const handleRemoveDocument = (id: string) => setDocuments(prev => prev.filter(d => d.id !== id));
  const handleRemoveCompany = (key: string) => setDocuments(prev => prev.filter(d => companyKey(d) !== key));
  const handleUpdateDocument = (id: string, updates: Partial<Document>) =>
    setDocuments(prev => prev.map(d => d.id === id ? { ...d, ...updates } : d));

  // Poll for ingest completion on any document that is queued or indexing.
  // Uploaded files use /upload-status/{doc_id}; EDGAR filings use /ingest-status/{ticker}.
  React.useEffect(() => {
    const pending = documents.filter(
      d => (d.indexStatus === 'queued' || d.indexStatus === 'indexing' || d.indexStatus === 'waiting_for_quota')
        && (d.uploadDocId || (d.ticker && d.form)),
    );
    if (pending.length === 0) return;

    const timer = setInterval(async () => {
      for (const doc of pending) {
        try {
          const status = doc.uploadDocId
            ? await getUploadStatus(doc.uploadDocId)
            : await getIngestStatus(doc.ticker!, doc.form!);
          setDocuments(prev =>
            prev.map(d =>
              d.id === doc.id
                ? {
                    ...d,
                    indexStatus: status.status as IndexStatus,
                    indexChunks: status.chunks,
                    indexError:  status.error ?? undefined,
                  }
                : d,
            ),
          );
        } catch {
          // Transient network error — keep polling.
        }
      }
    }, 2500);

    return () => clearInterval(timer);
  }, [documents]);

  // Retry handler: delegates to the right backend endpoint based on doc type.
  const handleRetry = React.useCallback(async (doc: Document) => {
    handleUpdateDocument(doc.id, { indexStatus: 'queued', indexError: undefined });
    try {
      if (doc.uploadDocId) {
        await retryUpload(doc.uploadDocId);
      } else if (doc.ticker && doc.form) {
        await retryIngest(doc.ticker, doc.form);
      }
    } catch (e) {
      handleUpdateDocument(doc.id, {
        indexStatus: 'failed',
        indexError: e instanceof Error ? e.message : 'Retry request failed',
      });
    }
  }, []);

  // Backfill content for docs that were added before the section-extraction fix.
  // Only targets docs that came from /extract (have ticker + metrics) but have no
  // content yet. Uses a ref so a filing with no parseable sections doesn't loop.
  const backfilledRef = React.useRef(new Set<string>());
  React.useEffect(() => {
    const stale = documents.filter(
      d => d.ticker && !d.content && !backfilledRef.current.has(d.id),
    );
    if (stale.length === 0) return;
    const doc = stale[0];
    backfilledRef.current.add(doc.id);
    extractCompany(doc.ticker!, (doc.form as '10-K') ?? '10-K')
      .then(data => {
        const content = buildContent(data.sections ?? {});
        if (!content) return;
        setDocuments(prev =>
          prev.map(d =>
            d.id === doc.id
              ? {
                  ...d,
                  content,
                  form: d.form ?? data.form,
                  indexStatus: 'queued' as IndexStatus,
                  ...(data.sector && !d.sector ? { sector: data.sector } : {}),
                }
              : d,
          ),
        );
      })
      .catch(() => {});
  }, [documents]);

  // Companies derived from loaded documents (deduped by ticker), so the sidebar
  // reflects what's actually ingested rather than a hardcoded list.
  const companies = React.useMemo(() => {
    const out: { key: string; label: string }[] = [];
    const seen = new Set<string>();
    for (const d of documents) {
      const label = d.ticker || d.name;
      const key = label.toUpperCase();
      if (!seen.has(key)) { seen.add(key); out.push({ key, label }); }
    }
    return out;
  }, [documents]);

  // Companies other than the currently selected one — the topbar "Compare with
  // peers" fast path routes to the first of these (sidebar order, uppercase keys).
  const otherCompanies = React.useMemo(
    () => companies.map(co => co.key).filter(k => k !== (selectedTicker ?? '').toUpperCase()),
    [companies, selectedTicker],
  );

  // Stable peer cycle for the compare view: sidebar-ordered loaded companies
  // with the anchor removed, plus the route's peer appended at the tail when it
  // isn't loaded (a deep link to an unloaded company). Deterministic for a given
  // (route, companies), so the cycler's wraparound order is stable across
  // re-renders and the peer being viewed is always a member.
  const comparePeers = React.useMemo(() => {
    if (route.name !== 'compare') return [];
    const anchorKey = route.anchor.toUpperCase();
    const peerKey = route.peer.toUpperCase();
    const loaded = companies.map(co => co.key).filter(k => k !== anchorKey);
    return loaded.includes(peerKey) ? loaded : [...loaded, peerKey];
  }, [route, companies]);

  // Keep the selection valid: if nothing is selected yet, or the selected
  // company was deleted, fall back to the most recent filing (or clear it).
  React.useEffect(() => {
    if (documents.length === 0) { setSelectedTicker(null); return; }
    const exists = selectedTicker && documents.some(d => companyKey(d) === selectedTicker);
    if (!exists) setSelectedTicker(companyKey(documents[0]));
  }, [documents, selectedTicker]);

  // Entry point for the getting-started search:
  // 1. Add an optimistic placeholder so the dashboard appears immediately.
  // 2. Call /extract, which runs the EDGAR + companyfacts pipeline and kicks
  //    off background ingest into RavenDB.
  // 3. Replace the placeholder with the real metrics-filled document and set
  //    indexStatus: 'indexing' so the polling effect starts watching it.
  const handleAddCompany = async (query: string) => {
    const ticker = query.trim().toUpperCase();
    if (!ticker) return;

    const id = Date.now().toString();
    handleAddDocument({
      id,
      name: ticker,
      uploadDate: new Date().toISOString().slice(0, 10),
      size: '—',
      content: '',
      ticker,
    });
    navigateToCompany(ticker);

    try {
      const data = await extractCompany(ticker, '10-K');
      setDocuments(prev =>
        prev.map(d =>
          d.id === id
            ? {
                ...d,
                name: data.ticker || ticker,
                form: data.form,
                metrics: data.metrics,
                content: buildContent(data.sections ?? {}),
                indexStatus: 'queued' as IndexStatus,
                ...(data.sector ? { sector: data.sector } : {}),
              }
            : d,
        ),
      );
    } catch (err) {
      console.error(`Failed to extract ${ticker}:`, err);
    }
  };

  // /company/:ticker -> dashboard view + selection. This is the one direction
  // (URL -> state) the router owns; the other direction goes through
  // navigateToCompany() above so the two never drift apart.
  React.useEffect(() => {
    if (route.name !== 'company') return;
    setSelectedTicker(route.ticker.toUpperCase());
    setCurrentView('dashboard');
  }, [route]);

  // Deep-link render WITHOUT ingest. For a /company/:ticker with no local
  // document yet (a shared link, a bookmark, a fresh session), populate the
  // dashboard from GET /metrics — a free XBRL read that NEVER enqueues
  // embedding. This is the key quota property: a passively-opened URL renders
  // full fundamentals but spends zero Gemini quota. Embedding stays gated
  // behind an explicit click, and index status now gates only the FinChat
  // strip (built later), not the dashboard.
  //
  // fetchMetrics fails soft to null (bad ticker / transient) -> no document is
  // added -> the dashboard shows its existing empty state, no crash. Adding to
  // `documents` reuses the existing Dashboard (which renders from state) with
  // zero new render path; the `documents.some(...)` guard + `cancelled` flag
  // prevent double-adds across re-runs and React strict-mode double-invoke.
  React.useEffect(() => {
    if (route.name !== 'company') return;
    const ticker = route.ticker.toUpperCase();
    if (documents.some(d => companyKey(d) === ticker)) return;

    let cancelled = false;
    fetchMetrics(ticker).then(data => {
      if (cancelled || !data) return;
      handleAddDocument({
        id: `deeplink-${ticker}-${Date.now()}`,
        name: data.ticker || ticker,
        uploadDate: new Date().toISOString().slice(0, 10),
        size: '—',
        content: '',
        ticker,
        form: data.form,
        metrics: data.metrics,
        ...(data.sector ? { sector: data.sector } : {}),
      });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, documents]);

  if (showSplash) {
    return <SplashScreen onGetStarted={() => setShowSplash(false)} />;
  }

  // A route that names a ticker (/company/:ticker or /compare/:anchor/:peer)
  // is intent, even with zero documents added — e.g. a shared link opened in
  // a fresh session. /company populates the dashboard via the fetchMetrics
  // effect above (free XBRL read, no embed); /compare fetches directly by
  // ticker (compare-metrics/market work for any SEC ticker). Neither should be
  // swallowed by the empty-documents gate.
  if (documents.length === 0 && route.name === 'other') {
    return <GettingStarted onAddCompany={handleAddCompany} />;
  }

  const renderView = () => {
    switch (currentView) {
      case 'dashboard': return <Dashboard documents={documents} selectedTicker={selectedTicker} />;
      case 'documents': return <DocumentManager documents={documents} onAddDocument={handleAddDocument} onRemoveDocument={handleRemoveDocument} onFetched={() => setCurrentView('dashboard')} onRetry={handleRetry} />;
      case 'chat':      return <ChatInterface documents={documents} />;
      case 'analysis':  return <AnalysisView documents={documents} />;
      case 'help':      return <HelpView />;
      default:          return <Dashboard documents={documents} selectedTicker={selectedTicker} />;
    }
  };

  // Topbar reflects the real route: a /compare URL shows "Compare · A vs B"
  // rather than the (stale) current sidebar view. The "Compare with peers" CTA
  // shows only on a company dashboard with a selection — never on the compare
  // view itself.
  const isCompareRoute = route.name === 'compare';
  const topbarTitle = isCompareRoute
    ? 'Compare'
    : (NAV_ITEMS.find(n => n.view === currentView)?.label ?? 'Dashboard');
  const topbarSubtitle = isCompareRoute
    ? `${route.anchor.toUpperCase()} vs ${route.peer.toUpperCase()}`
    : TOPBAR_SUBTITLES[currentView];
  const showCompareCta = !isCompareRoute && currentView === 'dashboard' && !!selectedTicker;

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', fontFamily: FF }}>

      {/* ── Sidebar ── */}
      <aside
        style={{
          width:         collapsed ? 52 : 216,
          minWidth:      collapsed ? 52 : 216,
          background:    c.surface,
          borderRight:   `0.5px solid ${c.border}`,
          display:       'flex',
          flexDirection: 'column',
          flexShrink:    0,
          overflow:      'hidden',
          transition:    'width 0.2s ease, min-width 0.2s ease',
        }}
      >
        {/* Logo row */}
        <div style={{ height: 52, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 9, borderBottom: `0.5px solid ${c.border}`, flexShrink: 0 }}>
          <div style={{ width: 26, height: 26, minWidth: 26, borderRadius: 6, background: c.brandTint, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <TrendingUp size={13} color={c.brand} />
          </div>
          {!collapsed && (
            <span style={{ fontSize: 15, fontWeight: 500, color: c.text, whiteSpace: 'nowrap' }}>
              Fin<span style={{ color: c.brand }}>Sight</span>
            </span>
          )}
          <button
            onClick={() => setCollapsed(c => !c)}
            title={collapsed ? 'Expand' : 'Collapse'}
            style={{ marginLeft: 'auto', width: 24, height: 24, minWidth: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: c.textFaint, flexShrink: 0 }}
            onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          </button>
        </div>

        {/* Nav items */}
        <nav style={{ flex: 1, padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: 2, overflow: 'hidden' }}>
          {!collapsed && (
            <p style={{ fontSize: 11, color: c.textFaint, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '8px 8px 4px', margin: 0, whiteSpace: 'nowrap' }}>
              Main
            </p>
          )}

          {NAV_ITEMS.map(({ view, label, icon }) => {
            const active = currentView === view;
            return (
              <button
                key={view}
                onClick={() => selectView(view)}
                title={collapsed ? label : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: 9,
                  padding: '7px 10px', borderRadius: 6,
                  fontSize: 13, fontWeight: active ? 500 : 400,
                  color: active ? c.brand : c.textMuted,
                  background: active ? c.brandTint : 'transparent',
                  border: 'none', cursor: 'pointer',
                  width: '100%', textAlign: 'left',
                  whiteSpace: 'nowrap', fontFamily: FF,
                  transition: 'background 0.1s, color 0.1s',
                }}
                onMouseEnter={e => { if (!active) { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; } }}
                onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.textMuted; } }}
              >
                <span style={{ flexShrink: 0, minWidth: 17, display: 'flex' }}>{icon}</span>
                {!collapsed && <span>{label}</span>}
                {!collapsed && view === 'documents' && documents.length > 0 && (
                  <span style={{ marginLeft: 'auto', fontSize: 11, padding: '1px 7px', borderRadius: 10, background: active ? c.peer : c.surfaceAlt, color: active ? c.brandDeep : c.textMuted, fontWeight: 500 }}>
                    {documents.length}
                  </span>
                )}
              </button>
            );
          })}

          {/* Companies — derived from loaded documents */}
          {!collapsed && companies.length > 0 && (
            <p style={{ fontSize: 11, color: c.textFaint, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '12px 8px 4px', margin: 0, whiteSpace: 'nowrap' }}>
              Companies
            </p>
          )}
          {companies.map(({ key, label }) => {
            const active = key === selectedTicker && currentView === 'dashboard';
            const hovered = hoveredCompany === key;
            return (
              <div
                key={key}
                style={{ position: 'relative', display: 'flex', alignItems: 'center' }}
                onMouseEnter={() => setHoveredCompany(key)}
                onMouseLeave={() => setHoveredCompany(null)}
              >
                <button
                  onClick={() => navigateToCompany(key)}
                  title={collapsed ? label : undefined}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px', borderRadius: 6,
                    fontSize: 12, fontWeight: active ? 500 : 400,
                    color: active ? c.brand : hovered ? c.text : c.textMuted,
                    background: active ? c.brandTint : hovered ? c.hover : 'transparent',
                    border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left', whiteSpace: 'nowrap', fontFamily: FF,
                    transition: 'background 0.1s, color 0.1s',
                    paddingRight: hovered && !collapsed ? 28 : 10,
                  }}
                >
                  <span style={{ flexShrink: 0, minWidth: 17, display: 'flex' }}><Building2 size={16} /></span>
                  {!collapsed && <span>{label}</span>}
                </button>
                {hovered && !collapsed && (
                  <button
                    onClick={e => { e.stopPropagation(); handleRemoveCompany(key); }}
                    title={`Remove ${label}`}
                    style={{
                      position: 'absolute', right: 6,
                      width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      borderRadius: 4, border: 'none', background: 'transparent',
                      cursor: 'pointer', color: c.textFaint, padding: 0,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = c.negSurface; e.currentTarget.style.color = c.neg; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.textFaint; }}
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            );
          })}
          <button
            onClick={() => selectView('documents')}
            title={collapsed ? 'Add company' : undefined}
            style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px', borderRadius: 6, fontSize: 12, color: c.textFaint, background: 'transparent', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left', whiteSpace: 'nowrap', fontFamily: FF }}
            onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.textMuted; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.textFaint; }}
          >
            <span style={{ flexShrink: 0, minWidth: 17, display: 'flex' }}><Plus size={16} /></span>
            {!collapsed && <span>Add company</span>}
          </button>
        </nav>

        {/* Settings */}
        <div style={{ padding: 8, borderTop: `0.5px solid ${c.border}`, flexShrink: 0 }}>
          <button
            title="Settings"
            style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '7px 10px', borderRadius: 6, fontSize: 13, color: c.textMuted, background: 'transparent', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left', whiteSpace: 'nowrap', fontFamily: FF }}
            onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.textMuted; }}
          >
            <span style={{ flexShrink: 0, minWidth: 17, display: 'flex' }}><Settings size={17} /></span>
            {!collapsed && <span>Settings</span>}
          </button>
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: c.bg }}>

        {/* Topbar */}
        <header style={{ height: 52, borderBottom: `0.5px solid ${c.border}`, display: 'flex', alignItems: 'center', padding: '0 20px', gap: 8, flexShrink: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 500, color: c.text }}>
            {topbarTitle}
          </span>
          <span style={{ color: c.border }}>·</span>
          <span style={{ fontSize: 13, color: c.textMuted }}>
            {topbarSubtitle}
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
            {showCompareCta && (
              <div ref={comparePickerWrapRef} style={{ position: 'relative' }}>
                <button
                  onClick={() => {
                    const first = otherCompanies[0];
                    if (first) navigateToCompare(selectedTicker!, first);
                    else setComparePickerOpen(o => !o);
                  }}
                  aria-haspopup={otherCompanies.length === 0 ? 'listbox' : undefined}
                  aria-expanded={otherCompanies.length === 0 ? comparePickerOpen : undefined}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px', borderRadius: 7, border: 'none', background: c.brandDeep, color: c.onBrand, fontSize: 13, fontWeight: 500, cursor: 'pointer', fontFamily: FF }}
                  onMouseEnter={e => (e.currentTarget.style.background = c.brandDeepHover)}
                  onMouseLeave={e => (e.currentTarget.style.background = c.brandDeep)}
                >
                  <ArrowLeftRight size={14} />
                  Compare with peers
                </button>
                {/* When peers exist the button routes straight to the first; the
                    picker only opens on the empty-peer-set fallback. */}
                <PeerPicker
                  open={comparePickerOpen}
                  onClose={() => setComparePickerOpen(false)}
                  onSelect={t => { setComparePickerOpen(false); navigateToCompare(selectedTicker!, t); }}
                  exclude={selectedTicker ? [selectedTicker.toUpperCase()] : []}
                  align="right"
                />
              </div>
            )}
            <span style={{ fontSize: 11, fontWeight: 500, padding: '3px 10px', borderRadius: 10, background: c.posSurface, color: c.pos, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: c.pos, display: 'inline-block' }} />
              API connected
            </span>
          </div>
        </header>

        {/* Page content */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          {route.name === 'compare'
            ? <CompareView
                anchor={route.anchor.toUpperCase()}
                peer={route.peer.toUpperCase()}
                peers={comparePeers}
                onBack={() => navigateToCompany(route.anchor)}
                onSelectPeer={p => navigateToCompare(route.anchor, p)}
              />
            : renderView()}
        </div>
      </main>
    </div>
  );
};

export default App;
