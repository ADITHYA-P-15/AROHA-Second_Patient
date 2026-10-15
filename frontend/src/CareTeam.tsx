import { FormEvent, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Check, Copy, UserPlus } from 'lucide-react';
import { api } from './api/client.ts';
import { RateCaretakers } from './Reputation.tsx';

type PatientItem = { id: string; name: string; birth_year?: number; care_code?: string | null };
type Member = { id: string; user_id: string; name: string; email?: string | null; role: string; role_label: string; team_role: string; is_primary_coordinator: boolean };
type CaregiverLite = { id: string; user_id?: string | null };

const errText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

/** Shows the CareCircle ID with a copy button; clipboard can be blocked on plain-HTTP LAN origins, so the code stays selectable. */
export function CareCodeCard({ name, code, patientId }: { name: string; code: string; patientId?: string }) {
  const [copied, setCopied] = useState('');
  const client = useQueryClient();
  async function regenerate() {
    if (!patientId || !window.confirm(`Issue a new CareCircle ID for ${name}? The old one stops working. Professionals already on the team stay.`)) return;
    try { const r = await api<{ care_code: string }>(`/api/v1/patients/${patientId}/care-code/regenerate`, { method: 'POST' }); setCopied(`New ID: ${r.care_code}`); await client.invalidateQueries({ queryKey: ['patients'] }); await client.invalidateQueries({ queryKey: ['patient'] }); } catch (err) { setCopied(err instanceof Error ? err.message : 'Could not issue a new ID.'); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(code); setCopied('Copied.'); } catch { setCopied('Copy is not available here. Select the ID and copy it manually.'); }
  }
  return <section className="card ct-code" aria-label="CareCircle ID">
    <p className="eyebrow">CARECIRCLE ID</p>
    <div className="ct-code-row"><strong className="ct-code-value">{code}</strong><button type="button" onClick={() => void copy()}>{copied === 'Copied.' ? <Check size={16} aria-hidden="true"/> : <Copy size={16} aria-hidden="true"/>} Copy</button></div>
    <p className="muted">Share this ID and the birth year with the hospital so a healthcare professional can find {name}.</p>
    {patientId && <p className="muted small">Shared by mistake? <button type="button" className="text-button" onClick={() => void regenerate()}>Issue a new ID</button> Removing a healthcare professional also issues a new ID.</p>}
    {copied && <p role="status" className="muted">{copied}</p>}
  </section>;
}

/** Primary contact registers a patient. `intro` renders the friendly first-run version. */
export function RegisterPatient({ intro = false, onDone }: { intro?: boolean; onDone?: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState('');
  const [birthYear, setBirthYear] = useState('');
  const [careNotes, setCareNotes] = useState('');
  const [ownLogin, setOwnLogin] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ name: string; care_code: string } | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      const body: Record<string, unknown> = { name: name.trim(), birth_year: Number(birthYear), care_notes: careNotes };
      if (ownLogin) body.patient_account = { email: email.trim(), password };
      const made = await api<{ name: string; care_code: string }>('/api/v1/patients', { method: 'POST', body: JSON.stringify(body) });
      setCreated({ name: made.name, care_code: made.care_code });
      setName(''); setBirthYear(''); setCareNotes(''); setOwnLogin(false); setEmail(''); setPassword('');
      await client.invalidateQueries({ queryKey: ['patients'] });
    } catch (err) { setError(errText(err, 'Could not register the patient.')); } finally { setBusy(false); }
  }
  const year = new Date().getFullYear();
  return <div className="ct">
    {created && <><p role="status" className="ct-notice">{created.name} is registered.</p><CareCodeCard name={created.name} code={created.care_code}/>{onDone && <button type="button" onClick={onDone}>Done</button>}</>}
    {(!created || !intro) && <form className="card" onSubmit={e => void submit(e)}>
      <p className="eyebrow">{intro ? 'WELCOME' : 'NEW PATIENT'}</p>
      <h2>{intro ? 'Register the patient you care for' : 'Register another patient'}</h2>
      {intro && <p className="muted">Add the person you look after. You will get a CareCircle ID to share with the hospital.</p>}
      <label>Patient name<input required maxLength={160} value={name} onChange={e => setName(e.target.value)}/></label>
      <label>Birth year (the hospital needs it to find the patient)<input type="number" required min={1900} max={year} value={birthYear} onChange={e => setBirthYear(e.target.value)}/></label>
      <label>Care notes<textarea rows={3} maxLength={2000} value={careNotes} onChange={e => setCareNotes(e.target.value)}/></label>
      <label><input type="checkbox" checked={ownLogin} onChange={e => setOwnLogin(e.target.checked)}/>Give the patient their own login (optional)</label>
      {ownLogin && <><label>Patient email<input type="email" required value={email} onChange={e => setEmail(e.target.value)}/></label><label>Patient password<input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)}/></label></>}
      {error && <p role="alert" className="error">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? 'Registering…' : 'Register patient'}</button>
    </form>}
  </div>;
}

const groups: { key: string; title: string }[] = [
  { key: 'PRIMARY_CONTACT', title: 'Primary contacts' },
  { key: 'CARETAKER', title: 'Caretakers' },
  { key: 'PROFESSIONAL', title: 'Healthcare professionals' },
  { key: 'PATIENT', title: 'Patient' },
];

