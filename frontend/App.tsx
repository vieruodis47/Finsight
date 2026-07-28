import React, { useState } from 'react';
import {
  LayoutDashboard, Files, MessageSquare, BarChart3,
  TrendingUp, Building2, Plus, Settings,
  PanelLeftClose, PanelLeftOpen,
  HelpCircle, X, ArrowLeftRight, Menu,
} from 'lucide-react';
import { ViewState, Document, IndexStatus } from './types';
import { c, font } from './theme';
import HelpView from './components/HelpView';
import Dashboard from './components/Dashboard';
import DocumentManager from './components/DocumentManager';
import ChatInterface from './components/ChatInterface';
import AnalysisView from './components/AnalysisView';
import CompareView from './components/CompareView';
import SettingsView from './components/SettingsView';
import NotFound from './components/NotFound';
import ErrorBoundary from './components/ErrorBoundary';
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
import { ChatProvider } from './context/ChatContext';
import { useIsTablet, useIsMobile, useRoute, useOnClickOutside, viewPath } from './utils/hooks';

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
  settings: 'Workspace preferences',
};

const FF = font.ui;

const App: React.FC = () => {
  const isTablet = useIsTablet();
  const isMobile = useIsMobile();          // <= 768px: sidebar becomes an off-canvas drawer
  const { route, navigate }                 = useRoute();
  const [showSplash, setShowSplash]         = useState(true);
  // The active top-level screen is DERIVED from the URL (single source of truth),
  // so a hard refresh / deep link on /analysis, /documents, … lands on the right
  // screen and browser back/forward Just Works. A /company URL shows the
  // dashboard; /compare and /notfound render their own branch below.
  const currentView: ViewState = route.name === 'view' ? route.view : 'dashboard';
  const [documents, setDocuments]           = useState<Document[]>([]);
  const [collapsed, setCollapsed]           = useState(false);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [comparePickerOpen, setComparePickerOpen] = useState(false);
  const [drawerOpen, setDrawerOpen]         = useState(false);
  const comparePickerWrapRef = React.useRef<HTMLDivElement>(null);
  const sidebarRef  = React.useRef<HTMLElement>(null);
  const hamburgerRef = React.useRef<HTMLButtonElement>(null);
  useOnClickOutside(comparePickerWrapRef, () => setComparePickerOpen(false), comparePickerOpen);

  // Collapse to an icon rail on tablet, but NOT on mobile — there the sidebar is
  // a full-width overlay drawer, so it must show labels, not icons.
  React.useEffect(() => { setCollapsed(isTablet && !isMobile); }, [isTablet, isMobile]);

  // Close the drawer whenever we leave the mobile range (so it can't be stuck
  // open behind a now-fixed sidebar) or navigate to a different view/route.
  React.useEffect(() => { if (!isMobile) setDrawerOpen(false); }, [isMobile]);
  React.useEffect(() => { setDrawerOpen(false); }, [route]);

  const closeDrawer = React.useCallback(() => {
    setDrawerOpen(false);
    hamburgerRef.current?.focus(); // return focus to the trigger
  }, []);

  // While the drawer is a modal overlay: trap focus inside it, close on Escape,
  // and move focus to the first control on open. When closed on mobile it is
  // marked `inert` (below) so it's unreachable by tab / screen readers.
  React.useEffect(() => {
    if (!(isMobile && drawerOpen)) return;
    const node = sidebarRef.current;
    if (!node) return;
    const focusable = () =>
      Array.from(
        node.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter(el => el.offsetParent !== null);
    focusable()[0]?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); closeDrawer(); return; }
      if (e.key !== 'Tab') return;
      const f = focusable();
      if (f.length === 0) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    node.addEventListener('keydown', onKeyDown);
    return () => node.removeEventListener('keydown', onKeyDown);
  }, [isMobile, drawerOpen, closeDrawer]);

  // `inert` on the closed mobile drawer: removes it from the tab order AND the
  // accessibility tree, so an off-screen sidebar is never focusable. Set via a
  // ref effect for broad attribute support.
  React.useEffect(() => {
    const node = sidebarRef.current;
    if (!node) return;
    if (isMobile && !drawerOpen) node.setAttribute('inert', '');
    else node.removeAttribute('inert');
  }, [isMobile, drawerOpen]);

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

  // Switch to a top-level nav screen by navigating to its URL. Because
  // currentView is derived from the route, this one call updates the URL, the
  // rendered screen, the active-nav highlight, and browser history together —
  // and works identically from the compare view, a /company URL, or a 404.
  const selectView = (view: ViewState) => navigate(viewPath(view));

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
          setDocuments(prev => {
            // Only produce a new array/object when something actually changed.
            // Returning `prev` unchanged keeps the `documents` reference stable,
            // so this effect (keyed on [documents]) does NOT tear down and
            // recreate the interval — and the whole app doesn't re-render every
            // 2.5s forever while a filing sits in "indexing". A changed status
            // (e.g. indexing -> indexed) still updates once and lets the effect
            // re-run, dropping the now-complete doc from the polling set.
            const nextError = status.error ?? undefined;
            let changed = false;
            const next = prev.map(d => {
              if (d.id !== doc.id) return d;
              if (
                d.indexStatus === (status.status as IndexStatus) &&
                d.indexChunks === status.chunks &&
                d.indexError === nextError
              ) {
                return d;
              }
              changed = true;
              return {
                ...d,
                indexStatus: status.status as IndexStatus,
                indexChunks: status.chunks,
                indexError:  nextError,
              };
            });
            return changed ? next : prev;
          });
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
    // currentView is derived from the route ('company' → dashboard), so no view
    // state to set here.
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

  // ChatProvider wraps EVERY return path (splash, getting-started, main shell)
  // and is the top-level element each time, so React keeps the single provider
  // instance mounted across all of these transitions and across in-app
  // navigation — that is what makes the FinChat conversation (and any in-flight
  // stream) survive leaving and returning to the chat route.
  if (showSplash) {
    return (
      <ChatProvider documents={documents}>
        <SplashScreen onGetStarted={() => setShowSplash(false)} />
      </ChatProvider>
    );
  }

  // A route that names a ticker (/company/:ticker or /compare/:anchor/:peer)
  // is intent, even with zero documents added — e.g. a shared link opened in
  // a fresh session. /company populates the dashboard via the fetchMetrics
  // effect above (free XBRL read, no embed); /compare fetches directly by
  // ticker (compare-metrics/market work for any SEC ticker). Neither should be
  // swallowed by the empty-documents gate. `notfound` falls through to the app
  // shell below, which renders the 404 page (with nav still available).
  if (documents.length === 0 && route.name === 'view' && route.view === 'dashboard') {
    return (
      <ChatProvider documents={documents}>
        <GettingStarted onAddCompany={handleAddCompany} />
      </ChatProvider>
    );
  }

  const renderView = () => {
    switch (currentView) {
      case 'dashboard': return <Dashboard documents={documents} selectedTicker={selectedTicker} />;
      case 'documents': return <DocumentManager documents={documents} onAddDocument={handleAddDocument} onRemoveDocument={handleRemoveDocument} onFetched={() => navigate(viewPath('dashboard'))} onRetry={handleRetry} />;
      case 'chat':      return <ChatInterface documents={documents} />;
      case 'analysis':  return <AnalysisView documents={documents} />;
      case 'help':      return <HelpView />;
      case 'settings':  return <SettingsView />;
      default:          return <Dashboard documents={documents} selectedTicker={selectedTicker} />;
    }
  };

  // Topbar reflects the real route: a /compare URL shows "Compare · A vs B"
  // rather than the (stale) current sidebar view. The "Compare with peers" CTA
  // shows only on a company dashboard with a selection — never on the compare
  // view itself.
  const isCompareRoute = route.name === 'compare';
  const isNotFound = route.name === 'notfound';
  const settingsLabel = 'Settings';
  const topbarTitle = isCompareRoute
    ? 'Compare'
    : isNotFound
    ? 'Not found'
    : currentView === 'settings'
    ? settingsLabel
    : (NAV_ITEMS.find(n => n.view === currentView)?.label ?? 'Dashboard');
  const topbarSubtitle = isCompareRoute
    ? `${route.anchor.toUpperCase()} vs ${route.peer.toUpperCase()}`
    : isNotFound
    ? 'This page could not be found'
    : TOPBAR_SUBTITLES[currentView];
  // The compare CTA belongs only on a company dashboard with a selection — never
  // on the compare view itself or a 404.
  const showCompareCta = !isCompareRoute && !isNotFound && currentView === 'dashboard' && !!selectedTicker;

  // Which sidebar item is visually highlighted, derived from the ACTUAL route so
  // it stays correct on direct URL entry and browser back/forward — not just on
  // click. /compare highlights its parent section (Dashboard); a 404 highlights
  // nothing. `aria-current="page"` is set only on a genuine current page (a
  // top-level view), never on the parent-highlight for compare or on a 404.
  const activeView: ViewState | null = isNotFound ? null : isCompareRoute ? 'dashboard' : currentView;
  const currentPageView: ViewState | null = isCompareRoute || isNotFound ? null : currentView;

  // The sidebar is an in-flow rail on tablet/desktop and a fixed off-canvas
  // drawer on mobile. Same markup, different framing.
  const asideStyle: React.CSSProperties = isMobile
    ? {
        position: 'fixed', top: 0, left: 0, bottom: 0,
        width: 'min(84vw, 280px)',
        background: c.surface, borderRight: `0.5px solid ${c.border}`,
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        zIndex: 60,
        transform: drawerOpen ? 'translateX(0)' : 'translateX(-100%)',
        transition: 'transform 0.25s ease',
        boxShadow: drawerOpen ? '2px 0 16px rgba(15,23,42,0.18)' : 'none',
      }
    : {
        width: collapsed ? 52 : 216, minWidth: collapsed ? 52 : 216,
        background: c.surface, borderRight: `0.5px solid ${c.border}`,
        display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden',
        transition: 'width 0.2s ease, min-width 0.2s ease',
      };

  return (
    <ChatProvider documents={documents}>
    <div className="app-root" style={{ display: 'flex', overflow: 'hidden', fontFamily: FF }}>

      {/* Backdrop behind the mobile drawer (click to dismiss). */}
      {isMobile && drawerOpen && (
        <div
          aria-hidden="true"
          onClick={closeDrawer}
          style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.40)', zIndex: 55 }}
        />
      )}

      {/* ── Sidebar (in-flow rail on desktop/tablet, off-canvas drawer on mobile) ── */}
      <aside
        ref={sidebarRef}
        id="app-sidebar"
        role={isMobile ? 'dialog' : undefined}
        aria-modal={isMobile && drawerOpen ? true : undefined}
        aria-label={isMobile ? 'Main navigation' : undefined}
        style={asideStyle}
      >
        {/* Logo row */}
        <div style={{ height: 52, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 9, borderBottom: `0.5px solid ${c.border}`, flexShrink: 0 }}>
          {/* Logo → home. Uses selectView('dashboard') — the exact navigation the
              Dashboard nav item uses. A <button> (not <a href>) because top-level
              screens are state-based views in this SPA router, not URLs; an href
              would trigger a full reload and drop in-memory state. */}
          <button
            type="button"
            className="logo-home"
            onClick={() => selectView('dashboard')}
            aria-label="FinSight home"
            style={{
              display: 'flex', alignItems: 'center', gap: 9,
              background: 'transparent', border: 'none', cursor: 'pointer',
              padding: isMobile ? '3px 8px' : '3px 4px', margin: '-3px -4px', borderRadius: 8,
              // ≥44px tall tap target on mobile (WCAG 2.5.5); the icon+wordmark
              // alone are only ~32px high.
              minHeight: isMobile ? 44 : undefined,
              fontFamily: FF, textAlign: 'left',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            <div style={{ width: 26, height: 26, minWidth: 26, borderRadius: 6, background: c.brandTint, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <TrendingUp size={13} color={c.brand} />
            </div>
            {!collapsed && (
              <span style={{ fontSize: 15, fontWeight: 500, color: c.text, whiteSpace: 'nowrap' }}>
                Fin<span style={{ color: c.brand }}>Sight</span>
              </span>
            )}
          </button>
          <button
            onClick={isMobile ? closeDrawer : () => setCollapsed(c => !c)}
            title={isMobile ? 'Close menu' : collapsed ? 'Expand' : 'Collapse'}
            aria-label={isMobile ? 'Close menu' : collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            style={{ marginLeft: 'auto', width: isMobile ? 44 : 24, height: isMobile ? 44 : 24, minWidth: isMobile ? 44 : 24, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: c.textFaint, flexShrink: 0 }}
            onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            {isMobile ? <X size={20} /> : collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
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
            const active = activeView === view;
            return (
              <button
                key={view}
                onClick={() => selectView(view)}
                title={collapsed ? label : undefined}
                aria-current={currentPageView === view ? 'page' : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: 9,
                  padding: isMobile ? '10px 12px' : '7px 10px', minHeight: isMobile ? 44 : undefined,
                  borderRadius: 6,
                  fontSize: isMobile ? 14 : 13, fontWeight: active ? 500 : 400,
                  color: active ? c.brand : c.navInactive,
                  background: active ? c.brandTint : 'transparent',
                  // Active-state left indicator (inset shadow = no layout shift).
                  boxShadow: active ? `inset 2px 0 0 ${c.brand}` : 'none',
                  border: 'none', cursor: 'pointer',
                  width: '100%', textAlign: 'left',
                  whiteSpace: 'nowrap', fontFamily: FF,
                  transition: 'background 0.1s, color 0.1s',
                }}
                onMouseEnter={e => { if (!active) { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; } }}
                onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.navInactive; } }}
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
            // A company is "current" only on its own /company dashboard, never on
            // a 404. On /compare the anchor stays visually selected (you compare
            // from it) but is not the current page for aria purposes.
            const active = key === selectedTicker && activeView === 'dashboard';
            const isCurrentPage = active && route.name === 'company';
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
                  aria-current={isCurrentPage ? 'page' : undefined}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 9, padding: isMobile ? '10px 12px' : '7px 10px', minHeight: isMobile ? 44 : undefined, borderRadius: 6,
                    fontSize: isMobile ? 14 : 12, fontWeight: active ? 500 : 400,
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
            style={{ display: 'flex', alignItems: 'center', gap: 9, padding: isMobile ? '10px 12px' : '7px 10px', minHeight: isMobile ? 44 : undefined, borderRadius: 6, fontSize: isMobile ? 14 : 12, color: c.textFaint, background: 'transparent', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left', whiteSpace: 'nowrap', fontFamily: FF }}
            onMouseEnter={e => { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.textMuted; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.textFaint; }}
          >
            <span style={{ flexShrink: 0, minWidth: 17, display: 'flex' }}><Plus size={16} /></span>
            {!collapsed && <span>Add company</span>}
          </button>
        </nav>

        {/* Settings */}
        <div style={{ padding: 8, borderTop: `0.5px solid ${c.border}`, flexShrink: 0 }}>
          {(() => {
            const active = activeView === 'settings';
            return (
              <button
                onClick={() => selectView('settings')}
                title={collapsed ? 'Settings' : undefined}
                aria-current={currentPageView === 'settings' ? 'page' : undefined}
                style={{ display: 'flex', alignItems: 'center', gap: 9, padding: isMobile ? '10px 12px' : '7px 10px', minHeight: isMobile ? 44 : undefined, borderRadius: 6, fontSize: isMobile ? 14 : 13, fontWeight: active ? 500 : 400, color: active ? c.brand : c.textMuted, background: active ? c.brandTint : 'transparent', boxShadow: active ? `inset 2px 0 0 ${c.brand}` : 'none', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left', whiteSpace: 'nowrap', fontFamily: FF }}
                onMouseEnter={e => { if (!active) { e.currentTarget.style.background = c.hover; e.currentTarget.style.color = c.text; } }}
                onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = c.textMuted; } }}
              >
                <span style={{ flexShrink: 0, minWidth: 17, display: 'flex' }}><Settings size={17} /></span>
                {!collapsed && <span>Settings</span>}
              </button>
            );
          })()}
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: c.bg }}>

        {/* Topbar — explicit white bg so text contrast is computed against a
            known background (the header is otherwise transparent). */}
        <header style={{ height: 52, background: c.bg, borderBottom: `0.5px solid ${c.border}`, display: 'flex', alignItems: 'center', padding: isMobile ? '0 10px' : '0 20px', gap: 8, flexShrink: 0 }}>
          {/* Hamburger — opens the drawer. Only rendered on mobile. */}
          {isMobile && (
            <button
              ref={hamburgerRef}
              onClick={() => setDrawerOpen(true)}
              aria-label="Open menu"
              aria-expanded={drawerOpen}
              aria-controls="app-sidebar"
              style={{ width: 44, height: 44, minWidth: 44, display: 'flex', alignItems: 'center', justifyContent: 'center', marginLeft: -6, borderRadius: 8, border: 'none', background: 'transparent', cursor: 'pointer', color: c.text, flexShrink: 0 }}
              onMouseEnter={e => (e.currentTarget.style.background = c.hover)}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <Menu size={20} />
            </button>
          )}
          <span style={{ fontSize: 15, fontWeight: 500, color: c.text, whiteSpace: 'nowrap' }}>
            {topbarTitle}
          </span>
          {/* Subtitle (+ decorative dot) — dropped on mobile to prevent the
              header from overflowing at narrow widths. */}
          {!isMobile && (
            <>
              <span aria-hidden="true" style={{ width: 3, height: 3, borderRadius: '50%', background: c.border, flexShrink: 0 }} />
              <span style={{ fontSize: 13, color: c.textMuted }}>
                {topbarSubtitle}
              </span>
            </>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
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
                  aria-label="Compare with peers"
                  style={{ display: 'flex', alignItems: 'center', gap: 6, height: isMobile ? 44 : 30, width: isMobile ? 44 : undefined, justifyContent: 'center', padding: isMobile ? 0 : '0 12px', borderRadius: 7, border: 'none', background: c.brandDeep, color: c.onBrand, fontSize: 13, fontWeight: 500, cursor: 'pointer', fontFamily: FF }}
                  onMouseEnter={e => (e.currentTarget.style.background = c.brandDeepHover)}
                  onMouseLeave={e => (e.currentTarget.style.background = c.brandDeep)}
                >
                  <ArrowLeftRight size={isMobile ? 18 : 14} />
                  {/* Icon-only on mobile to keep the header from overflowing. */}
                  {!isMobile && 'Compare with peers'}
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
          </div>
        </header>

        {/* Page content. Wrapped in an ErrorBoundary so a render exception in
            one view (e.g. a chart fed a partial/malformed response) degrades to
            a readable, retryable card instead of white-screening the whole app —
            the sidebar and nav stay usable. resetKey is the active view/route,
            so navigating away clears the error automatically. */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <ErrorBoundary
            label={isCompareRoute ? 'the comparison' : (currentView === 'analysis' ? 'the analysis' : 'this view')}
            resetKey={isCompareRoute ? `compare:${route.anchor}:${route.peer}` : isNotFound ? `notfound:${route.path}` : `view:${currentView}`}
          >
            {route.name === 'compare'
              ? <CompareView
                  anchor={route.anchor.toUpperCase()}
                  peer={route.peer.toUpperCase()}
                  peers={comparePeers}
                  onBack={() => navigateToCompany(route.anchor)}
                  onSelectPeer={p => navigateToCompare(route.anchor, p)}
                />
              : route.name === 'notfound'
              ? <NotFound path={route.path} onHome={() => navigate('/')} />
              : renderView()}
          </ErrorBoundary>
        </div>
      </main>
    </div>
    </ChatProvider>
  );
};

export default App;
