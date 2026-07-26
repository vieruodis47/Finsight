import React, {
  createContext, useContext, useReducer, useRef, useCallback, useEffect,
} from 'react';
import { Document, ChatMessage } from '../types';
import { askFinSightStream } from '../services/gemini';
import { companyLabel } from '../utils/company';
import {
  resolveCompaniesInQuestion, looksLikeComparison, isCompanySpecific,
} from '../utils/questionQuality';

// ──────────────────────────────────────────────────────────────────────────
// Why this provider exists
//
// FinChat (ChatInterface) is a ROUTED component: it unmounts the moment the
// user navigates to another view, taking its useState with it — so a whole
// conversation (messages, sources, filter, in-flight stream) was destroyed by a
// trip to Documents to fetch a company. This provider lifts all CONVERSATION
// state and the streaming engine ABOVE the router. Mounted once in App (which
// never unmounts across navigation), it keeps the conversation — and any
// in-flight streaming response — alive while the user is on another route, and
// intact when they return. ChatInterface becomes a pure consumer.
//
// Streaming across navigation: we deliberately DO NOT abort an in-flight stream
// on navigation. Because the fetch/reader and its state updates live here (never
// unmounted), the response keeps accumulating off-screen and is complete when
// the user comes back. Aborting would throw away the answer they explicitly
// asked for; continuing costs nothing (the provider is always mounted, so there
// is no setState-after-unmount risk and no lost tokens).
// ──────────────────────────────────────────────────────────────────────────

// ── greeting + company helpers (moved out of ChatInterface) ────────────────

// "Name (TICKER)" when we have a proper name, plain ticker otherwise.
const companyDisplay = (doc: Document): string => {
  const ticker = doc.ticker?.toUpperCase() || doc.name;
  const name = companyLabel(doc);
  return name !== ticker ? `${name} (${ticker})` : ticker;
};

