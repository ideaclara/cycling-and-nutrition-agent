import { useEffect, useMemo, useState } from 'react';
import { ApiError, type DailyLog, type FieldDef, type Schema, getDay, putDay } from './api';
import { ReadingsSection } from './ReadingsSection';
import { changedValues, parseField, stepFor } from './validation';

const GROUPS: { id: FieldDef['group']; title: string }[] = [
  { id: 'garmin', title: 'Garmin' },
  { id: 'xert', title: 'Xert' },
  { id: 'body', title: 'Body' },
  { id: 'nutrition', title: 'Nutrition (daily totals)' },
];

const label = (category: string) => category.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

export function localToday(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

type Status =
  { kind: 'idle' } | { kind: 'loading' } | { kind: 'saved'; at: string } | { kind: 'error'; message: string };

export function DailyLogForm({ schema }: { schema: Schema }) {
  const [date, setDate] = useState(localToday);
  const [loaded, setLoaded] = useState<DailyLog>({});
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [servings, setServings] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<Status>({ kind: 'loading' });

  const dqsCategories = useMemo(
    () => [...schema.dqs_categories.high_quality, ...schema.dqs_categories.low_quality],
    [schema],
  );

  const applyLoaded = (item: DailyLog) => {
    setLoaded(item);
    setInputs(Object.fromEntries(Object.keys(schema.fields).map((n) => [n, item[n] == null ? '' : String(item[n])])));
    setServings(Object.fromEntries(dqsCategories.map((c) => [c, String(item.dqs_servings?.[c] ?? '')])));
    setErrors({});
  };

  useEffect(() => {
    let cancelled = false;
    getDay(date)
      .then((item) => {
        if (cancelled) return;
        applyLoaded(item ?? {});
        setStatus({ kind: 'idle' });
      })
      .catch((err: Error) => !cancelled && setStatus({ kind: 'error', message: err.message }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const values: Record<string, number | null> = {};
    const fieldErrors: Record<string, string> = {};
    for (const [name, def] of Object.entries(schema.fields)) {
      const parsed = parseField(def, inputs[name] ?? '');
      if ('error' in parsed) fieldErrors[name] = parsed.error;
      else values[name] = parsed.value;
    }
    const dqs: Record<string, number> = {};
    for (const category of dqsCategories) {
      const n = Number(servings[category] || 0);
      if (!Number.isFinite(n) || n < 0 || n > 20) fieldErrors[`dqs_${category}`] = 'Servings must be 0–20';
      else if (n > 0) dqs[category] = n;
    }
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length) return;

    const changes: Record<string, unknown> = changedValues(loaded, values);
    if (JSON.stringify(dqs) !== JSON.stringify(loaded.dqs_servings ?? {})) changes.dqs_servings = dqs;
    if (!Object.keys(changes).length) {
      setStatus({ kind: 'saved', at: 'no changes' });
      return;
    }

    setStatus({ kind: 'loading' });
    try {
      const saved = await putDay(date, changes);
      applyLoaded(saved ?? {});
      setStatus({ kind: 'saved', at: new Date().toLocaleTimeString() });
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors);
      setStatus({ kind: 'error', message: (err as Error).message });
    }
  };

  const prefill = loaded.intervals ?? {};

  return (
    <>
      <form onSubmit={onSubmit} noValidate>
        <div className="date-row">
          <label>
            Date
            <input
              type="date"
              value={date}
              max={localToday()}
              onChange={(e) => {
                setStatus({ kind: 'loading' });
                setDate(e.target.value);
              }}
              required
            />
          </label>
          {status.kind === 'loading' && <span className="muted">Loading…</span>}
        </div>

        {GROUPS.map((group) => (
          <fieldset key={group.id}>
            <legend>{group.title}</legend>
            <div className="grid">
              {Object.entries(schema.fields)
                .filter(([, def]) => def.group === group.id)
                .map(([name, def]) => (
                  <label key={name} className={errors[name] ? 'invalid' : undefined}>
                    {def.label}
                    {def.unit && <span className="unit"> ({def.unit})</span>}
                    <input
                      type="number"
                      inputMode="decimal"
                      name={name}
                      placeholder={prefill[name] != null ? String(prefill[name]) : undefined}
                      min={def.minimum}
                      max={def.maximum}
                      step={stepFor(def)}
                      value={inputs[name] ?? ''}
                      onChange={(e) => setInputs({ ...inputs, [name]: e.target.value })}
                    />
                    {prefill[name] != null && (inputs[name] ?? '') === '' && (
                      <span className="hint">From Intervals.icu</span>
                    )}
                    {errors[name] && <span className="error">{errors[name]}</span>}
                  </label>
                ))}
            </div>
          </fieldset>
        ))}

        <fieldset>
          <legend>
            Diet Quality Score — servings
            {loaded.dqs_total != null && <span className="dqs-total">DQS {loaded.dqs_total}</span>}
          </legend>
          {(['high_quality', 'low_quality'] as const).map((quality) => (
            <div key={quality}>
              <h3>{quality === 'high_quality' ? 'High quality' : 'Low quality'}</h3>
              <div className="grid">
                {schema.dqs_categories[quality].map((category) => (
                  <label key={category} className={errors[`dqs_${category}`] ? 'invalid' : undefined}>
                    {label(category)}
                    <input
                      type="number"
                      inputMode="decimal"
                      min={0}
                      max={20}
                      step={0.5}
                      value={servings[category] ?? ''}
                      onChange={(e) => setServings({ ...servings, [category]: e.target.value })}
                    />
                    {errors[`dqs_${category}`] && <span className="error">{errors[`dqs_${category}`]}</span>}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </fieldset>

        <div className="actions">
          <button type="submit" disabled={status.kind === 'loading'}>
            Save
          </button>
          {status.kind === 'saved' && <span className="ok">Saved ({status.at})</span>}
          {status.kind === 'error' && <span className="error">{status.message}</span>}
        </div>
      </form>
      <ReadingsSection key={date} date={date} />
    </>
  );
}
