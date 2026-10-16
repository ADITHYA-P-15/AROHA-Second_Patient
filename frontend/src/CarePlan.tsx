import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { usePatientPick } from './PatientPick.tsx';
import { canRecordLate, statusLabel, statusTone } from './lib/care.ts';
import { coverLine, groupByDay, holderSummary, kindLabel, supportLabel, timeOnly, type PlanActivity, type PlanAssignment } from './lib/plan.ts';
import { APP_TIMEZONE, localInputToIso, nowLocalInput } from './lib/time.ts';
import { ProofPhotoReview } from './ProofPhotoReview.tsx';
import { ProofPhotoCapture } from './ProofPhoto.tsx';

type Activity = PlanActivity & { description?: string | null; location_note?: string | null; due_by?: string | null; completed_late?: boolean; my_permissions: string[] };
type Caregiver = { id: string; name: string; is_active: boolean };
type Filter = 'ALL' | 'MEDICINE' | 'APPOINTMENT' | 'ATTENTION';
const DAY = 86_400_000;
const EARLY_MS = 2 * 3_600_000; // matches care_status.EARLY_WINDOW
const FILTERS: [Filter, string][] = [['ALL', 'All'], ['MEDICINE', 'Medicines'], ['APPOINTMENT', 'Appointments'], ['ATTENTION', 'Needs attention']];
const HOME_SUPPORT = ['DAILY_ASSIST', 'MOBILITY_ASSIST', 'TRANSPORT', 'PRESCRIPTION_PICKUP', 'SUPPLIES'];

const needsAttention = (a: Activity) => a.care_status === 'MISSED' || (a.care_status === 'PENDING' && (!!a.cover || (holderSummary(a).tone !== 'ok' && holderSummary(a).tone !== 'muted')));

