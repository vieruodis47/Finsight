import { useState, useEffect, useRef, RefObject } from 'react';
import { breakpoint } from '../theme';
import type { ViewState } from '../types';

/**
 * Returns a debounced copy of `value` that only updates after `delay` ms of
 * no changes. Used to throttle search API calls while the user is typing.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/**
 * Subscribes to a `(max-width: Npx)` media query and re-renders on change.
 * The single primitive behind every responsive layout decision that needs to
 * live in JS (drawer vs fixed sidebar, grid column count, chart tick density),
 * so breakpoints stay defined once in theme.ts rather than scattered as string
 * literals per component.
 */
export function useMediaQuery(maxWidthPx: number): boolean {
  const query = `(max-width: ${maxWidthPx}px)`;
  const [matches, setMatches] = useState(
    () => (typeof window !== 'undefined' ? window.matchMedia(query).matches : false),
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    setMatches(mq.matches); // sync in case the breakpoint changed between renders
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [query]);
  return matches;
}

// Sidebar collapses to an icon rail at/below tablet.
export const useIsTablet = (): boolean => useMediaQuery(breakpoint.tablet);
// Off-canvas drawer + stacked grids at/below this width.
export const useIsMobile = (): boolean => useMediaQuery(breakpoint.mobile);
// Small handset: single column, largest touch targets, most aggressive tick thinning.
export const useIsPhone = (): boolean => useMediaQuery(breakpoint.phone);

/**
 * Observes an element's content-box width via ResizeObserver, returned as a
 * `[ref, width]` pair. Charts read their OWN rendered width from this (never the
 * window), because tick density has to adapt to the real container: a chart in a
 * 3-column desktop grid is only ~400px wide and needs the same tick thinning as
 * a phone. Works for off-screen carousel slides too — a translated slide still
 * has its laid-out width, so the observer reports a real (non-zero) number.
 */
export function useElementWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (typeof w === 'number') setWidth(w);
    });
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width); // sync initial measure
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/**
 * True when the user has asked for reduced motion. The chart carousel reads this
 * to drop its slide transition (WCAG 2.3.3) — navigation still works, it just
 * jumps rather than slides.
 */
export function usePrefersReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)';
  const [reduced, setReduced] = useState(
    () => (typeof window !== 'undefined' ? window.matchMedia(query).matches : false),
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    setReduced(mq.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);
  return reduced;
}

/**
 * Calls `handler` on a mousedown outside `ref`. Used to dismiss popovers
 * (e.g. PeerPicker) on an outside click. `active` lets callers only attach the
 * listener while the popover is open. The ref must wrap BOTH the trigger and
 * the panel so clicking the trigger doesn't count as "outside" (which would
 * fight the trigger's own toggle).
 */
export function useOnClickOutside(
  ref: RefObject<HTMLElement | null>,
  handler: () => void,
  active = true,
): void {
  useEffect(() => {
    if (!active) return;
    const listener = (e: MouseEvent) => {
      const el = ref.current;
      if (!el || el.contains(e.target as Node)) return;
      handler();
    };
    document.addEventListener('mousedown', listener);
    return () => document.removeEventListener('mousedown', listener);
  }, [ref, handler, active]);
}

// ---------------------------------------------------------------------------
// Minimal client-side router. Every screen is now URL-addressable so a hard
// refresh / deep link lands on the right view:
//   - top-level screens: "/" (dashboard), /documents, /chat, /analysis, /help,
//     /settings  → { name: 'view', view }
//   - ticker-bearing:    /company/:t, /compare/:a/:p (shareable, deep-linkable)
// App.tsx DERIVES its current view from this route (no separate useState), so
// the URL is the single source of truth and the two can't drift.
//
// No history library: pushState + a popstate listener cover back/forward and
// shareable URLs. Both server.js (production, behind Cloud Run) and Vite's dev
// server fall back to index.html for unknown paths, so a hard refresh on
// /analysis or /compare/AAPL/DELL loads the SPA shell and this hook parses the
// URL from there. Anything that matches no pattern is `notfound`, so a mistyped
// or stale link renders a real 404 page instead of silently showing a screen.
// ---------------------------------------------------------------------------

// Top-level screen ↔ path. "/" is the canonical dashboard path; "/dashboard" is
// accepted as an alias (both parse to the dashboard view).
const VIEW_TO_PATH: Record<ViewState, string> = {
  dashboard: '/',
  documents: '/documents',
  chat:      '/chat',
  analysis:  '/analysis',
  help:      '/help',
  settings:  '/settings',
};
const PATH_TO_VIEW: Record<string, ViewState> = {
  '/':          'dashboard',
  '/dashboard': 'dashboard',
  '/documents': 'documents',
  '/chat':      'chat',
  '/analysis':  'analysis',
  '/help':      'help',
  '/settings':  'settings',
};

// The URL for a top-level screen, used by App's nav so the two directions
// (click → URL, URL → view) share one mapping and never disagree.
export const viewPath = (view: ViewState): string => VIEW_TO_PATH[view];

export type Route =
  | { name: 'view'; view: ViewState }
  | { name: 'company'; ticker: string }
  | { name: 'compare'; anchor: string; peer: string }
  | { name: 'notfound'; path: string };

function parseRoute(pathname: string): Route {
  // Normalise a trailing slash (except the root) so "/analysis/" == "/analysis".
  const path = pathname !== '/' && pathname.endsWith('/') ? pathname.slice(0, -1) : (pathname || '/');

  const view = PATH_TO_VIEW[path];
  if (view) return { name: 'view', view };

  const company = path.match(/^\/company\/([^/]+)$/);
  if (company) return { name: 'company', ticker: decodeURIComponent(company[1]) };

  const compare = path.match(/^\/compare\/([^/]+)\/([^/]+)$/);
  if (compare) {
    return {
      name: 'compare',
      anchor: decodeURIComponent(compare[1]),
      peer: decodeURIComponent(compare[2]),
    };
  }

  return { name: 'notfound', path: pathname };
}

export function useRoute(): { route: Route; navigate: (path: string) => void } {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = (path: string) => {
    if (path === window.location.pathname) return;
    window.history.pushState(null, '', path);
    setRoute(parseRoute(path));
  };

  return { route, navigate };
}
