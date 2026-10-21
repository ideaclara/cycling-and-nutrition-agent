import { useEffect, useState } from 'react';
import { type Advice, getLatestAdvice, refreshAdvice } from './api';
import { Markdown } from './markdown';

const STATUS_LABEL: Record<Advice['status'], string> = {
  green: 'Good to train',
  amber: 'Take it easier',
  red: 'Rest day',
  unknown: 'Not enough data',
};

export function AdviceCard() {
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [state, setState] = useState<'loading' | 'idle' | 'refreshing'>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLatestAdvice()
      .then(setAdvice)
      .catch((err: Error) => setError(err.message))
      .finally(() => setState('idle'));
  }, []);

  const onRefresh = () => {
    setState('refreshing');
    setError(null);
    refreshAdvice()
      .then(setAdvice)
      .catch((err: Error) => setError(err.message))
      .finally(() => setState('idle'));
  };

  return (
    <section className={`advice advice-${advice?.status ?? 'unknown'}`}>
      <div className="advice-head">
        <h2>
          Today's advice
          {advice && <span className="badge">{STATUS_LABEL[advice.status]}</span>}
        </h2>
        <button type="button" className="link" onClick={onRefresh} disabled={state !== 'idle'}>
          {state === 'refreshing' ? 'Thinking…' : 'Refresh'}
        </button>
      </div>
      {state === 'loading' && <p className="muted">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {advice && (
        <>
          <Markdown text={advice.text} />
          <p className="muted small">
            For {advice.date} · generated {new Date(advice.generated_at).toLocaleTimeString()}
            {advice.facts.missing.length > 0 && <> · missing: {advice.facts.missing.join(', ')}</>}
            {advice.facts.flags.length > 0 && <> · flags: {advice.facts.flags.join(', ').replace(/_/g, ' ')}</>}
            {advice.guardrail_intervened && <> · held back by the guardrail</>}
          </p>
        </>
      )}
      {!advice && state === 'idle' && !error && (
        <p className="muted">No advice yet. Press Refresh to generate today's.</p>
      )}
    </section>
  );
}