export function CarePlan({ role }: { role: string }) {
  const { id, picker, loading, empty } = usePatientPick();
  const client = useQueryClient(); const navigate = useNavigate();
  const [past, setPast] = useState(false); const [filter, setFilter] = useState<Filter>('ALL');
  const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const start = new Date(); start.setMinutes(0, 0, 0);
  const from = past ? new Date(start.getTime() - 7 * DAY) : new Date(start.getTime() - 12 * 3_600_000);
  const to = past ? start : new Date(start.getTime() + 7 * DAY);
  const activities = useQuery({ queryKey: ['activities', id, 'plan', past], queryFn: () => api<{ items: Activity[] }>(`/api/v1/patients/${id}/activities?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}&limit=100`), enabled: !!id, refetchInterval: 30000 });
  const patient = useQuery({ queryKey: ['patient', id], queryFn: () => api<{ my_permissions: string[] }>(`/api/v1/patients/${id}`), enabled: !!id });
  const manager = !!patient.data?.my_permissions?.includes('plan:manage') && role === 'PRIMARY_CONTACT';
  const caregivers = useQuery({ queryKey: ['caregivers', id], queryFn: () => api<{ items: Caregiver[] }>(`/api/v1/patients/${id}/caregivers`), enabled: !!id && manager });
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{ timezone?: string }>('/api/v1/meta') });
  const timeZone = meta.data?.timezone ?? APP_TIMEZONE;

  async function run(fn: () => Promise<string>, fail: string) {
    if (busy) return;
    setBusy(true);
    try { setNotice(await fn()); } catch (err) { setNotice(err instanceof Error ? err.message : fail); }
    finally {
      await Promise.all(['activities', 'cover', 'cover-offers', 'command-center', 'notifications', 'adherence', 'workload', 'forecast', 'proof-photos'].map(k => client.invalidateQueries({ queryKey: [k] }))).catch(() => undefined);
      setBusy(false);
    }
  }
  const post = (path: string, body: unknown = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });
  const photoDone = (msg: string) => { setNotice(msg); void Promise.all(['activities', 'cover', 'cover-offers', 'command-center', 'notifications', 'adherence', 'workload', 'forecast', 'proof-photos'].map(k => client.invalidateQueries({ queryKey: [k] }))).catch(() => undefined); };
  const actions = {
    done: (a: Activity) => run(async () => { const r = await api<{ completed_late: boolean }>(`/api/v1/activities/${a.id}/complete`, { method: 'POST', body: '{}' }); return `${a.title} recorded as done${r.completed_late ? ' (late)' : ''}.`; }, 'Could not record this.'),
    cannot: (a: Activity, x: PlanAssignment) => {
      if (!window.confirm(`Can't make “${a.title}” at ${timeOnly(a.scheduled_start)}? AROHA will ask the next best caretaker. You keep it until someone accepts.`)) return;
      void run(async () => { await post(`/api/v1/caregivers/${x.caregiver_id}/availability-overrides`, { start_at: a.scheduled_start, end_at: a.scheduled_end, status: 'UNAVAILABLE', reason: 'PERSONAL', note: `Can't make ${a.title}`.slice(0, 1000) }); return 'Noted. A replacement is being asked — you keep this until someone accepts.'; }, 'Could not record that.');
    },
    respond: (x: PlanAssignment, verb: 'confirm' | 'decline') => run(async () => { await post(`/api/v1/assignments/${x.id}/${verb}`, verb === 'decline' ? { reason: 'Unable to attend' } : {}); return verb === 'confirm' ? 'You are confirmed for this.' : 'Declined. Someone else will be asked.'; }, 'Could not update.'),
    assign: (a: Activity, caregiverId: string) => run(async () => { await post(`/api/v1/activities/${a.id}/assignments`, { caregiver_id: caregiverId, role: 'PRIMARY', confirm_now: true, scope: 'THIS' }); return `${caregivers.data?.items.find(c => c.id === caregiverId)?.name ?? 'Caretaker'} is now doing ${a.title}.`; }, 'Could not assign.'),
    cover: (a: Activity) => run(async () => { await post(`/api/v1/activities/${a.id}/cover-requests`, { note: 'Asked from Care Plan' }); navigate(`/cover?patient=${id}`); return 'Looking for cover.'; }, 'Could not start a cover search.'),
  };

  if (loading) return <section className="card"><div className="skeleton"/></section>;
  if (empty || !id) return <section className="card">No patient is linked to this account yet.</section>;
  const rows = (activities.data?.items ?? []).filter(a => a.lifecycle_status !== 'CANCELLED').filter(a =>
    filter === 'ALL' ? true : filter === 'MEDICINE' ? kindLabel(a) === 'Medicine' : filter === 'APPOINTMENT' ? kindLabel(a) === 'Appointment' : needsAttention(a));
  const groups = groupByDay(rows);
  if (past) groups.reverse();
  const attention = (activities.data?.items ?? []).filter(a => a.lifecycle_status !== 'CANCELLED' && needsAttention(a)).length;

  return <div className="cp">
    <div className="section-head"><div><p className="eyebrow">CARE PLAN</p><h3>{past ? 'Last 7 days' : 'Today and the next 7 days'}</h3></div>{picker}</div>
    {notice && <p className="md-notice" role="status">{notice}</p>}
    {manager && id && <ProofPhotoReview patientId={id} onDone={msg => { setNotice(msg); void client.invalidateQueries({ queryKey: ['proof-photos'] }); }}/>}
    <div className="cp-toolbar">
      <div className="cp-filters" role="group" aria-label="Show">{FILTERS.map(([value, label]) => <button key={value} className={`cp-filter${filter === value ? ' on' : ''}`} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}{value === 'ATTENTION' && attention > 0 ? <span className="cp-badge">{attention}</span> : null}</button>)}</div>
      <button className="cp-filter" onClick={() => setPast(!past)}>{past ? 'Show upcoming' : 'Show last 7 days'}</button>
    </div>
    {activities.isLoading && <div className="skeleton"/>}
    {!activities.isLoading && groups.length === 0 && <section className="card cp-empty"><p>{filter === 'ATTENTION' ? 'Nothing needs attention. Every task has a caretaker.' : 'Nothing scheduled in this period.'}</p></section>}
    {groups.map(g => <section key={g.key} className="cp-day" aria-label={g.label}>
      <h4>{g.label}</h4>
      <ul>{g.items.map(a => <PlanRow key={a.id} a={a} role={role} manager={manager} busy={busy} caregivers={caregivers.data?.items ?? []} actions={actions} timeZone={timeZone} onPhotoDone={photoDone}/>)}</ul>
    </section>)}
    {manager && !past && <HomeTask patientId={id} onDone={msg => { setNotice(msg); void client.invalidateQueries({ queryKey: ['activities'] }); }}/>}
  </div>;
}

type Actions = { done: (a: Activity) => Promise<void>; cannot: (a: Activity, x: PlanAssignment) => void; respond: (x: PlanAssignment, verb: 'confirm' | 'decline') => Promise<void>; assign: (a: Activity, caregiverId: string) => Promise<void>; cover: (a: Activity) => Promise<void> };

