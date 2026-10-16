export const APP_TIMEZONE = 'Asia/Kolkata';

export function formatAppTime(value: string | Date, options: Intl.DateTimeFormatOptions = {}, timeZone = APP_TIMEZONE) {
  return new Intl.DateTimeFormat('en-IN', { timeZone, dateStyle: 'medium', timeStyle: 'short', ...options }).format(typeof value === 'string' ? new Date(value) : value);
}

/** Convert an app-timezone wall time from a datetime-local input to an ISO instant. */
export function localInputToIso(value: string, timeZone = APP_TIMEZONE): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error('Enter a valid date and time');
  const [year, month, day, hour, minute] = value.split(/[-T:]/).map(Number);
  const wallTime = Date.UTC(year, month - 1, day, hour, minute);
  const check = new Date(wallTime);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day || check.getUTCHours() !== hour || check.getUTCMinutes() !== minute) throw new Error('Enter a valid date and time');
  const formatter = new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  let instant = wallTime;
  for (let i = 0; i < 4; i++) {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(instant)).map(part => [part.type, Number(part.value)]));
    const displayedAsUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
    instant = wallTime - (displayedAsUtc - instant);
  }
  const roundTrip = Object.fromEntries(formatter.formatToParts(new Date(instant)).map(part => [part.type, Number(part.value)]));
  if (roundTrip.year !== year || roundTrip.month !== month || roundTrip.day !== day || roundTrip.hour !== hour || roundTrip.minute !== minute) throw new Error('That local time does not exist in the configured timezone');
  return new Date(instant).toISOString();
}

export function nowLocalInput(now: Date = new Date(), timeZone = APP_TIMEZONE) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export type WeeklyWindow = { weekday: number; start_min: number; end_min: number };
export function validateSchedule(windows: WeeklyWindow[]) {
  if (windows.some((w) => !Number.isInteger(w.weekday) || w.weekday < 0 || w.weekday > 6 || !Number.isInteger(w.start_min) || !Number.isInteger(w.end_min) || w.start_min < 0 || w.start_min >= w.end_min || w.end_min > 1440)) return false;
  return windows.every((a, i) => windows.slice(i + 1).every((b) => a.weekday !== b.weekday || Math.max(a.start_min, b.start_min) >= Math.min(a.end_min, b.end_min)));
}
