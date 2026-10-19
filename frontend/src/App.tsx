import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { useEffect, useState } from 'react';
import { type Schema, getSchema, syncStrava } from './api';
import { DailyLogForm } from './DailyLogForm';

function LoggedIn({ signOut }: { signOut?: () => void }) {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const onSync = () => {
    setSyncMessage('Syncing…');
    syncStrava()
      .then((r) => setSyncMessage(`Strava: ${r?.queued ?? 0} new activities queued`))
      .catch((err: Error) => setSyncMessage(`Strava sync failed: ${err.message}`));
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
            Sync Strava
          </button>
          <button type="button" className="link" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
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
