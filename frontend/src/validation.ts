import type { FieldDef } from './api';

/**
 * Parse one numeric input the same way the API validates it.
 * Returns `{ value }` (null = cleared) or `{ error }`.
 */
export function parseField(def: FieldDef, raw: string): { value: number | null } | { error: string } {
  const text = raw.trim();
  if (text === '') return { value: null };
  const value = Number(text);
  if (!Number.isFinite(value)) return { error: 'Must be a number' };
  if (def.integer && !Number.isInteger(value)) return { error: 'Must be a whole number' };
  if (value < def.minimum || value > def.maximum) return { error: `Must be between ${def.minimum} and ${def.maximum}` };
  return { value: def.decimals != null ? Number(value.toFixed(def.decimals)) : value };
}

export function stepFor(def: FieldDef): string {
  if (def.integer) return '1';
  if (def.decimals != null) return (1 / 10 ** def.decimals).toString();
  return 'any';
}

/** Fields whose value differs from what was loaded: only these are sent in the PUT. */
export function changedValues(
  original: Record<string, unknown>,
  current: Record<string, number | null>,
): Record<string, number | null> {
  const changes: Record<string, number | null> = {};
  for (const [name, value] of Object.entries(current)) {
    const before = original[name] ?? null;
    if (before !== value) changes[name] = value;
  }
  return changes;
}
