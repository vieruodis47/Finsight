import React from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { c, font } from '../theme';

interface ErrorBoundaryProps {
  children: React.ReactNode;
  // Human label for the area being guarded, used in the fallback copy.
  label?: string;
  // When this value changes, the boundary clears its error and re-renders its
  // children. Pass the current view/route so navigating away from a broken page
  // automatically recovers instead of stranding the user on the fallback.
  resetKey?: unknown;
  // Optional extra recovery action wired to the Retry button (e.g. a refetch).
  onRetry?: () => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

// Catches render/lifecycle exceptions in its subtree so ONE bad component can't
// white-screen the whole app. Without this, a thrown TypeError in a chart (e.g.
// a forecast metric missing a numeric field) unmounts the entire React tree and
// the page goes blank. Here it degrades to a readable, retryable card while the
// sidebar/nav stay usable.
//
// NB: React error boundaries only catch errors during render, in lifecycle
// methods, and in constructors of the components below them. They do NOT catch
// errors in event handlers, timers, or async callbacks — those paths must still
// set their own error state (which the data hooks here already do).
export default class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidUpdate(prev: ErrorBoundaryProps) {
    // Auto-recover when the guarded context changes (e.g. user switched views).
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Surface it for diagnostics instead of swallowing it silently.
    console.error(`[ErrorBoundary${this.props.label ? ` · ${this.props.label}` : ''}]`, error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState({ error: null });
    this.props.onRetry?.();
  };

  render() {
    if (!this.state.error) return this.props.children;

    const what = this.props.label ?? 'this view';
    return (
      <div
        role="alert"
        style={{
          margin: 22,
          padding: '20px 22px',
          background: c.negSurface,
          border: `0.5px solid ${c.negBorder}`,
          borderRadius: 10,
          fontFamily: font.ui,
          maxWidth: 640,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <AlertTriangle size={18} color={c.neg} style={{ flexShrink: 0 }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: c.text }}>
            Something went wrong loading {what}.
          </span>
        </div>
        <p style={{ fontSize: 13, color: c.text2, lineHeight: 1.6, margin: '0 0 14px' }}>
          The data for this view couldn’t be displayed. This is usually a
          temporary or partial response — your other filings and pages are
          unaffected. Try again, or switch to another company or view.
        </p>
        <button
          onClick={this.handleRetry}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '7px 14px', borderRadius: 7, fontSize: 13, fontWeight: 500,
            background: c.brandDeep, color: c.onBrand, border: 'none', cursor: 'pointer',
            fontFamily: font.ui,
          }}
        >
          <RotateCw size={14} /> Retry
        </button>
        {import.meta.env?.DEV && (
          <pre style={{ marginTop: 14, fontSize: 11, color: c.textMuted, whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
            {this.state.error.message}
          </pre>
        )}
      </div>
    );
  }
}
