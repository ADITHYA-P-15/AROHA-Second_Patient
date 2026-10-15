import { FormEvent, useEffect, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { RotateCcw } from 'lucide-react';
import { api } from './api/client.ts';
import { newId } from './lib/id.ts';
import { supportLabel } from './lib/plan.ts';
import { usePatientPick } from './PatientPick.tsx';
import { AGENCY_STARS, GENDERS, cityOptions, type Agency, type DirectoryFilters, type DirectoryOptions, type Sector } from './lib/directory.ts';
import { MultiSelect } from './MultiSelect.tsx';
import { ProfileDrawer } from './FindCaretakers.tsx';
import { MAX_COMPARE, TOP_DEFAULT, buildMatchesQuery, compareRows, hasActiveFilters, preferencesPayload, requestStatusText, roleText, toggleCompare, topReasons, type HireRequest, type Match, type MatchPage, type MatchSort, type Preferences } from './lib/teambuilder.ts';

const CAPS = ['MEDICATION_ASSIST', 'APPOINTMENT_ESCORT', 'TRANSPORT', 'DAILY_ASSIST', 'MOBILITY_ASSIST', 'PRESCRIPTION_PICKUP', 'LAB_ESCORT', 'SUPPLIES'];
const SECTORS: [string, string][] = [['NORTH', 'North'], ['SOUTH', 'South'], ['EAST', 'East'], ['WEST', 'West']];
type Filters = DirectoryFilters & { state: string[]; city: string[]; language: string[] };
const BLANK: Filters = { sector: '', agency: '', state: [], city: [], gender: '', language: [], min_experience: '', min_agency_rating: '', available_on: '' };

/** Find & build team: the top five caretakers for this patient, ranked like a backup (ratings, the help the patient needs,
 * place, language, free time). Must-help skills are all required. Nobody joins without a request and their acceptance. */
export function BuildTeam() {
  const { id: pid, picker } = usePatientPick();
  const client = useQueryClient();
  const [filters, setFilters] = useState<Filters>(BLANK);
  const [sort, setSort] = useState<MatchSort>('best');
  const [must, setMust] = useState<string[] | null>(null);  // null: the patient's recorded help and saved must-haves
  const query = buildMatchesQuery(filters, sort, TOP_DEFAULT, must);
  const sectors = useQuery({ queryKey: ['directory-sectors'], queryFn: () => api<{ items: Sector[] }>('/api/v1/directory/sectors'), staleTime: 300_000 });
  const options = useQuery({ queryKey: ['directory-options'], queryFn: () => api<DirectoryOptions>('/api/v1/directory/options'), staleTime: 300_000 });
  const agencies = useQuery({ queryKey: ['directory-agencies', filters.sector], staleTime: 300_000,
    queryFn: () => api<{ items: Agency[] }>(`/api/v1/directory/agencies${filters.sector ? `?sector=${filters.sector}` : ''}`) });
  const prefs = useQuery({ queryKey: ['care-preferences', pid], queryFn: () => api<Preferences>(`/api/v1/patients/${pid}/care-preferences`), enabled: !!pid });
  const matches = useQuery({ queryKey: ['team-matches', pid, query], queryFn: () => api<MatchPage>(`/api/v1/patients/${pid}/team-matches${query}`), enabled: !!pid, placeholderData: keepPreviousData });
  const requests = useQuery({ queryKey: ['hire-requests', pid], queryFn: () => api<{ items: HireRequest[] }>(`/api/v1/patients/${pid}/hire-requests`), enabled: !!pid, refetchInterval: 20000 });
  const [form, setForm] = useState<Preferences>({ languages: [], city: '', sector_code: null, min_rating: null, capabilities: [] });
  const [compare, setCompare] = useState<string[]>([]);
  const [asking, setAsking] = useState<Match | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => { if (prefs.data) setForm(prefs.data); }, [prefs.data]);
  useEffect(() => { setMust(null); setCompare([]); }, [pid]);
  const refresh = () => Promise.all(['team-matches', 'hire-requests', 'command-center', 'care-preferences'].map(k => client.invalidateQueries({ queryKey: [k] })));
  const set = (patch: Partial<Filters>) => setFilters(f => ({ ...f, ...patch }));
  const page = matches.data;
  const mustNow = must ?? page?.must_have ?? [];

  async function saveNeeds(e: FormEvent) {
    e.preventDefault(); setNotice('');
    try {
      await api(`/api/v1/patients/${pid}/care-preferences`, { method: 'PUT', body: JSON.stringify(preferencesPayload(form, mustNow)) });
      setNotice('Saved.'); await refresh();
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not save.'); }
  }
  async function withdraw(r: HireRequest) {
    try { await api(`/api/v1/hire-requests/${r.id}/withdraw`, { method: 'POST' }); setNotice(`Request to ${r.caretaker.name} withdrawn.`); await refresh(); }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not withdraw.'); }
  }
  if (!pid) return <section className="card">Register a patient first in Care Team.</section>;
  const items = page?.items ?? [];
  const sectorStates = new Set((sectors.data?.items ?? []).filter(s => !filters.sector || s.code === filters.sector).flatMap(s => s.states));
  const states = (options.data?.states ?? []).filter(s => sectorStates.has(s) || filters.state.includes(s));
  const picked = items.filter(m => compare.includes(m.caregiver_id)).sort((a, b) => compare.indexOf(a.caregiver_id) - compare.indexOf(b.caregiver_id));
  const toggleMust = (c: string) => setMust(mustNow.includes(c) ? mustNow.filter(x => x !== c) : [...mustNow, c]);
  const pending = (requests.data?.items ?? []).filter(r => r.status === 'PENDING' || r.status === 'ACCEPTED' || r.status === 'DECLINED');

  return <div className="tb tb-clean">
    {picker && <div className="tb-picker">{picker}</div>}
    {notice && <p className="md-notice" role="status">{notice}</p>}

    <section className="card tb-block">
      <h4>Must help with <small className="muted">all required</small></h4>
      <div className="tb-chips">{CAPS.map(c => <button key={c} type="button" className={`cp-filter${mustNow.includes(c) ? ' on' : ''}`} aria-pressed={mustNow.includes(c)} onClick={() => toggleMust(c)}>{supportLabel(c)}</button>)}</div>
      <details className="tb-more"><summary>More about the patient</summary>
        <form className="tb-grid" onSubmit={e => void saveNeeds(e)}>
          <MultiSelect label="Languages" searchable value={form.languages} onChange={languages => setForm({ ...form, languages })}
            options={[...new Set([...(options.data?.languages ?? []), ...form.languages])].map(l => ({ value: l, label: l }))}/>
          <label>City<select value={form.city} onChange={e => setForm({ ...form, city: e.target.value })}><option value="">Any</option>
            {[...new Set([...(options.data?.cities ?? []).map(c => c.city), ...(form.city ? [form.city] : [])])].sort().map(c => <option key={c} value={c}>{c}</option>)}</select></label>
          <label>Region<select value={form.sector_code ?? ''} onChange={e => setForm({ ...form, sector_code: e.target.value || null })}><option value="">Any</option>{SECTORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label>Min. reputation<input type="number" min={0} max={100} placeholder="0–100" value={form.min_rating ?? ''} onChange={e => setForm({ ...form, min_rating: e.target.value === '' ? null : Number(e.target.value) })}/></label>
          <button className="cp-btn cp-primary tb-save">Save as patient's needs</button>
        </form>
      </details>
    </section>

    <section className="card tb-block" aria-label="Filters">
      <div className="tb-filter-head"><h4>Filters</h4>
        <button type="button" className="cp-btn" disabled={!hasActiveFilters(filters, sort)} onClick={() => { setFilters(BLANK); setSort('best'); }}><RotateCcw size={14} aria-hidden="true"/>Reset all filters</button></div>
      <div className="tb-filters">
        <label>Region<select value={filters.sector} onChange={e => set({ sector: e.target.value, agency: '', state: [], city: [] })}><option value="">All</option>{SECTORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <MultiSelect label="States" searchable options={states.map(s => ({ value: s, label: s }))} value={filters.state}
          onChange={state => set({ state, city: filters.city.filter(c => (options.data?.cities ?? []).some(x => x.city === c && (!state.length || state.includes(x.state)))) })}/>
        <MultiSelect label="Cities" searchable options={cityOptions((options.data?.cities ?? []).filter(c => sectorStates.has(c.state)), filters.state, filters.city)} value={filters.city} onChange={city => set({ city })}/>
        <MultiSelect label="Languages" searchable options={(options.data?.languages ?? []).map(l => ({ value: l, label: l }))} value={filters.language} onChange={language => set({ language })}/>
        <label>Gender<select value={filters.gender} onChange={e => set({ gender: e.target.value })}><option value="">Any</option>{GENDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Agency<select value={filters.agency} onChange={e => set({ agency: e.target.value })}><option value="">Any</option>{(agencies.data?.items ?? []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
        <label>Agency rating<select value={String(filters.min_agency_rating ?? '')} onChange={e => set({ min_agency_rating: e.target.value })}>{AGENCY_STARS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Experience<select value={String(filters.min_experience ?? '')} onChange={e => set({ min_experience: e.target.value })}><option value="">Any</option>{[2, 5, 10, 15].map(n => <option key={n} value={n}>{n}+ years</option>)}</select></label>
        <label>Free on<input type="date" value={filters.available_on} onChange={e => set({ available_on: e.target.value })}/></label>
        <label>Order<select value={sort} onChange={e => setSort(e.target.value as MatchSort)}><option value="best">Best match</option><option value="experience">Experience</option><option value="name">Name</option></select></label>
      </div>
    </section>

    {matches.isError && <p className="error" role="alert">Could not load caretakers.</p>}
    <section aria-label="Top matches">
      <h4 className="tb-title">Top {Math.min(TOP_DEFAULT, items.length) || ''} matches {page && <small className="muted">of {page.total}</small>}</h4>
      {matches.isLoading ? <div className="skeleton"/> : items.length ? <ol className="tb-matches">{items.map((m, i) => <li key={m.caregiver_id} className="tb-match">
        <div className="tb-match-head"><span className="tb-rank">{i + 1}</span><strong>{m.name}</strong>
          <span className="tb-score" title="Match points">{m.score} pts</span>{m.composite !== null && <span className="chip">★ {Math.round(m.composite)}</span>}</div>
        <p className="tb-meta">{[m.city, m.agency_name ? `${m.agency_name}${m.agency_rating ? ` ${m.agency_rating.toFixed(1)}★` : ''}` : 'Independent', m.years_experience ? `${m.years_experience} yrs` : 'New', m.languages.slice(0, 3).join(', ')].filter(Boolean).join(' · ')}</p>
        <div className="tb-reasons">{topReasons(m).map(r => <span key={r} className="tb-reason">{r}</span>)}</div>
        {m.capacity_note && <p className="tb-warn small" title={m.capacity_note}>Busy this week · fewer free slots</p>}
        <div className="tb-actions"><button className="text-button" onClick={() => setOpenId(m.caregiver_id)}>Profile</button>
          <label className="tb-check"><input type="checkbox" checked={compare.includes(m.caregiver_id)} disabled={!compare.includes(m.caregiver_id) && compare.length >= MAX_COMPARE}
            onChange={() => setCompare(toggleCompare(compare, m.caregiver_id))}/>Compare</label>
          {m.request_pending ? <span className="chip">Request sent</span> : <button className="cp-btn cp-primary" onClick={() => setAsking(m)}>Send request</button>}</div>
      </li>)}</ol> : <p className="muted">No one fits. Untick a must-help skill or reset the filters.</p>}
    </section>

    {picked.length > 0 && <section className="card tb-compare"><h4>Compare</h4><div className="tb-table-wrap"><table><thead><tr><th scope="col"></th>{picked.map(m => <th key={m.caregiver_id} scope="col">{m.name}</th>)}</tr></thead>
      <tbody>{compareRows(picked).map(r => <tr key={r.label}><th scope="row">{r.label}</th>{r.values.map((v, i) => <td key={i}>{v}</td>)}</tr>)}</tbody></table></div>
      <button className="text-button" onClick={() => setCompare([])}>Clear</button></section>}

    {pending.length > 0 && <section className="card tb-block"><h4>Requests</h4><ul className="tb-requests">{pending.map(r => <li key={r.id} className={`tb-req tb-${r.status.toLowerCase()}`}>
      <div><strong>{r.caretaker.name}</strong> <span className="chip">{roleText(r.intended_role)}</span></div>
      <p className="small muted">{requestStatusText(r)}</p>
      {r.status === 'PENDING' && <button className="text-button" onClick={() => void withdraw(r)}>Withdraw</button>}</li>)}</ul></section>}

    <p className="muted small">Ranked from records and ratings, not a medical judgement. Contact details are shared after a caretaker accepts.</p>
    {openId && <ProfileDrawer id={openId} onClose={() => setOpenId(null)}/>}
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
