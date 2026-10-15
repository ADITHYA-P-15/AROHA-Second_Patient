import { describe, expect, it } from 'vitest';
import { canCheckIn, checkInHint, checkInText, needsCheckIn, type CheckInPolicy } from './checkin.ts';

const policy: CheckInPolicy = { categories: ['APPOINTMENT'], importance: ['MEDIUM', 'HIGH', 'CRITICAL'], opens_before_min: 60, grace_min: 15, missing_after_min: 20 };
const start = Date.parse('2026-10-15T10:00:00Z');
const task = { category: 'APPOINTMENT', importance: 'HIGH', requires_caregiver: true, scheduled_start: '2026-10-15T10:00:00Z', scheduled_end: '2026-10-15T11:00:00Z', care_status: 'PENDING' };
const min = 60_000;

describe('check-in rules in the UI', () => {
  it('only for tasks the policy covers', () => {
    expect(needsCheckIn(task, policy)).toBe(true);
    expect(needsCheckIn({ ...task, category: 'MEDICATION' }, policy)).toBe(false);
    expect(needsCheckIn({ ...task, importance: 'LOW' }, policy)).toBe(false);
  });
  it('opens an hour before and closes at the end, once', () => {
    expect(canCheckIn(task, policy, undefined, start - 61 * min)).toBe(false);
    expect(canCheckIn(task, policy, undefined, start - 59 * min)).toBe(true);
    expect(canCheckIn(task, policy, undefined, start + 61 * min)).toBe(false);
    expect(canCheckIn({ ...task, care_status: 'COMPLETED' }, policy, undefined, start)).toBe(false);
    expect(canCheckIn(task, policy, { id: 'c', activity_id: 'a', caregiver_id: 'g', status: 'ON_TIME', minutes_late: 0, checked_in_at: '' }, start)).toBe(false);
  });
  it('words the state and the rule', () => {
    expect(checkInText({ id: 'c', activity_id: 'a', caregiver_id: 'g', status: 'LATE', minutes_late: 22, checked_in_at: '' })).toBe('Checked in 22 min late');
    expect(checkInHint(task, policy, start)).toContain('on time until 15 min');
    expect(checkInHint(task, policy, start + 18 * min)).toContain('check in now');
    expect(checkInHint(task, policy, start + 25 * min)).toContain('finding cover');
  });
});
