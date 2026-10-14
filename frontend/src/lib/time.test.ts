import { describe, expect, it } from 'vitest';
import { formatAppTime, localInputToIso, validateSchedule } from './time';

describe('Asia/Kolkata time helpers', () => {
  it('converts local wall time with the IST offset', () => expect(localInputToIso('2026-10-15T10:30')).toBe('2026-10-15T05:00:00.000Z'));
  it('displays instants in app timezone independent of host timezone', () => expect(formatAppTime('2026-10-15T05:00:00Z', { dateStyle: undefined, timeStyle: 'short' })).toMatch(/10:30/));
  it('rejects overlapping or malformed schedule windows', () => {
    expect(validateSchedule([{ weekday: 1, start_min: 540, end_min: 600 }, { weekday: 1, start_min: 600, end_min: 660 }])).toBe(true);
    expect(validateSchedule([{ weekday: 1, start_min: 540, end_min: 620 }, { weekday: 1, start_min: 600, end_min: 660 }])).toBe(false);
  });
});
