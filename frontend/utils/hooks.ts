import { useState, useEffect } from 'react';
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
