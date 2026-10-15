import { FormEvent, useState } from 'react';
import { api } from './api/client.ts';

const MOOD = ['Very low', 'Low', 'Okay', 'Good', 'Very good'];

/** An optional short check-in. It helps the doctor's progress report; it is not a way to ask for help. */
export function CheckInCard({ patientId }: { patientId?: string }) {
  const [pain, setPain] = useState(''); const [mood, setMood] = useState(''); const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false); const [done, setDone] = useState(false); const [error, setError] = useState('');
  const empty = pain === '' && mood === '' && !note.trim();
  async function submit(e: FormEvent) {
    e.preventDefault(); if (!patientId || empty) return;
    setBusy(true); setError(''); setDone(false);
    try {
      await api(`/api/v1/patients/${patientId}/check-ins`, { method: 'POST', body: JSON.stringify({ pain: pain === '' ? null : Number(pain), mood: mood === '' ? null : Number(mood), note: note.trim() }) });
      setDone(true); setPain(''); setMood(''); setNote('');
    } catch { setError('Could not save the check-in. Please try again.'); } finally { setBusy(false); }
  }
  return <form className="card checkin" onSubmit={e => void submit(e)} aria-label="How are you today">
    <p className="eyebrow">OPTIONAL CHECK-IN</p><h3>How are you today?</h3>
    <p className="muted small">This helps your doctor see how you have been over time. It is not a request for help: use the buttons above if you need someone now.</p>
    <label>Pain right now<select value={pain} onChange={e => setPain(e.target.value)}><option value="">Skip</option>{Array.from({ length: 11 }, (_, n) => <option key={n} value={n}>{n === 0 ? '0 (none)' : n === 10 ? '10 (worst)' : n}</option>)}</select></label>
    <label>Mood<select value={mood} onChange={e => setMood(e.target.value)}><option value="">Skip</option>{MOOD.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></label>
    <label>Anything to add (optional)<textarea rows={2} maxLength={300} value={note} onChange={e => setNote(e.target.value)}/></label>
    <button className="primary" disabled={busy || empty || !patientId}>{busy ? 'Saving…' : 'Save check-in'}</button>
    {done && <p role="status" className="ct-notice">Saved. Your care team can see this.</p>}
    {error && <p role="alert" className="error">{error}</p>}
  </form>;
}
