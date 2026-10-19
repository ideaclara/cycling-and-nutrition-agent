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
