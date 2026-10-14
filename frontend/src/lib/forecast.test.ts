import { describe, expect, it } from 'vitest';
import { formatLeadHours, formatSecureBy, inHorizon, kindLabel, leadRules, levelLabel, standByNotice, tabLabel, trimNote } from './forecast.ts';

describe('forecast helpers', () => {
  it('labels kinds and levels', () => {
    expect(kindLabel('SINGLE_POINT')).toBe('Single point of failure');
    expect(kindLabel('UNCONFIRMED')).toBe('Not confirmed');
    expect(levelLabel('INSUFFICIENT')).toBe('Not enough capacity');
    expect(levelLabel('OK')).toBe('Enough capacity');
  });
  it('filters by horizon', () => {
    const asOf = '2026-10-14T16:00:00+00:00';
    expect(inHorizon('2026-10-15T07:00:00+00:00', asOf, '24h')).toBe(true);
    expect(inHorizon('2026-10-17T07:30:00+00:00', asOf, '24h')).toBe(false);
    expect(inHorizon('2026-10-17T07:30:00+00:00', asOf, '3d')).toBe(true);
    expect(inHorizon('2026-10-18T07:30:00+00:00', asOf, '3d')).toBe(false);
    expect(inHorizon('2026-10-17T07:30:00+00:00', asOf, '7d')).toBe(true);
    expect(inHorizon('bad', asOf, '7d')).toBe(false);
  });
  it('formats secure-by in Asia/Kolkata', () => {
    expect(formatSecureBy('2026-10-16T07:30:00+00:00')).toBe('Fri 16 Oct, 13:00');
    expect(formatSecureBy('nope')).toBe('');
  });
  it('formats lead hours', () => {
    expect(formatLeadHours(null)).toBe('—');
    expect(formatLeadHours(16)).toBe('16 h');
    expect(formatLeadHours(39.6)).toBe('40 h');
    expect(formatLeadHours(52)).toBe('2 d 4 h');
    expect(formatLeadHours(72)).toBe('3 d');
  });
  it('lists lead rules longest first', () => {
    expect(leadRules({ LOW: 12, CRITICAL: 72 })).toEqual(['Critical tasks: secure 72 h ahead', 'Low-importance tasks: secure 12 h ahead']);
  });
  it('labels tabs without claiming safety', () => {
    expect(tabLabel('Next 24 hours', { gaps: 0, unconfirmed: 0, single_points: 0 })).toBe('Next 24 hours · nothing to secure');
    expect(tabLabel('Next 3 days', { gaps: 1, unconfirmed: 0, single_points: 2 })).toBe('Next 3 days · 3 to secure');
  });
  it('builds notices and trims notes', () => {
    expect(standByNotice('Savitha')).toContain('Savitha has been asked to stand by.');
    expect(trimNote('a'.repeat(400))).toHaveLength(300);
    expect(trimNote('short')).toBe('short');
  });
});
