import { useEffect, useState } from 'react';
import {
  ApiError,
  type Reading,
  type ReadingType,
  type ReadingsSchema,
  deleteReading,
  getReadings,
  getReadingsSchema,
  postReading,
} from './api';
import { parseField, stepFor } from './validation';

const TYPE_LABELS: Record<ReadingType, string> = {
  BP: 'Blood pressure',
  TEMP: 'Body temperature',
};

/** "YYYY-MM-DDTHH:MM" in the browser's local time, for a datetime-local input. */
export function localDateTime(date: Date = new Date()): string {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

/** Default time for a new reading on `day`: now if `day` is today, else 07:00. */
export function defaultTime(day: string, now: Date = new Date()): string {
  const current = localDateTime(now);
  return current.startsWith(day) ? current : `${day}T07:00`;
}

export function describeReading(r: Reading): string {
  if (r.type === 'BP') return `${r.systolic_mmhg}/${r.diastolic_mmhg} mmHg, pulse ${r.pulse_bpm} bpm`;
  return `${r.temp_c} °C`;
}

export function ReadingsSection({ date }: { date: string }) {
  const [schema, setSchema] = useState<ReadingsSchema | null>(null);
  const [type, setType] = useState<ReadingType>('BP');
  const [measuredAt, setMeasuredAt] = useState(() => defaultTime(date));
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [readings, setReadings] = useState<Reading[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    getReadingsSchema()
      .then(setSchema)
      .catch((err: Error) => setMessage(err.message));
  }, []);

  const reload = () =>
    getReadings(date, date)
      .then((r) => setReadings(r?.items ?? []))
      .catch((err: Error) => setMessage(err.message));

  // The parent remounts this component (key={date}) when the day changes.
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!schema) return null;
  const fields = schema.types[type];

  const onSave = async () => {
    const fieldErrors: Record<string, string> = {};
    const values: Record<string, number> = {};
    for (const [name, def] of Object.entries(fields)) {
      const parsed = parseField(def, inputs[name] ?? '');
      if ('error' in parsed) fieldErrors[name] = parsed.error;
      else if (parsed.value == null) fieldErrors[name] = 'Required';
      else values[name] = parsed.value;
    }
    if (!measuredAt) fieldErrors.measured_at = 'Required';
    else if (measuredAt > localDateTime()) fieldErrors.measured_at = 'Must not be in the future';
    if (type === 'BP' && values.diastolic_mmhg >= values.systolic_mmhg) {
      fieldErrors.diastolic_mmhg = 'Must be lower than systolic';
    }
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length) return;

    try {
      await postReading({ type, measured_at: measuredAt, ...values });
      setInputs({});
      setMessage(`Saved ${TYPE_LABELS[type].toLowerCase()}`);
      reload();
    } catch (err) {
      if (err instanceof ApiError) setErrors(err.fieldErrors);
      setMessage((err as Error).message);
    }
  };

  const onDelete = async (r: Reading) => {
    try {
      await deleteReading(r.type, r.measured_at);
      reload();
    } catch (err) {
      setMessage((err as Error).message);
    }
  };

  return (
    <fieldset>
      <legend>Readings</legend>
      <div className="grid">
        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value as ReadingType)}>
            {(Object.keys(TYPE_LABELS) as ReadingType[]).map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <label className={errors.measured_at ? 'invalid' : undefined}>
          Date and time
          <input
            type="datetime-local"
            value={measuredAt}
            max={localDateTime()}
            onChange={(e) => setMeasuredAt(e.target.value)}
          />
          {errors.measured_at && <span className="error">{errors.measured_at}</span>}
        </label>
        {Object.entries(fields).map(([name, def]) => (
          <label key={name} className={errors[name] ? 'invalid' : undefined}>
            {def.label}
            {def.unit && <span className="unit"> ({def.unit})</span>}
            <input
              type="number"
              inputMode="decimal"
              min={def.minimum}
              max={def.maximum}
              step={stepFor(def)}
              value={inputs[name] ?? ''}
              onChange={(e) => setInputs({ ...inputs, [name]: e.target.value })}
            />
            {errors[name] && <span className="error">{errors[name]}</span>}
          </label>
        ))}
      </div>
      <div className="actions">
        <button type="button" onClick={onSave}>
          Add reading
        </button>
        {message && <span className="muted">{message}</span>}
      </div>
      {readings.length > 0 && (
        <ul className="readings">
          {readings.map((r) => (
            <li key={`${r.type}${r.measured_at}`}>
              <span>
                {r.local_time} · {TYPE_LABELS[r.type]}: {describeReading(r)}
              </span>
              <button type="button" className="link" onClick={() => onDelete(r)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
