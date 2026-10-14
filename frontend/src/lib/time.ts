export const APP_TIMEZONE = 'Asia/Kolkata';

export function formatAppTime(value: string | Date, options: Intl.DateTimeFormatOptions = {}) {
  return new Intl.DateTimeFormat('en-IN', { timeZone: APP_TIMEZONE, dateStyle: 'medium', timeStyle: 'short', ...options }).format(typeof value === 'string' ? new Date(value) : value);
}

/** Convert a datetime-local input (interpreted in Asia/Kolkata) to offset ISO. */
export function localInputToIso(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error('Enter a valid date and time');
  return new Date(`${value}:00+05:30`).toISOString();
}

export function nowLocalInput(now: Date = new Date()) {
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: APP_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(now);
  return parts.replace(' ', 'T');
}

export type WeeklyWindow = { weekday: number; start_min: number; end_min: number };
export function validateSchedule(windows: WeeklyWindow[]) {
  if (windows.some((w) => !Number.isInteger(w.weekday) || w.weekday < 0 || w.weekday > 6 || !Number.isInteger(w.start_min) || !Number.isInteger(w.end_min) || w.start_min < 0 || w.start_min >= w.end_min || w.end_min > 1440)) return false;
  return windows.every((a, i) => windows.slice(i + 1).every((b) => a.weekday !== b.weekday || Math.max(a.start_min, b.start_min) >= Math.min(a.end_min, b.end_min)));
}
