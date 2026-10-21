import { useEffect, useRef, useState } from 'react';
import { type ChatBackend, type ChatMessage, getChat, sendChat } from './api';
import { Markdown } from './markdown';

const BACKENDS: { id: ChatBackend; label: string }[] = [
  { id: 'agent', label: 'Bedrock Agent' },
  { id: 'agentcore', label: 'AgentCore' },
];
const SESSION_KEY = 'coach-chat-session';

function storedSession(): string {
  try {
    return localStorage.getItem(SESSION_KEY) ?? crypto.randomUUID();
  } catch {
    return crypto.randomUUID();
  }
}

function remember(sessionId: string) {
  try {
    localStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    // private mode: the session just won't survive a reload
  }
}

function Reply({ message }: { message: ChatMessage }) {
  return (
    <div className="msg assistant">
      <Markdown text={message.text || '_(no answer)_'} />
      <div className="msg-meta muted small">
        {BACKENDS.find((b) => b.id === message.backend)?.label}
        {message.latency_ms != null && <> · {(message.latency_ms / 1000).toFixed(1)} s</>}
        {message.steps && message.steps.length > 0 && <> · used {message.steps.join(', ')}</>}
        {message.guardrail && <span className="error"> · guardrail {message.guardrail}</span>}
      </div>
      {message.citations && message.citations.length > 0 && (
        <details className="small">
          <summary>{message.citations.length} sources</summary>
          <ul>
            {message.citations.map((c, i) => (
              <li key={i}>
                <strong>{c.title ?? c.source}</strong>: {c.excerpt}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function Chat() {
  const [sessionId, setSessionId] = useState(storedSession);
  const [backend, setBackend] = useState<ChatBackend>('agent');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    remember(sessionId);
    getChat(sessionId)
      .then((r) => setMessages(r?.items ?? []))
      .catch(() => setMessages([]));
  }, [sessionId]);

  useEffect(() => end.current?.scrollIntoView({ behavior: 'smooth' }), [messages, busy]);

  const onSend = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    setError(null);
    setBusy(true);
    setMessages((m) => [...m, { role: 'user', text, at: new Date().toISOString(), backend }]);
    try {
      const reply = await sendChat(text, sessionId, backend);
      if (reply) setMessages((m) => [...m, reply]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="chat">
      <div className="chat-bar">
        <div className="segmented" role="radiogroup" aria-label="Backend">
          {BACKENDS.map((b) => (
            <button
              key={b.id}
              type="button"
              role="radio"
              aria-checked={backend === b.id}
              className={backend === b.id ? 'active' : undefined}
              onClick={() => setBackend(b.id)}
            >
              {b.label}
            </button>
          ))}
        </div>
        <button type="button" className="link" onClick={() => setSessionId(crypto.randomUUID())}>
          New session
        </button>
      </div>
      <div className="messages">
        {messages.length === 0 && (
          <p className="muted">Ask about today's training, fuelling, recovery or your eating habits.</p>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="msg user">
              {m.text}
            </div>
          ) : (
            <Reply key={i} message={m} />
          ),
        )}
        {busy && <p className="muted">Thinking…</p>}
        {error && <p className="error">{error}</p>}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={onSend}>
        <textarea
          value={draft}
          rows={2}
          maxLength={4000}
          placeholder="Message the coach"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) onSend(e);
          }}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
