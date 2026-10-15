export type CheckInPolicy = { categories: string[]; importance: string[]; opens_before_min: number; grace_min: number; missing_after_min: number };
export type CheckIn = { id: string; activity_id: string; caregiver_id: string; status: 'ON_TIME' | 'LATE'; minutes_late: number; checked_in_at: string };
type TaskLike = { category: string; importance?: string; requires_caregiver?: boolean; scheduled_start: string; scheduled_end: string; care_status: string };

export const needsCheckIn = (t: TaskLike, p: CheckInPolicy) => !!t.requires_caregiver && p.categories.includes(t.category) && p.importance.includes(t.importance ?? 'MEDIUM');

/** Whether the "I'm here" button shows: the task needs one, is still pending, and we are between (start - opens_before) and the end. */
export function canCheckIn(t: TaskLike, p: CheckInPolicy, done: CheckIn | undefined, now: number = Date.now()): boolean {
  if (done || t.care_status !== 'PENDING' || !needsCheckIn(t, p)) return false;
  const start = new Date(t.scheduled_start).getTime();
  return now >= start - p.opens_before_min * 60_000 && now <= new Date(t.scheduled_end).getTime();
}

export function checkInText(c: CheckIn): string {
  return c.status === 'ON_TIME' ? 'Checked in on time' : `Checked in ${c.minutes_late} min late`;
}

/** What the caretaker reads under the button, so the rule is never a surprise. */
export function checkInHint(t: TaskLike, p: CheckInPolicy, now: number = Date.now()): string {
  const start = new Date(t.scheduled_start).getTime();
  if (now <= start + p.grace_min * 60_000) return `Check in when you arrive; on time until ${p.grace_min} min after the start.`;
  if (now <= start + p.missing_after_min * 60_000) return 'You are past the start: check in now so nobody is asked to cover.';
  return 'No check-in yet: the care team may be finding cover. Check in if you are here.';
}