// Deduplicates documents by ticker (or name when no ticker).
export const uniqueCompanies = (docs: Document[]): Document[] => {
  const seen = new Set<string>();
  return docs.filter(doc => {
    const key = (doc.ticker || doc.name).toUpperCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

// "A", "A and B", "A, B, and C", "A, B, C, and 2 more".
const formatList = (names: string[]): string => {
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  if (names.length <= 4) return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`;
  const shown = names.slice(0, 3).join(', ');
  return `${shown}, and ${names.length - 3} more`;
};

// The context-aware greeting shown as Finch's first message.
export const buildGreeting = (docs: Document[]): string => {
  const intro = "Hi, I'm Finch — FinSight's chat assistant.";
  const companies = uniqueCompanies(docs);

  if (companies.length === 0) {
    return `${intro} You don't have any filings loaded yet. Add a company from the Documents page and I'll help you dig into its SEC filings.`;
  }
  if (companies.length === 1) {
    const display = companyDisplay(companies[0]);
    const name = companyLabel(companies[0]);
    return `${intro} I see you have ${display} loaded. Want to load another company to compare, or shall we start with a question about ${name}?`;
  }
  const list = formatList(companies.map(companyDisplay));
  return `${intro} I've got ${list} loaded. Ask me about any of them, or compare them head to head.`;
};

const tk = (d: Document): string => (d.ticker || d.name || '').toUpperCase();

// Make the resolved company explicit in the text sent to the backend, so the
// GRAPH path (which resolves the company from the question, not the ticker
// scope) also confines to it. Skips injection when the company is already named.
const withCompany = (text: string, d: Document): string => {
  const ticker = tk(d);
  const label = companyLabel(d);
  const already = new RegExp(`\\b(${ticker}|${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})\\b`, 'i').test(text);
  return already ? text : `${text} (${ticker})`;
};

// Form filter for a resolved scope (all filings are 10-K today, but keep it
// derived rather than hardcoded).
const formFor = (scope: string[], docs: Document[]): '10-K' | undefined => {
  const forms = Array.from(new Set(
    docs.filter(d => scope.includes(tk(d))).map(d => d.form).filter((f): f is '10-K' => Boolean(f)),
  ));
  return forms.length === 1 ? forms[0] : undefined;
};

// ── state + reducer ────────────────────────────────────────────────────────

const WELCOME_ID = 'welcome';

const makeWelcome = (docs: Document[]): ChatMessage => ({
  id: WELCOME_ID, role: 'assistant', text: buildGreeting(docs), timestamp: new Date(),
});

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;            // "bird" pre-generation phase (routing + retrieval)
  selectedDocIds: string[];      // company filter chips ([] = "All")
  contextCompany: string | null; // active company for follow-up carry-over
  pendingClarify: string | null; // parked question awaiting a "which company?" answer
  announcement: string;          // a11y: the last COMPLETED answer, announced once
}

type Action =
  | { type: 'ADD_MESSAGE'; message: ChatMessage }
  | { type: 'PATCH_MESSAGE'; id: string; updates: Partial<ChatMessage> }
  | { type: 'SET_LOADING'; value: boolean }
  | { type: 'SET_SELECTED'; ids: string[] }
  | { type: 'TOGGLE_DOC'; id: string }
  | { type: 'SET_CONTEXT'; company: string | null }
  | { type: 'SET_PENDING'; question: string | null }
  | { type: 'SET_ANNOUNCEMENT'; text: string }
  | { type: 'SET_WELCOME_TEXT'; text: string };

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.message] };
    case 'PATCH_MESSAGE':
      return {
        ...state,
        messages: state.messages.map(m => (m.id === action.id ? { ...m, ...action.updates } : m)),
      };
    case 'SET_LOADING':
      return state.isLoading === action.value ? state : { ...state, isLoading: action.value };
    case 'SET_SELECTED':
      return { ...state, selectedDocIds: action.ids };
    case 'TOGGLE_DOC':
      return {
        ...state,
        selectedDocIds: state.selectedDocIds.includes(action.id)
          ? state.selectedDocIds.filter(x => x !== action.id)
          : [...state.selectedDocIds, action.id],
      };
    case 'SET_CONTEXT':
      return { ...state, contextCompany: action.company };
    case 'SET_PENDING':
      return { ...state, pendingClarify: action.question };
    case 'SET_ANNOUNCEMENT':
      return { ...state, announcement: action.text };
    case 'SET_WELCOME_TEXT':
      // Keep the greeting fresh with the loaded companies UNTIL the first real
      // message; once the user has interacted (more than the welcome message) it
      // freezes. No-op when unchanged so document-poll re-renders don't churn.
      if (
        state.messages.length !== 1 ||
        state.messages[0].id !== WELCOME_ID ||
        state.messages[0].text === action.text
      ) {
        return state;
      }
      return { ...state, messages: [{ ...state.messages[0], text: action.text }] };
    default:
      return state;
  }
}

// ── context shape ──────────────────────────────────────────────────────────

interface ChatContextValue {
  messages: ChatMessage[];
  isLoading: boolean;
  selectedDocIds: string[];
  announcement: string;
  // actions
  sendMessage: (raw: string) => void;
  pickClarifyCompany: (question: string, ticker: string) => void;
  pickClarifyCompare: (question: string) => void;
  setAllFilter: () => void;
  toggleDoc: (id: string) => void;
  // scroll persistence — survives ChatInterface unmount/remount so the
  // "stay at bottom vs. keep the user's scrolled-up position" decision is not
  // reset by navigation.
  stickToBottomRef: React.RefObject<boolean>;
  lastScrollTopRef: React.RefObject<number>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export const useChat = (): ChatContextValue => {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChat must be used within a ChatProvider');
  return ctx;
};

// ── provider ───────────────────────────────────────────────────────────────

export const ChatProvider: React.FC<{ documents: Document[]; children: React.ReactNode }> = ({
  documents, children,
}) => {
  const [state, dispatch] = useReducer(
    reducer,
    documents,
    (docs): ChatState => ({
      messages: [makeWelcome(docs)],
      isLoading: false,
      selectedDocIds: [],
      contextCompany: null,
      pendingClarify: null,
      announcement: '',
    }),
  );

  // Always-fresh mirrors so the (stable) action callbacks below read current
  // state/documents without stale closures or dependency churn.
  const stateRef = useRef(state);
  stateRef.current = state;
  const documentsRef = useRef(documents);
  documentsRef.current = documents;

  // Scroll bookkeeping, persisted across navigation (see ChatContextValue).
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);

