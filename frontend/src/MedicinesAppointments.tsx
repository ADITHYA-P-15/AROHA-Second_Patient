import { FormEvent, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { formatAppTime, localInputToIso, nowLocalInput } from './lib/time.ts';
import { adherenceLabel } from './lib/care.ts';
import { usePatientPick } from './PatientPick.tsx';

type Prescription = { id: string; medicine: string; dose: string; instructions: string; times: string[]; start_date: string; end_date: string | null; status: string; next_dose_at: string | null; stopped_at: string | null; stop_reason: string | null };
type Appointment = { id: string; title: string; start: string; end: string; location: string; notes: string; needs_escort: boolean; importance: string; status: string };
type AdherenceMed = { medicine: string; dose: string; due: number; on_time: number; late: number; missed: number; pending: number; on_time_pct: number | null };
type Adherence = { days: number; medicines: AdherenceMed[]; totals: Record<string, number>; on_time_pct: number | null; note: string };
type PatientInfo = { my_permissions: string[] };

function TimeChips({ times, onChange, label }: { times: string[]; onChange: (t: string[]) => void; label: string }) {
  const [value, setValue] = useState('08:00');
  const add = () => { if (value && !times.includes(value)) onChange([...times, value].sort()); };
  return <fieldset className="md-times"><legend>{label}</legend>
    <ul className="md-chiplist">{times.map(t => <li key={t}><span className="chip">{t}</span><button type="button" className="md-x" aria-label={`Remove ${t}`} onClick={() => onChange(times.filter(x => x !== t))}>×</button></li>)}{times.length === 0 && <li className="muted">No times yet</li>}</ul>
    <div className="md-row"><input type="time" aria-label="Dose time" value={value} onChange={e => setValue(e.target.value)}/><button type="button" onClick={add}>Add time</button></div>
  </fieldset>;
}

export function MedicinesAppointments() {
  const client = useQueryClient();
  const { id, picker, loading, empty } = usePatientPick();
  const patient = useQuery({ queryKey: ['patient', id], queryFn: () => api<PatientInfo>(`/api/v1/patients/${id}`), enabled: !!id });
  const canPrescribe = !!patient.data?.my_permissions?.includes('care:prescribe');
  const rx = useQuery({ queryKey: ['prescriptions', id], queryFn: () => api<{ items: Prescription[] }>(`/api/v1/patients/${id}/prescriptions?status=active`), enabled: !!id });
  const appts = useQuery({ queryKey: ['appointments', id], queryFn: () => api<{ items: Appointment[] }>(`/api/v1/patients/${id}/appointments?include_past=false`), enabled: !!id });
  const adherence = useQuery({ queryKey: ['adherence', id], queryFn: () => api<Adherence>(`/api/v1/patients/${id}/adherence?days=7`), enabled: !!id, retry: false });
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const [medicine, setMedicine] = useState(''); const [dose, setDose] = useState(''); const [instructions, setInstructions] = useState('');
  const [times, setTimes] = useState<string[]>([]); const [startDate, setStartDate] = useState(nowLocalInput().slice(0, 10)); const [endDate, setEndDate] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [eDose, setEDose] = useState(''); const [eInstr, setEInstr] = useState(''); const [eTimes, setETimes] = useState<string[]>([]); const [eEnd, setEEnd] = useState('');
  const [title, setTitle] = useState(''); const [when, setWhen] = useState(''); const [duration, setDuration] = useState('30'); const [location, setLocation] = useState('');
  const [notes, setNotes] = useState(''); const [escort, setEscort] = useState(true); const [importance, setImportance] = useState('MEDIUM');

  async function run(fn: () => Promise<string>, fail: string) {
    if (busy) return;
    setBusy(true);
    try { setNotice(await fn()); } catch (err) { setNotice(err instanceof Error ? err.message : fail); }
    finally {
      await Promise.all(['prescriptions', 'appointments', 'adherence', 'activities', 'command-center', 'history'].map(k => client.invalidateQueries({ queryKey: [k] }))).catch(() => undefined);
      setBusy(false);
    }
  }
  function prescribe(e: FormEvent) {
    e.preventDefault();
    if (times.length === 0) { setNotice('Add at least one dose time.'); return; }
    void run(async () => {
      const r = await api<{ doses_created: number }>(`/api/v1/patients/${id}/prescriptions`, { method: 'POST', body: JSON.stringify({ medicine: medicine.trim(), dose: dose.trim(), instructions: instructions.trim(), times, start_date: startDate, ...(endDate ? { end_date: endDate } : {}) }) });
      const name = medicine.trim(); setMedicine(''); setDose(''); setInstructions(''); setTimes([]); setEndDate('');
      return `${name} prescribed — ${r.doses_created} doses scheduled.`;
    }, 'Could not save the prescription.');
  }
  function startEdit(p: Prescription) { setEditing(p.id); setEDose(p.dose); setEInstr(p.instructions); setETimes(p.times); setEEnd(p.end_date ?? ''); }
  function saveEdit(p: Prescription) {
    if (eTimes.length === 0) { setNotice('Keep at least one dose time.'); return; }
    void run(async () => {
      const r = await api<{ doses_cancelled: number; doses_created: number }>(`/api/v1/prescriptions/${p.id}`, { method: 'PATCH', body: JSON.stringify({ dose: eDose.trim(), instructions: eInstr.trim(), times: eTimes, ...(eEnd ? { end_date: eEnd } : {}) }) });
      setEditing(null);
      return `${p.medicine} updated — ${r.doses_cancelled} doses replaced by ${r.doses_created} new ones.`;
    }, 'Could not change the prescription.');
  }
  function stop(p: Prescription) {
    const reason = window.prompt(`Why are you stopping ${p.medicine}?`, '');
    if (reason === null) return;
    void run(async () => { await api(`/api/v1/prescriptions/${p.id}/stop`, { method: 'POST', body: JSON.stringify({ reason: reason.trim() }) }); return `${p.medicine} stopped. Upcoming doses were removed.`; }, 'Could not stop the prescription.');
  }
  function schedule(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      const start = localInputToIso(when);
      await api(`/api/v1/patients/${id}/appointments`, { method: 'POST', body: JSON.stringify({ title: title.trim(), start, duration_minutes: Number(duration), location: location.trim(), notes: notes.trim(), needs_escort: escort, importance }) });
      const t = title.trim(); setTitle(''); setWhen(''); setLocation(''); setNotes('');
      return `${t} scheduled for ${formatAppTime(start)}.`;
    }, 'Could not schedule the appointment.');
  }
  function cancelAppt(a: Appointment) {
    const reason = window.prompt(`Why is “${a.title}” being cancelled?`, '');
    if (reason === null) return;
    void run(async () => { await api(`/api/v1/appointments/${a.id}/cancel`, { method: 'POST', body: JSON.stringify({ reason: reason.trim() }) }); return `${a.title} cancelled.`; }, 'Could not cancel the appointment.');
  }

  if (loading) return <section className="card"><div className="skeleton"/></section>;
  if (empty || !id) return <section className="card">No patient is linked to this account yet.</section>;
  const meds = rx.data?.items ?? [];
  const upcoming = appts.data?.items ?? [];

  return <div className="md">
    <div className="section-head"><div><p className="eyebrow">MEDICINES &amp; APPOINTMENTS</p><h3>{canPrescribe ? 'Prescribe and schedule' : 'Medicines and appointments'}</h3></div>{picker}</div>
    {notice && <p className="md-notice" role="status">{notice}</p>}

    {canPrescribe && <section className="card" aria-labelledby="md-rx-h"><h3 id="md-rx-h">Prescribe a medicine</h3>
      <form onSubmit={prescribe} className="md-form">
        <label>Medicine<input required maxLength={120} value={medicine} onChange={e => setMedicine(e.target.value)}/></label>
        <label>Dose<input required maxLength={120} value={dose} onChange={e => setDose(e.target.value)} placeholder="e.g. 500 mg"/></label>
        <label>Instructions<input maxLength={500} value={instructions} onChange={e => setInstructions(e.target.value)} placeholder="e.g. after food"/></label>
        <TimeChips times={times} onChange={setTimes} label="Dose times each day"/>
        <label>Start date<input type="date" required value={startDate} onChange={e => setStartDate(e.target.value)}/></label>
        <label>End date (optional)<input type="date" value={endDate} min={startDate} onChange={e => setEndDate(e.target.value)}/></label>
        <button className="primary" disabled={busy}>Prescribe</button>
      </form>
    </section>}

    <section className="card" aria-labelledby="md-active-h"><h3 id="md-active-h">Active prescriptions<span className="cc-count">{meds.length}</span></h3>
      {meds.length === 0 && <p className="muted">No active prescriptions.</p>}
      <ul className="md-list">{meds.map(p => <li key={p.id} className="md-item">
        <div className="md-head"><strong>{p.medicine}</strong> <span className="muted">{p.dose}</span></div>
        {p.instructions && <p className="md-small">{p.instructions}</p>}
        <p className="md-small">{p.times.map(t => <span className="chip" key={t}>{t}</span>)} {p.next_dose_at ? <>Next dose {formatAppTime(p.next_dose_at)}</> : 'No upcoming dose'}{p.end_date ? ` · until ${p.end_date}` : ''}</p>
        {canPrescribe && editing !== p.id && <div className="md-row"><button onClick={() => startEdit(p)} disabled={busy}>Change</button><button onClick={() => stop(p)} disabled={busy}>Stop</button></div>}
        {canPrescribe && editing === p.id && <div className="md-edit">
          <label>Dose<input value={eDose} onChange={e => setEDose(e.target.value)}/></label>
          <label>Instructions<input value={eInstr} onChange={e => setEInstr(e.target.value)}/></label>
          <TimeChips times={eTimes} onChange={setETimes} label="Dose times"/>
          <label>End date<input type="date" value={eEnd} onChange={e => setEEnd(e.target.value)}/></label>
          <div className="md-row"><button className="primary" onClick={() => saveEdit(p)} disabled={busy}>Save changes</button><button onClick={() => setEditing(null)}>Cancel</button></div>
        </div>}
      </li>)}</ul>
    </section>

    {canPrescribe && <section className="card" aria-labelledby="md-ap-h"><h3 id="md-ap-h">Schedule an appointment</h3>
      <form onSubmit={schedule} className="md-form">
        <label>Title<input required maxLength={200} value={title} onChange={e => setTitle(e.target.value)}/></label>
        <label>Date and time (Asia/Kolkata)<input type="datetime-local" required value={when} min={nowLocalInput()} onChange={e => setWhen(e.target.value)}/></label>
        <label>Duration (minutes)<input type="number" min={5} max={480} required value={duration} onChange={e => setDuration(e.target.value)}/></label>
        <label>Location<input maxLength={300} value={location} onChange={e => setLocation(e.target.value)}/></label>
        <label>Notes<textarea maxLength={1000} value={notes} onChange={e => setNotes(e.target.value)}/></label>
        <label><input type="checkbox" checked={escort} onChange={e => setEscort(e.target.checked)}/> Needs an escort</label>
        <label>Importance<select value={importance} onChange={e => setImportance(e.target.value)}><option value="MEDIUM">Medium</option><option value="HIGH">High</option><option value="CRITICAL">Critical</option></select></label>
        <button className="primary" disabled={busy}>Schedule appointment</button>
      </form>
    </section>}

    <section className="card" aria-labelledby="md-up-h"><h3 id="md-up-h">Upcoming appointments<span className="cc-count">{upcoming.length}</span></h3>
      {upcoming.length === 0 && <p className="muted">No upcoming appointments.</p>}
      <ul className="md-list">{upcoming.map(a => <li key={a.id} className="md-item">
        <div className="md-head"><strong>{a.title}</strong> <span className="chip">{a.importance}</span>{a.needs_escort && <span className="chip">Escort needed</span>}</div>
        <p className="md-small">{formatAppTime(a.start)}{a.location ? ` · ${a.location}` : ''}</p>
        {a.notes && <p className="md-small">{a.notes}</p>}
        {canPrescribe && <button onClick={() => cancelAppt(a)} disabled={busy}>Cancel appointment</button>}
      </li>)}</ul>
    </section>

    {adherence.data && <section className="card" aria-labelledby="md-ad-h"><h3 id="md-ad-h">Adherence (last {adherence.data.days} days)</h3>
      <p className="md-big">{adherenceLabel(adherence.data.on_time_pct)} <span className="muted">on time overall</span></p>
      {adherence.data.medicines.length === 0 && <p className="muted">No doses were due in this period.</p>}
      <ul className="md-list">{adherence.data.medicines.map(m => <li key={`${m.medicine}-${m.dose}`} className="md-item">
        <div className="md-head"><strong>{m.medicine}</strong> <span className="muted">{m.dose}</span> <span className="md-pct">{adherenceLabel(m.on_time_pct)} on time</span></div>
        <p className="md-small">{m.due} due · {m.on_time} on time · {m.late} late · {m.missed} missed · {m.pending} pending</p>
      </li>)}</ul>
      <p className="md-small muted">{adherence.data.note}</p>
    </section>}
  </div>;
}
