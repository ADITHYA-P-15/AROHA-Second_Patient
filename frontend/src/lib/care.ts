import { localInputToIso, nowLocalInput } from './time.ts';

export type CareStatus = 'PENDING' | 'COMPLETED' | 'MISSED' | 'CANCELLED';
const DAY_MS = 86_400_000;
const LATE_WINDOW_MS = DAY_MS;

export function statusLabel(status: string | undefined, completedLate = false): string {
  if (status === 'COMPLETED') return completedLate ? 'Done late' : 'Done';
  if (status === 'MISSED') return 'Missed';
  if (status === 'CANCELLED') return 'Cancelled';
  return 'Pending';
}

export function statusTone(status: string | undefined, completedLate = false): 'ok' | 'late' | 'bad' | 'muted' | 'pending' {
  if (status === 'COMPLETED') return completedLate ? 'late' : 'ok';
  if (status === 'MISSED') return 'bad';
  if (status === 'CANCELLED') return 'muted';
  return 'pending';
}

export function sourceLabel(source: string | undefined): string {
  if (source === 'PRESCRIPTION') return 'Prescription';
  if (source === 'APPOINTMENT') return 'Appointment';
  return 'Added by family';
}

/** A missed task may still be recorded as done within 24 h of its due-by time. */
export function canRecordLate(status: string, dueBy: string | null | undefined, now: Date = new Date()): boolean {
  if (status !== 'MISSED' || !dueBy) return false;
  const due = new Date(dueBy).getTime();
  return Number.isFinite(due) && now.getTime() <= due + LATE_WINDOW_MS;
}

/** ISO bounds of "today" (Asia/Kolkata) plus a number of extra days. */
export function dayBounds(days = 1, now: Date = new Date()): { from: string; to: string } {
  const local = nowLocalInput(now).slice(0, 10);
  const from = new Date(localInputToIso(`${local}T00:00`));
  return { from: from.toISOString(), to: new Date(from.getTime() + days * DAY_MS).toISOString() };
}

export function adherenceLabel(pct: number | null | undefined): string {
  return pct === null || pct === undefined ? '—' : `${Math.round(pct)}%`;
}