  // Refresh the welcome greeting as companies load/change, until first message.
  useEffect(() => {
    dispatch({ type: 'SET_WELCOME_TEXT', text: buildGreeting(documents) });
  }, [documents]);

  // The companies in play for the clarify gate: the explicitly-selected subset
  // if the user picked one/some ("All" = empty selection), else every loaded doc.
  const gateCompanies = useCallback((): Document[] => {
    const docs = documentsRef.current;
    const selected = docs.filter(d => stateRef.current.selectedDocIds.includes(d.id));
    return uniqueCompanies(selected.length > 0 ? selected : docs);
  }, []);

  // The actual retrieval + streaming call. `displayText` is the user's bubble;
  // `sentText` is what the backend sees (company-injected); `scope` is the ticker
  // filter; `newContext` becomes the active company for follow-ups.
  const runQuery = useCallback(async (
    displayText: string, sentText: string, scope: string[], newContext: string | null,
  ) => {
    if (stateRef.current.isLoading) return;
    dispatch({ type: 'SET_PENDING', question: null });
    dispatch({ type: 'SET_CONTEXT', company: newContext });
    dispatch({ type: 'ADD_MESSAGE', message: {
      id: Date.now().toString(), role: 'user', text: displayText, timestamp: new Date(),
    } });
    // The user just sent a message — pin to bottom so the answer streams in view.
    stickToBottomRef.current = true;
    dispatch({ type: 'SET_LOADING', value: true });

    const assistantId = `a-${Date.now()}`;
    let started = false;
    let acc = '';

    const ensureStarted = () => {
      if (started) return;
      started = true;
      dispatch({ type: 'SET_LOADING', value: false });
      dispatch({ type: 'ADD_MESSAGE', message: {
        id: assistantId, role: 'assistant', text: '', streaming: true, timestamp: new Date(),
      } });
    };
    const patch = (updates: Partial<ChatMessage>) =>
      dispatch({ type: 'PATCH_MESSAGE', id: assistantId, updates });

    await askFinSightStream(
      sentText,
      { tickers: scope.length ? scope : undefined, form: formFor(scope, documentsRef.current), k: 6 },
      {
        onToken: (delta) => { ensureStarted(); acc += delta; patch({ text: acc }); },
        onDone: ({ sources, validCitations, retrievalPath, chart }) => {
          ensureStarted();
          // `chart` (if present) resolves only at completion, so it appears after
          // the text, in the streaming flow — never mid-stream.
          patch({ text: acc, sources, validCitations, retrievalPath, chart, streaming: false });
          dispatch({ type: 'SET_ANNOUNCEMENT', text: acc });
        },
        onError: (message) => {
          if (!started) {
            started = true;
            dispatch({ type: 'SET_LOADING', value: false });
            dispatch({ type: 'ADD_MESSAGE', message: {
              id: assistantId, role: 'assistant', text: acc || `Error: ${message}`,
              streaming: false, error: true, timestamp: new Date(),
            } });
          } else {
            patch({ text: acc, streaming: false, error: true });
          }
        },
      },
    );
    if (!started) dispatch({ type: 'SET_LOADING', value: false });
  }, []);

  // Resume a pending/typed question scoped to ONE resolved company.
  const resolveToCompany = useCallback((question: string, d: Document) =>
    runQuery(withCompany(question, d), withCompany(question, d), [tk(d)], tk(d)), [runQuery]);

  // Resume a pending/typed question as a head-to-head across companies.
  const resolveToCompare = useCallback((question: string, docs: Document[]) => {
    const tickers = docs.map(tk);
    const already = /\b(compare|versus|vs\.?|both|between)\b/i.test(question);
    const sent = already ? question : `${question} — compare ${tickers.join(' and ')}`;
    runQuery(sent, sent, tickers, null);
  }, [runQuery]);

