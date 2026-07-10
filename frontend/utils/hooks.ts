import { useState, useEffect, RefObject } from 'react';
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

export function useIsTablet(): boolean {
  const [isTablet, setIsTablet] = useState(
    () => window.matchMedia(`(max-width: ${breakpoint.tablet}px)`).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint.tablet}px)`);
    const handler = (e: MediaQueryListEvent) => setIsTablet(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);
  return isTablet;
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
