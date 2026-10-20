import { describe, expect, it } from 'vitest';
import type { FieldDef } from './api';
import { changedValues, parseField, stepFor } from './validation';

const waist: FieldDef = {
  label: 'Waist',
  group: 'body',
  minimum: 50,
  maximum: 150,
  integer: false,
  unit: 'cm',
  decimals: 1,
};
const sleepScore: FieldDef = { ...waist, label: 'Sleep Score', group: 'garmin', minimum: 0, maximum: 100, integer: true, decimals: null };

describe('parseField', () => {
  it('accepts a waist measurement and rounds to one decimal', () => {
    expect(parseField(waist, '84.5')).toEqual({ value: 84.5 });
    expect(parseField(waist, '84.54')).toEqual({ value: 84.5 });
  });

  it('rejects waist values outside 50–150', () => {
    expect(parseField(waist, '49.9')).toHaveProperty('error');
    expect(parseField(waist, '150.1')).toHaveProperty('error');
  });

  it('treats empty input as cleared', () => {
    expect(parseField(waist, '  ')).toEqual({ value: null });
  });

  it('requires whole numbers for integer fields', () => {
    expect(parseField(sleepScore, '80.5')).toEqual({ error: 'Must be a whole number' });
  });
});

describe('stepFor', () => {
  it('uses 0.1 for waist', () => expect(stepFor(waist)).toBe('0.1'));
  it('uses 1 for integers', () => expect(stepFor(sleepScore)).toBe('1'));
});

describe('changedValues', () => {
  it('sends only edited fields, and null for cleared ones', () => {
    expect(changedValues({ waist_cm: 84.5, sleep_score: 80 }, { waist_cm: 84.0, sleep_score: 80, tp_ctl: null })).toEqual({
      waist_cm: 84.0,
    });
    expect(changedValues({ waist_cm: 84.5 }, { waist_cm: null })).toEqual({ waist_cm: null });
  });
});

describe('readings helpers', async () => {
  const { defaultTime, describeReading } = await import('./ReadingsSection');

  it('defaults to 07:00 on a past day', () => {
    expect(defaultTime('2026-10-01', new Date('2026-10-20T12:00:00'))).toBe('2026-10-01T07:00');
  });

  it('describes blood pressure and temperature', () => {
    const base = { measured_at: '', local_date: '', local_time: '07:00' };
    expect(describeReading({ ...base, type: 'BP', systolic_mmhg: 118, diastolic_mmhg: 76, pulse_bpm: 52 })).toBe(
      '118/76 mmHg, pulse 52 bpm',
    );
    expect(describeReading({ ...base, type: 'TEMP', temp_c: 36.8 })).toBe('36.8 °C');
  });
});
