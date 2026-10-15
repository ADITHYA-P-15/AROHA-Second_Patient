import { formatAppTime } from './time.ts';

export type PlanAssignment = { id: string; caregiver_id: string; caregiver_name: string; role: string; status: string; is_mine: boolean };
export type CoverState = { status: string; offered_to: string | null; offered_to_me: boolean } | null;
export type PlanActivity = { cover?: CoverState; id: string; title: string; category: string; source?: string; scheduled_start: string; scheduled_end: string; care_status?: string; lifecycle_status: string; requires_caregiver?: boolean; assignments: PlanAssignment[] };

const LIVE = new Set(['PROPOSED', 'AWAITING_CONFIRMATION', 'CONFIRMED']);

/** Who is doing it, in one plain sentence. Superseded, declined and cancelled assignments are history, not state. */
export function holderSummary(a: Pick<PlanActivity, 'assignments' | 'requires_caregiver'>): { text: string; tone: 'ok' | 'waiting' | 'none' | 'muted'; confirmed?: PlanAssignment; asking?: PlanAssignment; suggested?: PlanAssignment } {
  if (a.requires_caregiver === false) return { text: 'No caretaker needed', tone: 'muted' };
  const live = a.assignments.filter(x => x.role === 'PRIMARY' && LIVE.has(x.status));
  const confirmed = live.find(x => x.status === 'CONFIRMED');
  const asking = live.find(x => x.status === 'AWAITING_CONFIRMATION');
  const suggested = live.find(x => x.status === 'PROPOSED');
  if (confirmed) return { text: confirmed.is_mine ? 'You' : confirmed.caregiver_name, tone: 'ok', confirmed, asking, suggested };
  if (asking) return { text: asking.is_mine ? 'You are asked to take this' : `Waiting for ${asking.caregiver_name} to accept`, tone: 'waiting', asking, suggested };
  if (suggested) return { text: `Suggested: ${suggested.caregiver_name}`, tone: 'waiting', suggested };
  return { text: 'No caretaker yet', tone: 'none' };
}

export function kindLabel(a: Pick<PlanActivity, 'source' | 'category'>): string {
  if (a.source === 'PRESCRIPTION' || a.category === 'MEDICATION') return 'Medicine';
  if (a.source === 'APPOINTMENT' || a.category === 'APPOINTMENT') return 'Appointment';
  return 'Home task';
}

const dayKey = (iso: string) => formatAppTime(iso, { dateStyle: undefined, timeStyle: undefined, year: 'numeric', month: '2-digit', day: '2-digit' });

/** Group activities by local day, with "Today" / "Tomorrow" / "Yesterday" labels. */
export function groupByDay<T extends { scheduled_start: string }>(items: T[], now: Date = new Date()): { key: string; label: string; items: T[] }[] {
  const today = dayKey(now.toISOString());
  const tomorrow = dayKey(new Date(now.getTime() + 86_400_000).toISOString());
  const yesterday = dayKey(new Date(now.getTime() - 86_400_000).toISOString());
  const groups = new Map<string, T[]>();
  for (const item of [...items].sort((x, y) => x.scheduled_start.localeCompare(y.scheduled_start))) {
    const key = dayKey(item.scheduled_start);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()].map(([key, rows]) => {
    const date = formatAppTime(rows[0].scheduled_start, { dateStyle: undefined, timeStyle: undefined, weekday: 'short', day: 'numeric', month: 'short' });
    const prefix = key === today ? 'Today' : key === tomorrow ? 'Tomorrow' : key === yesterday ? 'Yesterday' : '';
    return { key, label: prefix ? `${prefix} · ${date}` : date, items: rows };
  });
}

export const timeOnly = (iso: string) => formatAppTime(iso, { dateStyle: undefined, timeStyle: 'short' });

const SUPPORT_LABELS: Record<string, string> = {
  MEDICATION_ASSIST: 'Medicines', APPOINTMENT_ESCORT: 'Appointment escort', TRANSPORT: 'Transport', DAILY_ASSIST: 'Daily help',
  MOBILITY_ASSIST: 'Mobility help', PRESCRIPTION_PICKUP: 'Pharmacy pickup', LAB_ESCORT: 'Lab visits', SUPPLIES: 'Supplies',
};
export const supportLabel = (code: string) => SUPPORT_LABELS[code] ?? code.replace(/_/g, ' ').toLowerCase();

export type WeeklyWindow = { weekday: number; start_min: number; end_min: number };
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const hm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
/** "Every day 07:00–21:30", or one part per distinct set of hours. Weekday 0 is Monday. */
export function scheduleSummary(windows: WeeklyWindow[]): string {
  if (!windows.length) return 'No regular hours set';
  const byHours = new Map<string, number[]>();
  for (const w of [...windows].sort((a, b) => a.weekday - b.weekday || a.start_min - b.start_min)) {
    const hours = w.start_min === 0 && w.end_min === 1440 ? 'all day' : `${hm(w.start_min)}–${hm(w.end_min === 1440 ? 1439 : w.end_min)}`;
    byHours.set(hours, [...(byHours.get(hours) ?? []), w.weekday]);
  }
  return [...byHours.entries()].map(([hours, days]) => {
    const unique = [...new Set(days)].join();
    const label = unique === '0,1,2,3,4,5,6' ? 'Every day' : unique === '0,1,2,3,4' ? 'Weekdays' : unique === '5,6' ? 'Weekends' : [...new Set(days)].map(d => WEEKDAYS[d]).join(', ');
    return `${label} ${hours}`;
  }).join(' · ');
}

/** One line about an open cover search, or '' when there is none. */
export function coverLine(cover: CoverState | undefined): string {
  if (!cover) return '';
  if (cover.offered_to_me) return 'You have been asked to cover this — see Cover Requests';
  return cover.offered_to ? `Finding cover: ${cover.offered_to} has been asked` : 'Finding cover: a replacement is being asked';
}
