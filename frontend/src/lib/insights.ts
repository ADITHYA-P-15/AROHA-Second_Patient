export type Flag = { code: string; text: string };
export type MedicineStat = { medicine: string; dose?: string; due: number; on_time: number; late: number; missed: number; pending: number; decided: number; taken_pct: number | null; on_time_pct: number | null; patients?: number };
export type PatientInsight = {
  id: string; name: string; birth_year: number | null; care_code: string | null;
  due: number; on_time: number; late: number; missed: number; pending: number; decided: number; taken_pct: number | null; on_time_pct: number | null;
  recent: { due: number; missed: number; taken_pct: number | null }; trend: 'improving' | 'steady' | 'slipping' | 'not_enough_data';
  needs_follow_up: boolean; flags: Flag[]; next_appointment: { id: string; title: string; start: string; covered: boolean } | null;
  uncovered_appointments: number; open_requests: number; medicines: MedicineStat[]; spark: (number | null)[];
};
export type Insights = {
  as_of: string; days: number; note: string; thresholds: { low_taken_pct: number; missed_recent: number; recent_days: number };
  totals: { patients: number; due: number; on_time: number; late: number; missed: number; pending: number; decided: number; taken_pct: number | null; on_time_pct: number | null;
    needs_follow_up: number; appointments_next_7_days: number; uncovered_appointments: number; open_requests: number; avg_ack_minutes: number | null; requests?: number };
  bands: { on_track: number; watch: number; follow_up: number; no_data: number };
  daily: { date: string; due: number; missed: number; decided: number; taken_pct: number | null }[];
  patients: PatientInsight[]; medicines: MedicineStat[];
};
export type Band = 'on_track' | 'watch' | 'follow_up' | 'no_data';
export type BandFilter = 'all' | Band;

export const BAND_LABEL: Record<Band, string> = { on_track: 'On track', watch: 'Keep an eye', follow_up: 'Follow-up suggested', no_data: 'Not enough data yet' };

/** Same bands as the backend summary: flagged is follow-up; too few recorded doses is "no data"; then under 90 % is watch. */
export function bandOf(p: Pick<PatientInsight, 'taken_pct' | 'needs_follow_up' | 'decided'>, minDecided = 8): Band {
  if (p.needs_follow_up) return 'follow_up';
  if (p.taken_pct === null || p.decided < minDecided) return 'no_data';
  return p.taken_pct < 90 ? 'watch' : 'on_track';
}

export function trendText(trend: PatientInsight['trend']): string {
  return trend === 'improving' ? 'Improving' : trend === 'slipping' ? 'Slipping' : trend === 'steady' ? 'Steady' : 'Not enough data';
}

export function pctText(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value)}%`;
}

export function filterPatients(list: PatientInsight[], query: string, band: BandFilter): PatientInsight[] {
  const q = query.trim().toLowerCase();
  return list.filter(p => (band === 'all' || bandOf(p) === band) && (!q || p.name.toLowerCase().includes(q) || (p.care_code ?? '').toLowerCase().includes(q)));
}

const csvCell = (value: string | number | null) => {
  const text = value === null ? '' : String(value);
  // Quote everything that could break a row, and neutralise spreadsheet formulas.
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

export function toCsv(data: Insights): string {
  const header = ['Patient', 'CareCircle ID', 'Doses due', 'On time', 'Late', 'Missed', 'Given %', 'Missed last 7 days', 'Trend', 'Follow-up suggested', 'Next appointment', 'Open requests'];
  const rows = data.patients.map(p => [p.name, p.care_code, p.due, p.on_time, p.late, p.missed, p.taken_pct, p.recent.missed, trendText(p.trend), p.needs_follow_up ? 'Yes' : 'No',
    p.next_appointment ? `${p.next_appointment.title} (${p.next_appointment.start.slice(0, 10)})` : '', p.open_requests]);
  return [header, ...rows].map(r => r.map(c => csvCell(c as string | number | null)).join(',')).join('\n') + '\n';
}
