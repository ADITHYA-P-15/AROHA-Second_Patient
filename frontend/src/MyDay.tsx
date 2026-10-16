import { FormEvent, useEffect, useState } from 'react';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { PatientRatePrompt, useFeature } from './Reputation.tsx';
import { canCheckIn, checkInHint, checkInText, type CheckIn, type CheckInPolicy } from './lib/checkin.ts';
import { APP_TIMEZONE, formatAppTime, localInputToIso, nowLocalInput } from './lib/time.ts';
import { canRecordLate, dayBounds, statusLabel, statusTone } from './lib/care.ts';
import { coverLine, kindLabel, timeOnly, type CoverState } from './lib/plan.ts';

type Assignment = { id: string; caregiver_id: string; caregiver_name: string; role: string; status: string; is_mine: boolean };
type Task = { cover?: CoverState; importance?: string; requires_caregiver?: boolean; id: string; patient_id: string; title: string; category: string; description?: string; location_note?: string; scheduled_start: string; scheduled_end: string; care_status: string; due_by: string | null; source: string; completed_late: boolean; lifecycle_status: string; assignments: Assignment[] };
type Offer = { id: string; patient: { name: string }; reason_note: string; activity: { title: string; scheduled_start: string } };
type Patient = { id: string; name: string };
type Caregiver = { id: string; user_id?: string | null; name: string };
type Me = { id: string; role: string };

const EARLY_MS = 2 * 3_600_000; // matches care_status.EARLY_WINDOW
const REASONS: [string, string][] = [['PERSONAL', 'Personal'], ['ILLNESS', 'Illness'], ['TRAVEL', 'Travel'], ['WORK', 'Work'], ['EMERGENCY', 'Emergency'], ['OTHER', 'Other']];

