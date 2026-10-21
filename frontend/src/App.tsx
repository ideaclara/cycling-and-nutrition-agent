import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { useEffect, useState } from 'react';
import { AdviceCard } from './AdviceCard';
import { type Schema, getSchema, syncIntervals, syncStrava } from './api';
import { DailyLogForm } from './DailyLogForm';

function LoggedIn({ signOut }: { signOut?: () => void }) {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const onSync = () => {
    setSyncMessage('Syncing…');
    Promise.allSettled([syncStrava(), syncIntervals()]).then(([strava, intervals]) => {
      const parts = [
        strava.status === 'fulfilled'
          ? `Strava: ${strava.value?.queued ?? 0} new activities queued`
          : `Strava failed: ${strava.reason.message}`,
        intervals.status === 'fulfilled'
          ? `Intervals: ${intervals.value?.written ?? 0} days updated`
          : `Intervals: ${intervals.reason.message}`,
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
        <h1>Daily Fitness Log</h1>
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
      <AdviceCard />
      {error && <p className="error">Could not load the form: {error}</p>}
      {schema ? <DailyLogForm schema={schema} /> : !error && <p className="muted">Loading…</p>}
    </main>
  );
}

export default function App() {
  // Self sign-up is disabled in Cognito, so only the sign-in screen is shown.
  return (
    <Authenticator hideSignUp>{({ signOut }) => <LoggedIn signOut={signOut} />}</Authenticator>
  );
}
