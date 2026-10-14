import { FormEvent, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { formatAppTime, localInputToIso, nowLocalInput } from './lib/time.ts';
import { canRecordLate, dayBounds, sourceLabel, statusLabel, statusTone } from './lib/care.ts';
import { usePatientPick } from './PatientPick.tsx';

type Assignment = { id: string; caregiver_id: string; caregiver_name: string; role: string; status: string; is_mine: boolean };
type Task = { id: string; title: string; category: string; description?: string; location_note?: string; scheduled_start: string; scheduled_end: string; care_status: string; due_by: string | null; source: string; completed_late: boolean; lifecycle_status: string; assignments: Assignment[] };
type Offer = { id: string; patient: { name: string }; reason_note: string; activity: { title: string; scheduled_start: string } };
type Caregiver = { id: string; user_id?: string | null; name: string };
type Me = { id: string; role: string };

const hhmm = (iso: string) => formatAppTime(iso, { dateStyle: undefined, timeStyle: 'short' });
const REASONS: [string, string][] = [['PERSONAL', 'Personal'], ['ILLNESS', 'Illness'], ['TRAVEL', 'Travel'], ['WORK', 'Work'], ['EMERGENCY', 'Emergency'], ['OTHER', 'Other']];

export function MyDay() {
  const client = useQueryClient();
  const { id, picker, loading, empty } = usePatientPick();
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/v1/auth/me') });
  const readOnly = me.data?.role === 'PATIENT';
  const bounds = dayBounds(1); const ahead = dayBounds(3);
  const today = useQuery({ queryKey: ['activities', id, 'today', bounds.from], queryFn: () => api<{ items: Task[] }>(`/api/v1/patients/${id}/activities?from=${encodeURIComponent(bounds.from)}&to=${encodeURIComponent(bounds.to)}&limit=100`), enabled: !!id, refetchInterval: 30000 });
  const coming = useQuery({ queryKey: ['activities', id, 'coming', bounds.to], queryFn: () => api<{ items: Task[] }>(`/api/v1/patients/${id}/activities?from=${encodeURIComponent(bounds.to)}&to=${encodeURIComponent(ahead.to)}&limit=100`), enabled: !!id });
  const offers = useQuery({ queryKey: ['cover-offers', 'mine'], queryFn: () => api<{ items: Offer[] }>('/api/v1/cover-offers/mine'), enabled: !readOnly && !!me.data, refetchInterval: 20000 });
  const caregivers = useQuery({ queryKey: ['caregivers', id], queryFn: () => api<{ items: Caregiver[] }>(`/api/v1/patients/${id}/caregivers`), enabled: !!id && !readOnly });
  const mine = caregivers.data?.items.find(c => c.user_id === me.data?.id) ?? (me.data?.role === 'CARETAKER' ? caregivers.data?.items[0] : undefined);
  const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState(nowLocalInput()); const [to, setTo] = useState(''); const [reason, setReason] = useState('PERSONAL'); const [note, setNote] = useState('');

  async function run(fn: () => Promise<string>, fail: string) {
    if (busy) return;
    setBusy(true);
    try { setNotice(await fn()); } catch (err) { setNotice(err instanceof Error ? err.message : fail); }
    finally {
      await Promise.all(['activities', 'cover', 'cover-offers', 'command-center', 'workload', 'notifications', 'adherence'].map(k => client.invalidateQueries({ queryKey: [k] }))).catch(() => undefined);
      setBusy(false);
    }
  }
  const done = (t: Task) => void run(async () => {
    const r = await api<{ completed_late: boolean }>(`/api/v1/activities/${t.id}/complete`, { method: 'POST', body: JSON.stringify({}) });
    return r.completed_late ? `${t.title} recorded as done (late).` : `${t.title} marked done. Thank you.`;
  }, 'Could not record this task.');
  const cannot = (t: Task, a: Assignment) => {
    if (!window.confirm(`Tell the care circle you can't make “${t.title}”? A replacement will be asked automatically, and you keep this task until someone accepts.`)) return;
    void run(async () => {
      await api(`/api/v1/caregivers/${a.caregiver_id}/availability-overrides`, { method: 'POST', body: JSON.stringify({ start_at: t.scheduled_start, end_at: t.scheduled_end, status: 'UNAVAILABLE', reason: 'PERSONAL', note: `Can't make ${t.title}`.slice(0, 1000) }) });
      return 'Noted. A replacement will be asked automatically — you keep this task until someone accepts.';
    }, 'Could not record that you are unavailable.');
  };
  const offerAct = (o: Offer, verb: 'accept' | 'decline') => {
    let body: Record<string, string> = {};
    if (verb === 'decline') { const r = window.prompt('Reason (optional)', ''); if (r === null) return; body = { reason: r.trim() }; }
    void run(async () => { await api(`/api/v1/cover-requests/${o.id}/${verb}`, { method: 'POST', body: JSON.stringify(body) }); return verb === 'accept' ? 'Thank you — you are confirmed for this task.' : 'Recorded. The next best match will be asked.'; }, 'Could not update this offer.');
  };
  function leave(e: FormEvent) {
    e.preventDefault();
    if (!mine) { setNotice('Your caretaker profile was not found for this patient.'); return; }
    void run(async () => {
      await api(`/api/v1/caregivers/${mine.id}/availability-overrides`, { method: 'POST', body: JSON.stringify({ start_at: localInputToIso(from), end_at: localInputToIso(to), status: 'UNAVAILABLE', reason, note: note.trim() }) });
      setTo(''); setNote('');
      return 'Leave recorded. Your tasks in that time will be offered to other caretakers; you keep them until someone accepts.';
    }, 'Could not record leave.');
  }

  if (loading) return <section className="card"><div className="skeleton"/></section>;
  if (empty || !id) return <section className="card">No patient is linked to this account yet.</section>;

  const visible = (list?: Task[]) => (list ?? []).filter(t => readOnly || t.assignments.length === 0 || t.assignments.some(a => a.is_mine)).sort((a, b) => a.scheduled_start.localeCompare(b.scheduled_start));
  const tasks = visible(today.data?.items); const next = visible(coming.data?.items);

  const card = (t: Task, actions: boolean) => {
    const mineA = t.assignments.find(a => a.is_mine);
    const tone = statusTone(t.care_status, t.completed_late);
    return <li key={t.id} className={`md-item md-task md-${tone}`}>
      <div className="md-head"><strong>{t.title}</strong> <span className={`md-status md-st-${tone}`}>{statusLabel(t.care_status, t.completed_late)}</span></div>
      <p className="md-small">{formatAppTime(t.scheduled_start, actions ? { dateStyle: undefined } : {})}{t.care_status === 'PENDING' && t.due_by ? ` · due by ${hhmm(t.due_by)}` : ''} · {sourceLabel(t.source)}</p>
      {(t.location_note || t.description) && <p className="md-small">{[t.location_note, t.description].filter(Boolean).join(' — ')}</p>}
      {!readOnly && actions && <div className="md-row">
        {t.care_status === 'PENDING' && <button className="primary" disabled={busy} onClick={() => done(t)}>Done</button>}
        {canRecordLate(t.care_status, t.due_by) && <button className="primary" disabled={busy} onClick={() => done(t)}>Record as done (late)</button>}
        {t.care_status === 'PENDING' && mineA?.status === 'CONFIRMED' && <button disabled={busy} onClick={() => cannot(t, mineA)}>I can’t make it</button>}
      </div>}
    </li>;
  };

  return <div className="md">
    <div className="section-head"><div><p className="eyebrow">{readOnly ? 'TODAY' : 'MY DAY'}</p><h3>{readOnly ? 'Today’s plan' : 'Today’s tasks'}</h3></div>{picker}</div>
    {notice && <p className="md-notice" role="status">{notice}</p>}

    {!readOnly && (offers.data?.items.length ?? 0) > 0 && <section className="card" aria-labelledby="md-off-h"><h3 id="md-off-h">Offers for you<span className="cc-count">{offers.data!.items.length}</span></h3>
      <ul className="md-list">{offers.data!.items.map(o => <li key={o.id} className="md-item">
        <strong>{o.activity.title}</strong><p className="md-small">{o.patient.name} · {formatAppTime(o.activity.scheduled_start)}</p>
        {o.reason_note && <p className="md-small">{o.reason_note}</p>}
        <div className="md-row"><button className="primary" disabled={busy} onClick={() => offerAct(o, 'accept')}>I can do it</button><button disabled={busy} onClick={() => offerAct(o, 'decline')}>I can’t</button></div>
      </li>)}</ul></section>}

    <section className="card" aria-labelledby="md-today-h"><h3 id="md-today-h">Today<span className="cc-count">{tasks.length}</span></h3>
      {today.isLoading && <div className="skeleton"/>}
      {!today.isLoading && tasks.length === 0 && <p className="muted">Nothing scheduled for today.</p>}
      <ul className="md-list">{tasks.map(t => card(t, true))}</ul></section>

    <section className="card"><details><summary>Coming up (next 2 days) — {next.length}</summary>
      {next.length === 0 ? <p className="muted">Nothing scheduled.</p> : <ul className="md-list">{next.map(t => card(t, false))}</ul>}</details></section>

    {!readOnly && <section className="card" aria-labelledby="md-leave-h"><h3 id="md-leave-h">Take leave</h3>
      <p className="md-small muted">Your tasks in that time will be offered to other caretakers; you keep them until someone accepts.</p>
      <form onSubmit={leave} className="md-form">
        <label>From (Asia/Kolkata)<input type="datetime-local" required value={from} onChange={e => setFrom(e.target.value)}/></label>
        <label>To (Asia/Kolkata)<input type="datetime-local" required value={to} min={from} onChange={e => setTo(e.target.value)}/></label>
        <label>Reason<select value={reason} onChange={e => setReason(e.target.value)}>{REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Note (optional)<input maxLength={1000} value={note} onChange={e => setNote(e.target.value)}/></label>
        <button className="primary" disabled={busy || !mine}>Record leave</button>
      </form></section>}
  </div>;
}
