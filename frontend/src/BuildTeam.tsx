import { FormEvent, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { newId } from './lib/id.ts';
import { supportLabel } from './lib/plan.ts';
import { usePatientPick } from './PatientPick.tsx';
import { GENDERS } from './lib/directory.ts';
import { MAX_COMPARE, compareRows, filterMatches, requestStatusText, roleText, toggleCompare, type HireRequest, type Match, type Preferences } from './lib/teambuilder.ts';

const CAPS = ['MEDICATION_ASSIST', 'APPOINTMENT_ESCORT', 'TRANSPORT', 'DAILY_ASSIST', 'MOBILITY_ASSIST', 'PRESCRIPTION_PICKUP', 'LAB_ESCORT', 'SUPPLIES'];
const SECTORS: [string, string][] = [['NORTH', 'North'], ['SOUTH', 'South'], ['EAST', 'East'], ['WEST', 'West']];

/** Build a care team from the directory: needs, ranked matches with a "why", compare up to three, send a hire request, track it. */
export function BuildTeam() {
  const { id: pid, picker } = usePatientPick();
  const client = useQueryClient();
  const prefs = useQuery({ queryKey: ['care-preferences', pid], queryFn: () => api<Preferences>(`/api/v1/patients/${pid}/care-preferences`), enabled: !!pid });
  const matches = useQuery({ queryKey: ['team-matches', pid], queryFn: () => api<{ items: Match[] }>(`/api/v1/patients/${pid}/team-matches?limit=30`), enabled: !!pid });
  const requests = useQuery({ queryKey: ['hire-requests', pid], queryFn: () => api<{ items: HireRequest[] }>(`/api/v1/patients/${pid}/hire-requests`), enabled: !!pid, refetchInterval: 20000 });
  const [form, setForm] = useState<Preferences>({ gender: null, gender_mode: 'SOFT', languages: [], city: '', sector_code: null, min_rating: null, capabilities: [] });
  const [langText, setLangText] = useState('');
  const [text, setText] = useState(''); const [ratedOnly, setRatedOnly] = useState(false);
  const [compare, setCompare] = useState<string[]>([]);
  const [asking, setAsking] = useState<Match | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => { if (prefs.data) { setForm(prefs.data); setLangText(prefs.data.languages.join(', ')); } }, [prefs.data]);
  const refresh = () => Promise.all(['team-matches', 'hire-requests', 'command-center', 'care-preferences'].map(k => client.invalidateQueries({ queryKey: [k] })));

  async function saveNeeds(e: FormEvent) {
    e.preventDefault(); setNotice('');
    try {
      await api(`/api/v1/patients/${pid}/care-preferences`, { method: 'PUT', body: JSON.stringify({ ...form, languages: langText.split(',').map(s => s.trim()).filter(Boolean) }) });
      setNotice('Needs saved. Matches and backup ranking now use them.'); await refresh();
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not save.'); }
  }
  async function withdraw(r: HireRequest) {
    try { await api(`/api/v1/hire-requests/${r.id}/withdraw`, { method: 'POST' }); setNotice(`Request to ${r.caretaker.name} withdrawn.`); await refresh(); }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not withdraw.'); }
  }
  if (!pid) return <section className="card">Register a patient first in Care Team.</section>;
  const items = filterMatches(matches.data?.items ?? [], { text, ratedOnly });
  const picked = (matches.data?.items ?? []).filter(m => compare.includes(m.caregiver_id)).sort((a, b) => compare.indexOf(a.caregiver_id) - compare.indexOf(b.caregiver_id));
  const open = (requests.data?.items ?? []).filter(r => r.status === 'PENDING');
  return <div className="tb">
    <div className="section-head"><div><p className="eyebrow">BUILD CARE TEAM · FICTIONAL PEOPLE</p><h3>Find and invite caretakers</h3></div>{picker}</div>
    <p className="muted small">Requests are answered in the app. Contact details are shared only after a caretaker accepts. Ranking is computed from records and ratings; it is not a medical judgement.</p>
    {notice && <p className="md-notice" role="status">{notice}</p>}

    <form className="card tb-needs" onSubmit={e => void saveNeeds(e)}><h3>What the patient needs</h3>
      <div className="tb-grid">
        <label>Caretaker gender<select value={form.gender ?? ''} onChange={e => setForm({ ...form, gender: e.target.value || null })}><option value="">No preference</option>{GENDERS.filter(([v]) => v !== 'UNDISCLOSED').map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>How strict<select value={form.gender_mode} disabled={!form.gender} onChange={e => setForm({ ...form, gender_mode: e.target.value as 'HARD' | 'SOFT' })}><option value="SOFT">Preferred (ranks higher)</option><option value="HARD">Required (others are filtered out)</option></select></label>
        <label>Languages<input value={langText} onChange={e => setLangText(e.target.value)} placeholder="e.g. Kannada, Hindi"/></label>
        <label>City<input value={form.city} maxLength={80} onChange={e => setForm({ ...form, city: e.target.value })} placeholder="e.g. Bengaluru"/></label>
        <label>Region<select value={form.sector_code ?? ''} onChange={e => setForm({ ...form, sector_code: e.target.value || null })}><option value="">Any</option>{SECTORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Minimum reputation (0–100)<input type="number" min={0} max={100} value={form.min_rating ?? ''} onChange={e => setForm({ ...form, min_rating: e.target.value === '' ? null : Number(e.target.value) })}/></label>
      </div>
      <fieldset className="pp-needs"><legend>Must be able to help with</legend>{CAPS.map(c => <label key={c}><input type="checkbox" checked={form.capabilities.includes(c)}
        onChange={e => setForm({ ...form, capabilities: e.target.checked ? [...form.capabilities, c] : form.capabilities.filter(x => x !== c) })}/>{supportLabel(c)}</label>)}</fieldset>
      <button className="primary">Save needs</button>
    </form>

    {open.length > 0 || (requests.data?.items.length ?? 0) > 0 ? <section className="card"><h3>Requests</h3><ul className="tb-requests">{(requests.data?.items ?? []).map(r => <li key={r.id} className={`tb-req tb-${r.status.toLowerCase()}`}>
      <div><strong>{r.caretaker.name}</strong> <span className="chip">{roleText(r.intended_role)}</span> <span className="chip">{r.status_text}</span></div>
      <p className="small">{requestStatusText(r)}</p>{r.capacity_note && <p className="small tb-warn">{r.capacity_note}</p>}
      {r.status === 'PENDING' && <button className="cp-btn" onClick={() => void withdraw(r)}>Withdraw</button>}</li>)}</ul></section> : null}

    <section className="card"><div className="tb-head"><h3>Matches</h3><div className="tb-tools"><input aria-label="Search matches" placeholder="Name or city" value={text} onChange={e => setText(e.target.value)}/>
      <label className="tb-check"><input type="checkbox" checked={ratedOnly} onChange={e => setRatedOnly(e.target.checked)}/>Rated only</label></div></div>
      {matches.isLoading ? <div className="skeleton"/> : items.length ? <ul className="tb-matches">{items.map((m, i) => <li key={m.caregiver_id} className="tb-match">
        <div className="tb-match-head"><span className="tb-rank">{i + 1}</span><strong>{m.name}</strong><span className="chip">{m.composite === null ? 'Not rated yet' : `Reputation ${Math.round(m.composite)}/100`}</span></div>
        <p className="small muted">{[m.city, m.state].filter(Boolean).join(', ')} · {m.languages.join(', ') || 'languages not given'} · {m.years_experience ? `${m.years_experience} years` : 'new'}</p>
        <ul className="tb-why">{m.why.map(w => <li key={w}>{w}</li>)}</ul>
        <div className="tb-actions"><label className="tb-check"><input type="checkbox" checked={compare.includes(m.caregiver_id)} disabled={!compare.includes(m.caregiver_id) && compare.length >= MAX_COMPARE}
          onChange={() => setCompare(toggleCompare(compare, m.caregiver_id))}/>Compare</label>
          {m.request_pending ? <span className="chip">Request waiting</span> : <button className="cp-btn cp-primary" onClick={() => setAsking(m)}>Send request</button>}</div>
      </li>)}</ul> : <p className="muted">No listed caretaker matches these needs yet. Loosen a requirement to see more.</p>}
    </section>

    {picked.length > 0 && <section className="card tb-compare"><h3>Compare ({picked.length}/{MAX_COMPARE})</h3><div className="tb-table-wrap"><table><thead><tr><th scope="col"></th>{picked.map(m => <th key={m.caregiver_id} scope="col">{m.name}</th>)}</tr></thead>
      <tbody>{compareRows(picked).map(r => <tr key={r.label}><th scope="row">{r.label}</th>{r.values.map((v, i) => <td key={i}>{v}</td>)}</tr>)}</tbody></table></div>
      <button className="text-button" onClick={() => setCompare([])}>Clear comparison</button></section>}

    {asking && <SendRequest pid={pid} match={asking} onClose={() => setAsking(null)} onSent={async message => { setAsking(null); setNotice(message); await refresh(); }}/>}
  </div>;
}

function SendRequest({ pid, match, onClose, onSent }: { pid: string; match: Match; onClose: () => void; onSent: (message: string) => void }) {
  const [role, setRole] = useState<'MAIN' | 'BACKUP'>('BACKUP');
  const [message, setMessage] = useState('');
  const [key] = useState(() => newId());  // one key per draft: a double tap cannot send twice
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function send(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      await api(`/api/v1/patients/${pid}/hire-requests`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ caregiver_id: match.caregiver_id, intended_role: role, message }) });
      onSent(`Request sent to ${match.name}. They will see it in the app; nothing is shared until they accept.`);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not send.'); }
    finally { setBusy(false); }
  }
  return <><div className="scrim dir-scrim" aria-hidden="true" onClick={onClose}/>
    <form className="dir-drawer" role="dialog" aria-modal="true" aria-label={`Send a request to ${match.name}`} onSubmit={e => void send(e)}>
      <div className="section-head"><div><p className="eyebrow">HIRE REQUEST</p><h3>{match.name}</h3></div><button type="button" className="icon-button" aria-label="Close" onClick={onClose}>✕</button></div>
      <label>Role on the team<select value={role} onChange={e => setRole(e.target.value as 'MAIN' | 'BACKUP')}><option value="BACKUP">Backup pool</option><option value="MAIN">Main caretaker</option></select></label>
      <label>Message (optional)<textarea maxLength={300} value={message} onChange={e => setMessage(e.target.value)} placeholder="A short note about the patient's routine"/></label>
      <small className="muted">{message.length}/300 · In-app only. The request expires after 7 days.</small>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</button>
    </form></>;
}

