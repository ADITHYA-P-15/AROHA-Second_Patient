import { describe, expect, it } from 'vitest';
import { candidateLabel, formatMinutes, formatPercent, resolutionLabel, signedPoints, splitCandidates } from './cover.ts';

describe('cover helpers', () => {
  it('formats minutes', () => {
    expect(formatMinutes(null)).toBe('—');
    expect(formatMinutes(0)).toBe('<1 min');
    expect(formatMinutes(12.2)).toBe('12 min');
    expect(formatMinutes(125)).toBe('2 h 5 min');
    expect(formatMinutes(120)).toBe('2 h');
  });
  it('formats percent and points', () => {
    expect(formatPercent(null)).toBe('—');
    expect(formatPercent(66.6)).toBe('67%');
    expect(signedPoints(15)).toBe('+15');
    expect(signedPoints(-10)).toBe('−10');
    expect(signedPoints(0)).toBe('0');
  });
  it('labels statuses and resolutions', () => {
    expect(candidateLabel('MISSING_CAPABILITY')).toBe('Missing capability');
    expect(candidateLabel('SOMETHING_NEW')).toBe('something new');
    expect(resolutionLabel('MATCHER')).toBe('via matcher');
    expect(resolutionLabel('MANUAL')).toBe('arranged directly');
    expect(resolutionLabel(null)).toBe('');
  });
  it('puts eligible first and collapses beyond the top three', () => {
    const list = [{ eligible: false }, { eligible: true, rank: 2 }, { eligible: true, rank: 1 }, { eligible: true, rank: 3 }, { eligible: true, rank: 4 }];
    const { shown, rest } = splitCandidates(list);
    expect(shown.map(c => c.rank)).toEqual([1, 2, 3]);
    expect(rest).toHaveLength(2);
    expect(rest[0].rank).toBe(4);
  });
});