export function CareTeam() {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<{ id: string }>('/api/v1/auth/me') });
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: PatientItem[] }>('/api/v1/patients') });
  const [adding, setAdding] = useState(false);
  const items = patients.data?.items ?? [];
  const patient = items.find(p => p.id === params.get('patient')) ?? items[0];
  const pid = patient?.id;
  const team = useQuery({ queryKey: ['team', pid], queryFn: () => api<{ items: Member[] }>(`/api/v1/patients/${pid}/care-team`), enabled: !!pid });
  const caregivers = useQuery({ queryKey: ['caregivers', pid], queryFn: () => api<{ items: CaregiverLite[] }>(`/api/v1/patients/${pid}/caregivers`), enabled: !!pid });
  const [email, setEmail] = useState('');
  const [teamRole, setTeamRole] = useState('CARETAKER');
  const [notice, setNotice] = useState('');
  const [noticeKind, setNoticeKind] = useState<'status' | 'alert'>('status');
  const say = (text: string, kind: 'status' | 'alert' = 'status') => { setNotice(text); setNoticeKind(kind); };
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: ['team', pid] }), client.invalidateQueries({ queryKey: ['caregivers', pid] })]); };
  async function invite(e: FormEvent) {
    e.preventDefault();
    try { await api(`/api/v1/patients/${pid}/care-team`, { method: 'POST', body: JSON.stringify({ email: email.trim(), team_role: teamRole }) }); setEmail(''); say('Added to the care team.'); await refresh(); }
    catch (err) { say(errText(err, 'Could not add that person.'), 'alert'); }
  }
  async function remove(m: Member) {
    if (!window.confirm(`Remove ${m.name} from the care team?`)) return;
    try { await api(`/api/v1/patients/${pid}/care-team/${m.id}`, { method: 'DELETE' }); say(`${m.name} was removed.`); await refresh(); }
    catch (err) { say(errText(err, 'Could not remove that person.'), 'alert'); }
  }
  async function optIn() {
    try { await api(`/api/v1/patients/${pid}/care-team/me/care-profile`, { method: 'POST' }); say('You can now be assigned care activities.'); await refresh(); }
    catch (err) { say(errText(err, 'Could not update your care profile.'), 'alert'); }
  }
  if (adding) return <RegisterPatient onDone={() => setAdding(false)}/>;
  if (patients.isLoading) return <section className="card"><div className="skeleton"/></section>;
  if (!patient) return <RegisterPatient intro/>;
  const hasProfile = !!caregivers.data?.items.some(c => c.user_id === me.data?.id);
  const members = team.data?.items ?? [];
  return <div className="ct">
    <div className="section-head"><div><p className="eyebrow">CARE TEAM</p><h3>Who looks after {patient.name}</h3></div>
      <div className="ct-tools">{items.length > 1 && <label>Patient<select value={patient.id} onChange={e => setParams({ patient: e.target.value })}>{items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}<button type="button" onClick={() => setAdding(true)}>Register another patient</button></div></div>
    {notice && <p role={noticeKind === 'alert' ? 'alert' : 'status'} className={noticeKind === 'alert' ? 'error' : 'ct-notice'}>{notice}</p>}
    <div className="grid">
      {groups.map(g => { const list = members.filter(m => m.role === g.key); return <section className="card" key={g.key}><h3>{g.title}</h3>
        {list.length ? <ul className="team-list">{list.map(m => <li key={m.id}><span><strong>{m.name}</strong><small>{m.email ?? ''}{m.is_primary_coordinator ? ' · lead contact' : ''}</small></span>{g.key !== 'PATIENT' && m.user_id !== me.data?.id && <button type="button" aria-label={`Remove ${m.name}`} onClick={() => void remove(m)}>Remove</button>}</li>)}</ul> : <p className="muted">{team.isLoading ? 'Loading…' : 'No one yet.'}</p>}
      </section>; })}
    </div>
    <form className="card" onSubmit={e => void invite(e)}>
      <h3><UserPlus size={18} aria-hidden="true"/> Invite someone</h3>
      <label>Their email<input type="email" required value={email} onChange={e => setEmail(e.target.value)}/></label>
      <label>Role<select value={teamRole} onChange={e => setTeamRole(e.target.value)}><option value="CARETAKER">Caretaker</option><option value="PRIMARY_CONTACT">Primary contact</option></select></label>
      <p className="muted">They need a CareCircle account first (Sign up → choose their role).</p>
      <button className="primary">Add to care team</button>
    </form>
    <RateCaretakers patientId={patient.id}/>
    <section className="card"><h3>Connect the hospital</h3><p>Healthcare professionals join the care team themselves. They search with the CareCircle ID and the patient’s birth year{patient.birth_year ? ` (${patient.birth_year})` : ''}.</p>
      {patient.care_code ? <CareCodeCard name={patient.name} code={patient.care_code} patientId={patient.id}/> : <p className="muted">The CareCircle ID is shown on the Patient Profile page.</p>}
      <Link to={`/patient-profile?patient=${patient.id}`}>Open patient profile</Link></section>
    {!hasProfile && !caregivers.isLoading && <section className="card"><h3>I also help with care activities</h3><p className="muted">Opt in to be offered medication doses and appointments yourself, alongside coordinating.</p><button type="button" onClick={() => void optIn()}>I also help with care activities</button></section>}
  </div>;
}