/** The caretaker's side: requests to join care teams, with accept or decline. */
export function HireRequests() {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ['hire-requests', 'mine'], queryFn: () => api<{ items: HireRequest[] }>('/api/v1/hire-requests/mine'), refetchInterval: 20000 });
  const [notice, setNotice] = useState('');
  async function answer(r: HireRequest, verb: 'accept' | 'decline') {
    const reason = verb === 'decline' ? window.prompt('Reason (optional, shared with the family)', '') : '';
    if (reason === null) return;
    try {
      await api(`/api/v1/hire-requests/${r.id}/${verb}`, { method: 'POST', body: JSON.stringify(verb === 'decline' ? { reason } : {}) });
      setNotice(verb === 'accept' ? `You joined ${r.patient.name}'s care team.` : 'Declined. The family was told; nothing was shared.');
      await Promise.all(['hire-requests', 'patients', 'notifications'].map(k => client.invalidateQueries({ queryKey: [k] })));
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not answer.'); }
  }
  const items = list.data?.items ?? [];
  return <div className="tb"><div className="section-head"><div><p className="eyebrow">HIRE REQUESTS</p><h3>{items.filter(r => r.status === 'PENDING').length ? 'Families asking you to join' : 'No requests waiting'}</h3></div></div>
    {notice && <p className="md-notice" role="status">{notice}</p>}
    {list.isLoading ? <div className="skeleton"/> : items.length ? <ul className="tb-requests">{items.map(r => <li key={r.id} className={`card tb-req tb-${r.status.toLowerCase()}`}>
      <div><strong>{r.patient.name}</strong> <span className="chip">{roleText(r.intended_role)}</span> <span className="chip">{r.status_text}</span></div>
      <p className="small muted">From {r.requested_by ?? 'a family member'}{r.message ? `: “${r.message}”` : ''}</p>
      {r.capacity_note && <p className="small tb-warn">{r.capacity_note}</p>}
      {r.status === 'PENDING' && <div className="cp-actions"><button className="cp-btn cp-primary" onClick={() => void answer(r, 'accept')}>Accept</button><button className="cp-btn" onClick={() => void answer(r, 'decline')}>Decline</button></div>}
    </li>)}</ul> : <section className="card cp-empty"><p>When a family sends you a request from the directory, it appears here.</p></section>}
  </div>;
}