/** Caretakers: every patient's tasks in one list. Patients: their own day, read-only. */
export function MyDay() {
  const client = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/v1/auth/me') });
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{ timezone?: string }>('/api/v1/meta') });
  const timeZone = meta.data?.timezone ?? APP_TIMEZONE;
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Patient[] }>('/api/v1/patients') });
  const readOnly = me.data?.role === 'PATIENT';
  const list = patients.data?.items ?? [];
  const today = dayBounds(1); const ahead = dayBounds(3);
  const days = useQueries({ queries: list.map(p => ({ queryKey: ['activities', p.id, 'my-day', today.from], refetchInterval: 30000,
    queryFn: () => api<{ items: Task[] }>(`/api/v1/patients/${p.id}/activities?from=${encodeURIComponent(today.from)}&to=${encodeURIComponent(ahead.to)}&limit=100`) })) });
  const offers = useQuery({ queryKey: ['cover-offers', 'mine'], queryFn: () => api<{ items: Offer[] }>('/api/v1/cover-offers/mine'), enabled: !readOnly && !!me.data, refetchInterval: 20000 });
  const caregivers = useQuery({ queryKey: ['caregivers', list[0]?.id], queryFn: () => api<{ items: Caregiver[] }>(`/api/v1/patients/${list[0].id}/caregivers`), enabled: !!list[0] && !readOnly });
  const mine = caregivers.data?.items.find(c => c.user_id === me.data?.id);
  const checkinsOn = useFeature('checkins');
  const checks = useQueries({ queries: list.map(p => ({ queryKey: ['check-ins', p.id], enabled: checkinsOn && !readOnly, refetchInterval: 30000,
    queryFn: () => api<{ items: CheckIn[]; policy: CheckInPolicy }>(`/api/v1/check-ins?patient_id=${p.id}`) })) });
  const checkPolicy = checks.find(q => q.data)?.data?.policy;
  const checkedIn = new Map(checks.flatMap(q => q.data?.items ?? []).map(c => [c.activity_id, c]));
  const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState(''); const [to, setTo] = useState(''); const [reason, setReason] = useState('PERSONAL'); const [note, setNote] = useState('');
  useEffect(() => { if (!from) setFrom(nowLocalInput(new Date(), timeZone)); }, [from, timeZone]);

  async function run(fn: () => Promise<string>, fail: string) {
    if (busy) return;
    setBusy(true);
    try { setNotice(await fn()); } catch (err) { setNotice(err instanceof Error ? err.message : fail); }
    finally {
      await Promise.all(['activities', 'cover', 'cover-offers', 'command-center', 'workload', 'notifications', 'adherence'].map(k => client.invalidateQueries({ queryKey: [k] }))).catch(() => undefined);
      setBusy(false);
    }
  }
  const checkIn = (t: Task) => void run(async () => {
    const r = await api<CheckIn>(`/api/v1/activities/${t.id}/check-in`, { method: 'POST', body: '{}' });
    await client.invalidateQueries({ queryKey: ['check-ins'] });
    return r.status === 'ON_TIME' ? `Checked in for ${t.title}. Thank you.` : `Checked in for ${t.title} (${r.minutes_late} min late).`;
  }, 'Could not check in.');
  const done = (t: Task) => void run(async () => {
    const r = await api<{ completed_late: boolean }>(`/api/v1/activities/${t.id}/complete`, { method: 'POST', body: '{}' });
    return r.completed_late ? `${t.title} recorded as done (late).` : `${t.title} marked done. Thank you.`;
  }, 'Could not record this task.');
  const cannot = (t: Task, a: Assignment) => {
    if (!window.confirm(`Can't make “${t.title}” at ${timeOnly(t.scheduled_start)}? CareCircle will ask the next best caretaker. You keep it until someone accepts.`)) return;
    void run(async () => {
      await api(`/api/v1/caregivers/${a.caregiver_id}/availability-overrides`, { method: 'POST', body: JSON.stringify({ start_at: t.scheduled_start, end_at: t.scheduled_end, status: 'UNAVAILABLE', reason: 'PERSONAL', note: `Can't make ${t.title}`.slice(0, 1000) }) });
      return 'Noted. A replacement is being asked — you keep this task until someone accepts.';
    }, 'Could not record that you are unavailable.');
  };
  const offerAct = (o: Offer, verb: 'accept' | 'decline') => void run(async () => {
    await api(`/api/v1/cover-requests/${o.id}/${verb}`, { method: 'POST', body: JSON.stringify(verb === 'decline' ? { reason: '' } : {}) });
    return verb === 'accept' ? `Thank you — you are now doing ${o.activity.title}.` : 'No problem. The next best caretaker will be asked.';
  }, 'Could not update this offer.');
  function leave(e: FormEvent) {
    e.preventDefault();
    if (!mine) { setNotice('Your caretaker profile was not found.'); return; }
    void run(async () => {
      await api(`/api/v1/caregivers/${mine.id}/availability-overrides`, { method: 'POST', body: JSON.stringify({ start_at: localInputToIso(from, timeZone), end_at: localInputToIso(to, timeZone), status: 'UNAVAILABLE', reason, note: note.trim() }) });
      setTo(''); setNote('');
      return 'Leave recorded. Your tasks in that time are being offered to other caretakers; you keep them until someone accepts.';
    }, 'Could not record leave.');
  }

  if (patients.isLoading || me.isLoading) return <section className="card"><div className="skeleton"/></section>;
  if (list.length === 0) return <section className="card">No patient is linked to this account yet.</section>;

  const names = new Map(list.map(p => [p.id, p.name]));
  const all = days.flatMap(q => q.data?.items ?? []).filter(t => t.lifecycle_status !== 'CANCELLED' && (readOnly || t.assignments.some(a => a.is_mine)))
    .sort((a, b) => a.scheduled_start.localeCompare(b.scheduled_start));
  const tasks = all.filter(t => t.scheduled_start < today.to); const next = all.filter(t => t.scheduled_start >= today.to);
  const open = tasks.filter(t => t.care_status === 'PENDING' || t.care_status === 'MISSED').length;
  const loading = days.some(q => q.isLoading);

  const card = (t: Task, actions: boolean) => {
    const mineA = t.assignments.find(a => a.is_mine && a.status === 'CONFIRMED');
    const tone = statusTone(t.care_status, t.completed_late);
    const startMs = new Date(t.scheduled_start).getTime();
    const canDo = t.care_status === 'PENDING' && startMs - Date.now() <= EARLY_MS;
    const detail = [list.length > 1 ? names.get(t.patient_id) : '', t.location_note, t.description].filter(Boolean).join(' · ');
    return <li key={t.id} className={`md-item md-task md-${tone}`}>
      <div className="md-head"><span className="md-time">{actions ? timeOnly(t.scheduled_start) : formatAppTime(t.scheduled_start, { dateStyle: 'medium', timeStyle: 'short' })}</span><strong>{t.title}</strong><span className="chip">{kindLabel(t)}</span><span className={`md-status md-st-${tone}`}>{statusLabel(t.care_status, t.completed_late)}</span></div>
      {detail && <p className="md-small">{detail}</p>}
      {!readOnly && t.care_status === 'PENDING' && t.cover && <p className="md-small cp-who-waiting">{coverLine(t.cover)}. You keep it until someone accepts.</p>}
      {!readOnly && checkedIn.get(t.id) && <p className="md-small"><span className="chip">{checkInText(checkedIn.get(t.id)!)}</span></p>}
      {!readOnly && actions && mineA && checkPolicy && canCheckIn(t, checkPolicy, checkedIn.get(t.id)) && <p className="md-small">{checkInHint(t, checkPolicy)}</p>}
      {!readOnly && actions && mineA && <div className="md-row">
        {checkPolicy && canCheckIn(t, checkPolicy, checkedIn.get(t.id)) && <button className="primary" disabled={busy} onClick={() => checkIn(t)}>I’m here · check in</button>}
        {canDo && <button className="primary" disabled={busy} onClick={() => done(t)}>Done</button>}
        {canRecordLate(t.care_status, t.due_by) && <button className="primary" disabled={busy} onClick={() => done(t)}>Record as done (late)</button>}
        {t.care_status === 'PENDING' && !t.cover && startMs > Date.now() && <button disabled={busy} onClick={() => cannot(t, mineA)}>I can’t make it</button>}
      </div>}
    </li>;
  };

  return <div className="md">
    {readOnly && <PatientRatePrompt/>}
    <div className="section-head"><div><p className="eyebrow">{readOnly ? 'TODAY' : 'MY DAY'}</p><h3>{readOnly ? 'Your day' : open ? `${open} task${open === 1 ? '' : 's'} to do today` : 'All done for today'}</h3></div></div>
    {notice && <p className="md-notice" role="status">{notice}</p>}

    {!readOnly && (offers.data?.items.length ?? 0) > 0 && <section className="card md-offers" aria-labelledby="md-off-h"><h3 id="md-off-h">Can you help?<span className="cc-count">{offers.data!.items.length}</span></h3>
      <ul className="md-list">{offers.data!.items.map(o => <li key={o.id} className="md-item">
        <strong>{o.activity.title}</strong><p className="md-small">{o.patient.name} · {formatAppTime(o.activity.scheduled_start)}</p>
        {o.reason_note && <p className="md-small muted">{o.reason_note}</p>}
        <div className="md-row"><button className="primary" disabled={busy} onClick={() => offerAct(o, 'accept')}>I can do it</button><button disabled={busy} onClick={() => offerAct(o, 'decline')}>I can’t</button></div>
      </li>)}</ul></section>}

    <section className="card" aria-labelledby="md-today-h"><h3 id="md-today-h">Today<span className="cc-count">{tasks.length}</span></h3>
      {loading && <div className="skeleton"/>}
      {!loading && tasks.length === 0 && <p className="muted">Nothing scheduled for today.</p>}
      <ul className="md-list">{tasks.map(t => card(t, true))}</ul></section>

    <section className="card"><details><summary>Next 2 days ({next.length})</summary>
      {next.length === 0 ? <p className="muted">Nothing scheduled.</p> : <ul className="md-list">{next.map(t => card(t, false))}</ul>}</details></section>

    {!readOnly && <section className="card"><details><summary>Take leave</summary>
      <p className="md-small muted">Your tasks in that time will be offered to other caretakers. You keep them until someone accepts.</p>
      <form onSubmit={leave} className="md-form">
        <label>From ({timeZone})<input type="datetime-local" required value={from} onChange={e => setFrom(e.target.value)}/></label>
        <label>To ({timeZone})<input type="datetime-local" required value={to} min={from} onChange={e => setTo(e.target.value)}/></label>
        <label>Reason<select value={reason} onChange={e => setReason(e.target.value)}>{REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Note (optional)<input maxLength={1000} value={note} onChange={e => setNote(e.target.value)}/></label>
        <button className="primary" disabled={busy || !mine}>Record leave</button>
      </form></details></section>}
  </div>;
}
