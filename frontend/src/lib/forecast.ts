import { APP_TIMEZONE } from './time.ts';

export type HorizonKey = '24h' | '3d' | '7d';
export const horizons: { key: HorizonKey; label: string; hours: number }[] = [
  { key: '24h', label: 'Next 24 hours', hours: 24 },
  { key: '3d', label: 'Next 3 days', hours: 72 },
  { key: '7d', label: 'Next 7 days', hours: 168 },
];

export const kindLabels: Record<string, string> = { GAP: 'Gap', UNCONFIRMED: 'Not confirmed', SINGLE_POINT: 'Single point of failure' };
export const levelLabels: Record<string, string> = { OK: 'Enough capacity', TIGHT: 'Tight', INSUFFICIENT: 'Not enough capacity' };
export const severityLabels: Record<string, string> = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' };
export const importanceLabels: Record<string, string> = { CRITICAL: 'Critical tasks', HIGH: 'High-importance tasks', MEDIUM: 'Medium-importance tasks', LOW: 'Low-importance tasks' };

export function kindLabel(kind: string) { return kindLabels[kind] ?? kind; }
export function levelLabel(level: string) { return levelLabels[level] ?? level; }
export function severityLabel(value: string) { return severityLabels[value] ?? value; }

/** True when `start` falls after `asOf` minus a small grace and no later than the horizon end. */
export function inHorizon(start: string, asOf: string, key: HorizonKey) {
  const hours = horizons.find(h => h.key === key)?.hours ?? 72;
  const s = new Date(start).getTime(); const a = new Date(asOf).getTime();
  if (!Number.isFinite(s) || !Number.isFinite(a)) return false;
  return s <= a + hours * 3600_000;
}

/** "Fri 16 Oct, 13:00" in the app time zone. */
export function formatSecureBy(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-IN', { timeZone: APP_TIMEZONE, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(d).map(x => [x.type, x.value]));
  return `${p.weekday} ${p.day} ${p.month}, ${p.hour}:${p.minute}`;
}

/** "16 h", "2 d 4 h", "—" when unknown. */
export function formatLeadHours(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) return '—';
  const total = Math.round(value);
  if (total < 48) return `${total} h`;
  const d = Math.floor(total / 24); const h = total % 24;
  return h ? `${d} d ${h} h` : `${d} d`;
}

export function leadRules(lead: Record<string, number>) {
  return Object.entries(lead).sort((a, b) => b[1] - a[1]).map(([k, h]) => `${importanceLabels[k] ?? k}: secure ${h} h ahead`);
}

export function tabLabel(label: string, c: { gaps: number; unconfirmed: number; single_points: number }) {
  const n = c.gaps + c.unconfirmed + c.single_points;
  return `${label} · ${n === 0 ? 'nothing to secure' : `${n} to secure`}`;
}

export function standByNotice(name: string) { return `${name} has been asked to stand by. The task stays flagged until they confirm.`; }
export function trimNote(text: string, max = 300) { return text.length <= max ? text : `${text.slice(0, max - 1)}…`; }
