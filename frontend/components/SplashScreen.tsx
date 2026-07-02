import React, { useState } from 'react';
import { TrendingUp, ArrowRight, FileText, MessageCircle, BarChart2, Sparkles } from 'lucide-react';
import { c, font } from '../theme';

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
          Upload 10-K and 10-Q documents, ask questions in plain English,
          and get instant analysis backed by the actual source text.
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

        {/* Feature pills */}
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', justifyContent: 'center' }}>
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