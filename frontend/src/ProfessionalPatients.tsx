import { FormEvent, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, ApiError } from './api/client.ts';

type PatientItem = { id: string; name: string; birth_year?: number; care_code?: string | null };
type Found = { id: string; name: string; birth_year: number; care_code: string; already_on_team: boolean };

function lookupMessage(err: unknown) {
  if (err instanceof ApiError && err.status === 404) return 'No patient matches that CareCircle ID and birth year. Check both and try again.';
  if (err instanceof ApiError && err.status === 429) return 'Too many attempts. Please wait a few minutes and try again.';
  return err instanceof Error ? err.message : 'Could not search right now.';
}

export function ProfessionalPatients() {
  const client = useQueryClient();
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: PatientItem[] }>('/api/v1/patients') });
  const [code, setCode] = useState('');
  const [year, setYear] = useState('');
  const [found, setFound] = useState<Found | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const payload = () => JSON.stringify({ care_code: code.trim().toUpperCase(), birth_year: Number(year) });
  async function lookup(e: FormEvent) {
    e.preventDefault(); setError(''); setNotice(''); setFound(null); setBusy(true);
    try { setFound(await api<Found>('/api/v1/patients/lookup', { method: 'POST', body: payload() })); }
    catch (err) { setError(lookupMessage(err)); } finally { setBusy(false); }
  }
  async function join() {
    setError(''); setBusy(true);
    try {
      const joined = await api<{ name: string }>('/api/v1/patients/join', { method: 'POST', body: payload() });
      setNotice(`${joined.name} is now on your patient list.`); setFound(null); setCode(''); setYear('');
      await client.invalidateQueries({ queryKey: ['patients'] });
    } catch (err) { setError(lookupMessage(err)); } finally { setBusy(false); }
  }
  const items = patients.data?.items ?? [];
  const thisYear = new Date().getFullYear();
  return <div className="ct">
    <section className="card"><p className="eyebrow">MY PATIENTS</p><h2>Patients on your list</h2>
      {patients.isLoading ? <div className="skeleton"/> : items.length ? <ul className="team-list">{items.map(p => <li key={p.id}><span><strong>{p.name}</strong><small>{p.birth_year ? `Born ${p.birth_year}` : ''}{p.care_code ? ` · ${p.care_code}` : ''}</small></span><span className="pp-links"><Link className="cp-btn" to={`/medicines?patient=${p.id}`}>Medicines</Link><Link className="cp-btn" to={`/care-plan?patient=${p.id}`}>Care plan</Link></span></li>)}</ul> : <p className="muted">No patients yet. Find a patient below with their CareCircle ID and birth year.</p>}
    </section>
    <form className="card" onSubmit={e => void lookup(e)}>
      <p className="eyebrow">FIND A PATIENT</p><h3>Find a patient</h3>
      <label>CareCircle ID<input required maxLength={20} placeholder="CC-ABC123" autoComplete="off" value={code} onChange={e => setCode(e.target.value)}/></label>
      <label>Birth year<input type="number" required min={1900} max={thisYear} value={year} onChange={e => setYear(e.target.value)}/></label>
      <button className="primary" disabled={busy}>Find patient</button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="ct-notice">{notice}</p>}
    {found && <section className="card" aria-label="Patient found"><p className="eyebrow">PATIENT FOUND</p><h3>{found.name}</h3><p>Born {found.birth_year} · {found.care_code}</p>
      {found.already_on_team ? <p role="status" className="muted">Already on your list</p> : <button className="primary" disabled={busy} onClick={() => void join()}>Join care team</button>}</section>}
  </div>;
}
