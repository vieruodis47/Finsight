import React, { useState } from 'react';
import { TrendingUp, ArrowRight, FileText, MessageCircle, BarChart2, Sparkles } from 'lucide-react';
import { c, font } from '../theme';
import dashboardPreview from '../assets/dashboard-preview.png';

interface SplashScreenProps {
  onGetStarted: () => void;
}

const SplashScreen: React.FC<SplashScreenProps> = ({ onGetStarted = () => {} }) => {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        width: '100vw',
        background: c.bg,
        fontFamily: font.ui,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', maxWidth: 520, padding: '0 24px' }}>

        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
          <div
            style={{
              width: 48, height: 48, borderRadius: 12,
              background: c.brandTint,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <TrendingUp size={22} color={c.brand} />
          </div>
          <span style={{ fontSize: 28, fontWeight: 500, color: c.text, letterSpacing: '-0.3px' }}>
            Fin<span style={{ color: c.brand }}>Sight</span>
          </span>
        </div>

        {/* Headline */}
        <h1
          style={{
            fontSize: 26, fontWeight: 500, color: c.text,
            lineHeight: 1.3, margin: '0 0 12px',
          }}
        >
          AI-powered financial research,<br />grounded in real filings
        </h1>

        {/* Subline */}
        <p
          style={{
            fontSize: 15, color: c.textMuted, lineHeight: 1.7,
            margin: '0 0 36px', maxWidth: 400,
          }}
        >
          Pull any company's 10-K straight from SEC EDGAR — or upload your own —
          ask questions in plain English, and get instant analysis backed by the
          actual source text.
        </p>

        {/* CTA */}
        <button
          onClick={onGetStarted}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '12px 28px', borderRadius: 8,
            background: hovered ? c.brandDeepHover : c.brandDeep,
            color: c.onBrand, fontSize: 15, fontWeight: 500,
            border: 'none', cursor: 'pointer',
            fontFamily: font.ui,
            transition: 'background 0.15s',
            marginBottom: 40,
          }}
        >
          Get started
          <ArrowRight size={16} />
        </button>

        {/* Product preview — framed screenshot. width/height are the asset's
            intrinsic dimensions so the browser reserves space and avoids layout
            shift; the real screenshot is dropped in at assets/dashboard-preview.png. */}
        <div style={{
          width: '100%', maxWidth: 520, marginBottom: 40,
          borderRadius: 12, border: `1px solid ${c.border}`,
          overflow: 'hidden', boxShadow: '0 8px 30px rgba(16,32,43,0.12)',
        }}>
          <img
            src={dashboardPreview}
            alt="FinSight dashboard showing a company's KPI cards, margin breakdown, and live market snapshot"
            width={1200}
            height={750}
            style={{ display: 'block', width: '100%', height: 'auto' }}
          />
        </div>

        {/* Feature badges — single row on desktop, 2×2 below 640px
            (see .feature-badges in index.html). */}
        <div className="feature-badges">
          {[
            { icon: <FileText size={13} />,      label: 'SEC EDGAR filings' },
            { icon: <MessageCircle size={13} />, label: 'RAG-powered Q&A' },
            { icon: <BarChart2 size={13} />,     label: 'Peer comparison' },
            { icon: <Sparkles size={13} />,      label: 'Gemini AI' },
          ].map(({ icon, label }) => (
            <div
              key={label}
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: c.textFaint }}
            >
              <span style={{ color: c.accentFg }}>{icon}</span>
              {label}
            </div>
          ))}
        </div>

        {/* Divider line */}
        <div style={{ width: 40, height: 1, background: c.border, margin: '32px 0' }} />

        {/* Mini credibility line */}
        <p style={{ fontSize: 12, color: c.textFaint, margin: 0 }}>
          Analyze any public company's SEC filings
        </p>
      </div>
    </div>
  );
};

export default SplashScreen;