function PlanRow({ a, role, manager, busy, caregivers, actions, timeZone, onPhotoDone }: { a: Activity; role: string; manager: boolean; busy: boolean; caregivers: Caregiver[]; actions: Actions; timeZone: string; onPhotoDone: (msg: string) => void }) {
  const [picking, setPicking] = useState(false); const [choice, setChoice] = useState('');
  const [showPhoto, setShowPhoto] = useState(false);
  const who = holderSummary(a);
  const tone = statusTone(a.care_status, a.completed_late);
  const now = Date.now(); const startMs = new Date(a.scheduled_start).getTime();
  const pending = a.care_status === 'PENDING';
  const upcoming = pending && startMs > now;
  const mineConfirmed = who.confirmed?.is_mine ? who.confirmed : undefined;
  // A medicine dose must be given and photographed by its assigned caretaker; the primary contact reviews the photo
  // afterwards instead of recording it themselves (and Care Plan has no camera flow to let them anyway).
  const mayRecord = a.source === 'PRESCRIPTION' ? !!mineConfirmed : (manager || !!mineConfirmed);
  const canRecord = (pending && startMs - now <= EARLY_MS && mayRecord) || (mayRecord && canRecordLate(a.care_status ?? '', a.due_by));
  const detail = [a.location_note, a.description].filter(Boolean).join(' · ');
  const others = caregivers.filter(c => c.is_active && c.id !== who.confirmed?.caregiver_id);
  return <li className={`cp-row cp-${tone}`}>
    <span className="cp-time">{timeOnly(a.scheduled_start)}</span>
    <div className="cp-main">
      <div className="cp-title"><strong>{a.title}</strong><span className="chip">{kindLabel(a)}</span><span className={`md-status md-st-${tone}`}>{statusLabel(a.care_status, a.completed_late)}</span></div>
      {detail && <p className="cp-detail">{detail}</p>}
      <p className={`cp-who cp-who-${who.tone}`}><span>Caretaker:</span> {who.text}</p>
      {pending && a.cover && <p className="cp-who cp-who-waiting">{coverLine(a.cover)}</p>}
      {role !== 'PATIENT' && showPhoto && <ProofPhotoCapture activityId={a.id} title={a.title} timeZone={timeZone} onDone={msg => { setShowPhoto(false); onPhotoDone(msg); }} onCancel={() => setShowPhoto(false)}/>}
      {role !== 'PATIENT' && !showPhoto && <div className="cp-actions">
        {canRecord && <button className="cp-btn cp-primary" disabled={busy} onClick={() => a.source === 'PRESCRIPTION' ? setShowPhoto(true) : void actions.done(a)}>{a.care_status === 'MISSED' ? 'Record as done (late)' : 'Mark done'}</button>}
        {who.asking?.is_mine && <><button className="cp-btn cp-primary" disabled={busy} onClick={() => void actions.respond(who.asking!, 'confirm')}>Accept</button><button className="cp-btn" disabled={busy} onClick={() => void actions.respond(who.asking!, 'decline')}>Decline</button></>}
        {upcoming && mineConfirmed && !manager && !a.cover && startMs - now < 2 * DAY && <button className="cp-btn" disabled={busy} onClick={() => actions.cannot(a, mineConfirmed)}>I can’t make it</button>}
        {upcoming && manager && a.requires_caregiver !== false && !picking && <button className="cp-btn" disabled={busy} onClick={() => setPicking(true)}>{who.confirmed ? 'Change caretaker' : 'Assign caretaker'}</button>}
      </div>}
      {picking && <div className="cp-assign">
        <label>Caretaker<select value={choice} onChange={e => setChoice(e.target.value)}><option value="">Choose…</option>{others.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <button className="cp-btn cp-primary" disabled={busy || !choice} onClick={() => { void actions.assign(a, choice); setPicking(false); setChoice(''); }}>Assign</button>
        {who.confirmed && <button className="cp-btn" disabled={busy} onClick={() => { setPicking(false); void actions.cover(a); }}>Let AROHA find someone</button>}
        <button className="cp-btn" onClick={() => setPicking(false)}>Cancel</button>
      </div>}
    </div>
  </li>;
}

function HomeTask({ patientId, onDone }: { patientId: string; onDone: (msg: string) => void }) {
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{ timezone?: string }>('/api/v1/meta') });
  const timeZone = meta.data?.timezone ?? APP_TIMEZONE;
  const [title, setTitle] = useState(''); const [start, setStart] = useState(''); const [minutes, setMinutes] = useState(30); const [support, setSupport] = useState('DAILY_ASSIST'); const [error, setError] = useState('');
  useEffect(() => { if (!start) setStart(nowLocalInput(new Date(), timeZone)); }, [start, timeZone]);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError('');
    try {
      const begin = localInputToIso(start, timeZone);
      await api(`/api/v1/patients/${patientId}/activities`, { method: 'POST', body: JSON.stringify({ title: title.trim(), category: 'DAILY_ROUTINE', scheduled_start: begin, scheduled_end: new Date(new Date(begin).getTime() + minutes * 60_000).toISOString(), required_support: [support], requires_caregiver: true, importance: 'MEDIUM' }) });
      setTitle(''); onDone(`“${title.trim()}” added. Assign a caretaker from the plan above.`);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not add the task.'); }
  }
  return <details className="card cp-add"><summary>Add a home task</summary>
    <p className="muted small">Medicines and appointments come from the hospital. Use this for other help at home, such as a grocery run.</p>
    <form className="md-form" onSubmit={submit}>
      <label>What needs doing<input required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Pick up groceries"/></label>
      <label>When ({timeZone})<input type="datetime-local" required value={start} onChange={e => setStart(e.target.value)}/></label>
      <label>How long (minutes)<input type="number" min={10} max={480} step={5} required value={minutes} onChange={e => setMinutes(Number(e.target.value))}/></label>
      <label>Kind of help<select value={support} onChange={e => setSupport(e.target.value)}>{HOME_SUPPORT.map(s => <option key={s} value={s}>{supportLabel(s)}</option>)}</select></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary">Add task</button>
    </form></details>;
}
