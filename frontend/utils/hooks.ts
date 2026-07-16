import { useState, useEffect, useRef, RefObject } from 'react';
import { breakpoint } from '../theme';

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
// Minimal client-side router — two URL shapes only, everything else falls
// through to the existing useState-driven view switching in App.tsx.
// No history library: pushState + a popstate listener cover back/forward and
// shareable URLs for exactly the two routes this app needs. Both server.js
// (production, behind Cloud Run) and Vite's dev server already fall back to
// index.html for unknown paths, so a hard refresh on /compare/AAPL/DELL loads
// the SPA shell and this hook parses the URL client-side from there.
// ---------------------------------------------------------------------------

export type Route =
  | { name: 'company'; ticker: string }
  | { name: 'compare'; anchor: string; peer: string }
  | { name: 'other' };

function parseRoute(pathname: string): Route {
  const company = pathname.match(/^\/company\/([^/]+)\/?$/);
  if (company) return { name: 'company', ticker: decodeURIComponent(company[1]) };

  const compare = pathname.match(/^\/compare\/([^/]+)\/([^/]+)\/?$/);
  if (compare) {
    return {
      name: 'compare',
      anchor: decodeURIComponent(compare[1]),
      peer: decodeURIComponent(compare[2]),
    };
  }

  return { name: 'other' };
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
