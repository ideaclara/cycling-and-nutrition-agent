import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { useEffect, useState } from 'react';

const TABS = [
  { id: 'log', label: 'Log' },
  { id: 'coach', label: 'Coach' },
  { id: 'analysis', label: 'Analysis' },
] as const;
type Tab = (typeof TABS)[number]['id'];

function tabFromHash(): Tab {
  const id = window.location.hash.replace('#/', '');
  return TABS.some((t) => t.id === id) ? (id as Tab) : 'log';
}
import { AdviceCard } from './AdviceCard';
import { AnalysisPage } from './AnalysisPage';
import { Chat } from './Chat';
import { type Schema, getSchema, syncFatSecret, syncIntervals, syncStrava } from './api';
import { DailyLogForm } from './DailyLogForm';

function LoggedIn({ signOut }: { signOut?: () => void }) {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(tabFromHash);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const onSync = () => {
    setSyncMessage('Syncing…');
    Promise.allSettled([syncStrava(), syncIntervals(), syncFatSecret()]).then(([strava, intervals, fatsecret]) => {
      const parts = [
        strava.status === 'fulfilled'
          ? `Strava: ${strava.value?.queued ?? 0} new activities queued`
          : `Strava failed: ${strava.reason.message}`,
        intervals.status === 'fulfilled'
          ? `Intervals: ${intervals.value?.written ?? 0} days updated`
          : `Intervals: ${intervals.reason.message}`,
        fatsecret.status === 'fulfilled'
          ? `FatSecret: ${fatsecret.value?.written ?? 0} days updated`
          : `FatSecret: ${fatsecret.reason.message}`,
      ];
      setSyncMessage(parts.join(' · '));
    });
  };

  useEffect(() => {
    getSchema()
      .then(setSchema)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <main>
      <header>
        <h1>Cycling Coach</h1>
        <div className="header-actions">
          {syncMessage && <span className="muted">{syncMessage}</span>}
          <button type="button" className="link" onClick={onSync}>
            Sync
          </button>
          <button type="button" className="link" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <nav className="tabs">
        {TABS.map((t) => (
          <a key={t.id} href={`#/${t.id}`} className={tab === t.id ? 'active' : undefined}>
            {t.label}
          </a>
        ))}
      </nav>
      {tab === 'log' && (
        <>
          <AdviceCard />
          {error && <p className="error">Could not load the form: {error}</p>}
          {schema ? <DailyLogForm schema={schema} /> : !error && <p className="muted">Loading…</p>}
        </>
      )}
      {tab === 'coach' && <Chat />}
      {tab === 'analysis' && <AnalysisPage />}
    </main>
  );
}

export default function App() {
  // Self sign-up is disabled in Cognito, so only the sign-in screen is shown.
  return <Authenticator hideSignUp>{({ signOut }) => <LoggedIn signOut={signOut} />}</Authenticator>;
}
