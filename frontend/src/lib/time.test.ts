import { describe, expect, it } from 'vitest';
import { formatAppTime, localInputToIso, nowLocalInput, validateSchedule } from './time';

describe('configured timezone helpers', () => {
  it('converts the app local time using the selected IANA timezone', () => {
    expect(localInputToIso('2026-10-15T10:30', 'Asia/Kolkata')).toBe('2026-10-15T05:00:00.000Z');
    expect(localInputToIso('2026-10-30T14:00', 'UTC')).toBe('2026-10-30T14:00:00.000Z');
    expect(localInputToIso('2026-10-30T14:00', 'America/New_York')).toBe('2026-10-30T18:00:00.000Z');
  });
  it('rejects invalid wall times and DST gaps', () => {
    expect(() => localInputToIso('2026-02-30T14:00', 'UTC')).toThrow();
    expect(() => localInputToIso('2026-03-08T02:30', 'America/New_York')).toThrow(/does not exist/);
  });
  it('formats the current input value in the configured timezone', () => {
    expect(nowLocalInput(new Date('2026-10-30T14:00:00Z'), 'UTC')).toBe('2026-10-30T14:00');
    expect(nowLocalInput(new Date('2026-10-30T14:00:00Z'), 'America/New_York')).toBe('2026-10-30T10:00');
  });
  it('displays instants in app timezone independent of host timezone', () => expect(formatAppTime('2026-10-15T05:00:00Z', { dateStyle: undefined, timeStyle: 'short' })).toMatch(/10:30/));
  it('rejects overlapping or malformed schedule windows', () => {
    expect(validateSchedule([{ weekday: 1, start_min: 540, end_min: 600 }, { weekday: 1, start_min: 600, end_min: 660 }])).toBe(true);
    expect(validateSchedule([{ weekday: 1, start_min: 540, end_min: 620 }, { weekday: 1, start_min: 600, end_min: 660 }])).toBe(false);
  });
});