  // Ask which company, offering the loaded options as quick-pick chips. No
  // retrieval or Gemini call happens here — the question is parked until answered.
  const askClarify = useCallback((question: string, companies: Document[]) => {
    dispatch({ type: 'SET_PENDING', question });
    const tickers = companies.map(tk);
    const compareHint = tickers.length === 2 ? 'Or want both compared?' : 'Or compare them?';
    dispatch({ type: 'ADD_MESSAGE', message: {
      id: `clarify-${Date.now()}`,
      role: 'assistant',
      text: `Which company do you mean — ${tickers.join(', ')}? ${compareHint}`,
      timestamp: new Date(),
      clarify: { question, companies: companies.map(d => ({ ticker: tk(d), label: companyLabel(d) })) },
    } });
  }, []);

  // ── Pre-retrieval clarify gate ──────────────────────────────────────────
  // Deterministically decide whether the query is answerable as-is or needs a
  // "which company?" question, BEFORE any retrieval/generation.
  const sendMessage = useCallback((raw: string) => {
    const text = raw.trim();
    const st = stateRef.current;
    if (!text || st.isLoading) return;
    const companies = gateCompanies();

    // If we're awaiting a clarification, interpret this reply as its answer and
    // resume the ORIGINAL question — don't make the user retype it.
    if (st.pendingClarify) {
      const picked = resolveCompaniesInQuestion(text, companies);
      const wantsAll = looksLikeComparison(text) || /\b(both|all|either|every)\b/i.test(text);
      if (picked.length >= 1 || wantsAll) {
        const q = st.pendingClarify;
        dispatch({ type: 'SET_PENDING', question: null });
        if (picked.length === 1 && !wantsAll) return resolveToCompany(q, picked[0]);
        return resolveToCompare(q, picked.length >= 2 ? picked : companies);
      }
      // Not an answer to the clarify — fall through and treat as a new question.
      dispatch({ type: 'SET_PENDING', question: null });
    }

    const matches = resolveCompaniesInQuestion(text, companies);
    if (matches.length >= 2) return resolveToCompare(text, matches);   // named several → compare
    if (matches.length === 1) {                                        // named one → proceed
      const d = matches[0];
      return runQuery(text, text, [tk(d)], tk(d));
    }

    // No company named:
    if (looksLikeComparison(text)) return runQuery(text, text, companies.map(tk), null); // corpus-wide compare
    if (st.contextCompany && isCompanySpecific(text)) {                                   // follow-up carry-over
      const d = companies.find(x => tk(x) === st.contextCompany);
      if (d) return runQuery(text, withCompany(text, d), [st.contextCompany], st.contextCompany);
    }
    if (companies.length <= 1) {                                                          // 0/1 loaded → assume
      const d = companies[0];
      return runQuery(text, d ? withCompany(text, d) : text, d ? [tk(d)] : [], d ? tk(d) : null);
    }
    if (isCompanySpecific(text)) return askClarify(text, companies);                      // ambiguous → ASK

    return runQuery(text, text, companies.map(tk), null);                                 // non-specific → proceed
  }, [gateCompanies, runQuery, resolveToCompany, resolveToCompare, askClarify]);

  // Resolve a clarify via a tapped chip: resume the parked question.
  const pickClarifyCompany = useCallback((question: string, ticker: string) => {
    const d = gateCompanies().find(x => tk(x) === ticker.toUpperCase());
    if (d) resolveToCompany(question, d);
  }, [gateCompanies, resolveToCompany]);

  const pickClarifyCompare = useCallback((question: string) =>
    resolveToCompare(question, gateCompanies()), [gateCompanies, resolveToCompare]);

  const setAllFilter = useCallback(() => dispatch({ type: 'SET_SELECTED', ids: [] }), []);
  const toggleDoc = useCallback((id: string) => dispatch({ type: 'TOGGLE_DOC', id }), []);

  const value: ChatContextValue = {
    messages: state.messages,
    isLoading: state.isLoading,
    selectedDocIds: state.selectedDocIds,
    announcement: state.announcement,
    sendMessage,
    pickClarifyCompany,
    pickClarifyCompare,
    setAllFilter,
    toggleDoc,
    stickToBottomRef,
    lastScrollTopRef,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
};
