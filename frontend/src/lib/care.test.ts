import { describe, expect, it } from 'vitest';
import { adherenceLabel, canRecordLate, dayBounds, sourceLabel, statusLabel } from './care.ts';

describe('care helpers', () => {
  it('labels statuses', () => {
    expect(statusLabel('PENDING')).toBe('Pending');
    expect(statusLabel('COMPLETED')).toBe('Done');
    expect(statusLabel('COMPLETED', true)).toBe('Done late');
    expect(statusLabel('MISSED')).toBe('Missed');
    expect(statusLabel('CANCELLED')).toBe('Cancelled');
  });
  it('labels sources', () => {
    expect(sourceLabel('PRESCRIPTION')).toBe('Prescription');
    expect(sourceLabel('APPOINTMENT')).toBe('Appointment');
    expect(sourceLabel('MANUAL')).toBe('Added by family');
  });
  it('allows late recording only within 24 hours of due_by', () => {
    const due = '2026-10-14T04:00:00Z';
    expect(canRecordLate('MISSED', due, new Date('2026-10-14T20:00:00Z'))).toBe(true);
    expect(canRecordLate('MISSED', due, new Date('2026-10-15T04:01:00Z'))).toBe(false);
    expect(canRecordLate('PENDING', due, new Date('2026-10-14T05:00:00Z'))).toBe(false);
    expect(canRecordLate('MISSED', null)).toBe(false);
  });
  it('computes Kolkata day bounds', () => {
    const { from, to } = dayBounds(2, new Date('2026-10-14T10:00:00Z'));
    expect(from).toBe('2026-10-13T18:30:00.000Z');
    expect(to).toBe('2026-10-15T18:30:00.000Z');
  });
  it('formats adherence', () => {
    expect(adherenceLabel(null)).toBe('—');
    expect(adherenceLabel(85.6)).toBe('86%');
  });
});
