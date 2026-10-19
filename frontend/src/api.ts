import { fetchAuthSession } from 'aws-amplify/auth';

const BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

/** Mirrors `Field` in services/common/daily_log_schema.py (served by GET /daily-log/schema). */
export interface FieldDef {
  label: string;
  group: 'garmin' | 'xert' | 'trainingpeaks' | 'body';
  minimum: number;
  maximum: number;
  integer: boolean;
  unit: string;
  decimals: number | null;
}

export interface Schema {
  fields: Record<string, FieldDef>;
  dqs_categories: { high_quality: string[]; low_quality: string[] };
}

export type DailyLog = Record<string, unknown> & {
  date?: string;
  dqs_servings?: Record<string, number>;
  dqs_total?: number;
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly fieldErrors: Record<string, string> = {},
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T | null> {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init.headers },
  });
  if (res.status === 404) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body.message ?? res.statusText, body.errors);
  return body as T;
}

export const getSchema = () => request<Schema>('/daily-log/schema');
export const getDay = (date: string) => request<DailyLog>(`/daily-log/${date}`);
export const putDay = (date: string, changes: Record<string, unknown>) =>
  request<DailyLog>(`/daily-log/${date}`, { method: 'PUT', body: JSON.stringify(changes) });
export const syncStrava = () => request<{ message: string; queued: number }>('/strava/sync', { method: 'POST' });
