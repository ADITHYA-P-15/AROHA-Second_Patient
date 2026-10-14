import { describe, expect, it } from 'vitest';
import { barPercent, delegationLabel, shortDay, statusLabel } from './workload';

describe('workload helpers', () => {
  it('caps the visual bar but not below zero', () => { expect(barPercent(133)).toBe(100); expect(barPercent(-4)).toBe(0); expect(barPercent(33.4)).toBe(33); });
  it('uses calm operational labels', () => { expect(statusLabel('NEEDS_REVIEW')).toBe('Needs review'); expect(delegationLabel('PROFESSIONAL')).toBe('Healthcare professional only'); });
  it('formats a date-only string without timezone drift', () => expect(shortDay('2026-10-15')).toMatch(/Thu.*15|15.*Thu/));
});
