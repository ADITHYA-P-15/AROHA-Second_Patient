export const statusLabels: Record<string, string> = { OVERLOADED: 'Overloaded', NEEDS_REVIEW: 'Needs review', NEAR_LIMIT: 'Near limit', BALANCED: 'Balanced', HAS_CAPACITY: 'Has capacity', INACTIVE: 'Inactive' };
export const delegationLabels: Record<string, string> = { GENERAL: 'General', TRAINED: 'Trained caregiver', PROFESSIONAL: 'Healthcare professional only' };

export function statusLabel(status: string) { return statusLabels[status] ?? status; }
export function delegationLabel(value: string) { return delegationLabels[value] ?? value; }
/** Visual bar width is capped at 100 while the numeric label keeps the real value. */
export function barPercent(score: number) { return Math.max(0, Math.min(100, Math.round(score))); }
/** Compact weekday + day for a YYYY-MM-DD date string, timezone independent. */
export function shortDay(date: string) {
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'UTC', weekday: 'short', day: 'numeric' }).format(new Date(`${date}T00:00:00Z`));
}
