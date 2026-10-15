import { FormEvent, useEffect, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { newId } from './lib/id.ts';
import { supportLabel } from './lib/plan.ts';
import { usePatientPick } from './PatientPick.tsx';
import { AGENCY_STARS, GENDERS, cardText, cityOptions, type Agency, type DirectoryFilters, type DirectoryOptions, type Sector } from './lib/directory.ts';
import { MultiSelect } from './MultiSelect.tsx';
import { compositeText } from './lib/reputation.ts';
import { ProfileDrawer } from './FindCaretakers.tsx';
import { MAX_COMPARE, TOP_DEFAULT, buildMatchesQuery, compareRows, requestStatusText, roleText, toggleCompare, type HireRequest, type Match, type MatchPage, type MatchSort, type Preferences } from './lib/teambuilder.ts';

const CAPS = ['MEDICATION_ASSIST', 'APPOINTMENT_ESCORT', 'TRANSPORT', 'DAILY_ASSIST', 'MOBILITY_ASSIST', 'PRESCRIPTION_PICKUP', 'LAB_ESCORT', 'SUPPLIES'];
const SECTORS: [string, string][] = [['NORTH', 'North'], ['SOUTH', 'South'], ['EAST', 'East'], ['WEST', 'West']];
type Filters = DirectoryFilters & { state: string[]; city: string[]; language: string[]; capability: string[] };
const BLANK: Filters = { sector: '', agency: '', state: [], city: [], gender: '', language: [], capability: [], min_experience: '', min_agency_rating: '', available_on: '' };

/** Find & build care team: browse the directory with every filter, ranked for this patient the way a backup is ranked
 * (ratings, skills for the patient's needs, place, language, free time), then compare, view a profile and send a hire request. */
export function BuildTeam() {
  const { id: pid, picker } = usePatientPick();
  const client = useQueryClient();
  const [filters, setFilters] = useState<Filters>(BLANK);
  const [sort, setSort] = useState<MatchSort>('best');
  const [top, setTop] = useState(TOP_DEFAULT);
  const query = buildMatchesQuery(filters, sort, top);
  const sectors = useQuery({ queryKey: ['directory-sectors'], queryFn: () => api<{ items: Sector[] }>('/api/v1/directory/sectors'), staleTime: 300_000 });
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
  const refresh = () => Promise.all(['team-matches', 'hire-requests', 'command-center', 'care-preferences'].map(k => client.invalidateQueries({ queryKey: [k] })));
  const set = (patch: Partial<Filters>) => { setFilters(f => ({ ...f, ...patch })); setTop(TOP_DEFAULT); };
  const options = useQuery({ queryKey: ['directory-options'], queryFn: () => api<DirectoryOptions>('/api/v1/directory/options'), staleTime: 300_000 });

  async function saveNeeds(e: FormEvent) {
    e.preventDefault(); setNotice('');
    try {
      await api(`/api/v1/patients/${pid}/care-preferences`, { method: 'PUT', body: JSON.stringify(form) });
      setNotice('Needs saved. The ranking and backup choices now use them.'); await refresh();
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not save.'); }
  }
  async function withdraw(r: HireRequest) {
    try { await api(`/api/v1/hire-requests/${r.id}/withdraw`, { method: 'POST' }); setNotice(`Request to ${r.caretaker.name} withdrawn.`); await refresh(); }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not withdraw.'); }
  }
  if (!pid) return <section className="card">Register a patient first in Care Team.</section>;
  const page = matches.data;
  const items = page?.items ?? [];
  const sectorStates = new Set((sectors.data?.items ?? []).filter(s => !filters.sector || s.code === filters.sector).flatMap(s => s.states));
  const states = (options.data?.states ?? []).filter(s => sectorStates.has(s) || filters.state.includes(s));
  const picked = items.filter(m => compare.includes(m.caregiver_id)).sort((a, b) => compare.indexOf(a.caregiver_id) - compare.indexOf(b.caregiver_id));
  const active = Object.entries(filters).some(([k, v]) => k !== 'sector' && v !== '' && v !== undefined && !(Array.isArray(v) && !v.length));
  return <div className="tb">
    <div className="section-head"><div><p className="eyebrow">FIND &amp; BUILD CARE TEAM · FICTIONAL PEOPLE</p><h3>Choose caretakers for the team</h3></div>{picker}</div>
    <p className="muted small">The best matches come first, ranked like a backup is: ratings, the skills the patient needs, where they live, language and free time. Phone numbers are shared only after a caretaker accepts your request. This is not a medical judgement.</p>
    {notice && <p className="md-notice" role="status">{notice}</p>}

    <details className="card tb-needs" open={!prefs.data?.set}><summary><strong>What the patient needs</strong> <span className="muted small">(used for ranking; must-have skills and the minimum reputation leave others out)</span></summary>
      <form onSubmit={e => void saveNeeds(e)}>
        <div className="tb-grid">
          <MultiSelect label="Languages the patient speaks" searchable value={form.languages} onChange={languages => setForm({ ...form, languages })}
            options={[...new Set([...(options.data?.languages ?? []), ...form.languages])].map(l => ({ value: l, label: l }))}/>
          <label>Patient's city<select value={form.city} onChange={e => setForm({ ...form, city: e.target.value })}><option value="">Not set</option>
            {[...new Set([...(options.data?.cities ?? []).map(c => c.city), ...(form.city ? [form.city] : [])])].sort().map(c => <option key={c} value={c}>{c}</option>)}</select></label>
          <label>Region<select value={form.sector_code ?? ''} onChange={e => setForm({ ...form, sector_code: e.target.value || null })}><option value="">Any</option>{SECTORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label>Minimum reputation (0–100)<input type="number" min={0} max={100} value={form.min_rating ?? ''} onChange={e => setForm({ ...form, min_rating: e.target.value === '' ? null : Number(e.target.value) })}/></label>
        </div>
        <fieldset className="pp-needs"><legend>Must be able to help with</legend>{CAPS.map(c => <label key={c}><input type="checkbox" checked={form.capabilities.includes(c)}
          onChange={e => setForm({ ...form, capabilities: e.target.checked ? [...form.capabilities, c] : form.capabilities.filter(x => x !== c) })}/>{supportLabel(c)}</label>)}</fieldset>
        <button className="primary">Save needs</button>
      </form>
    </details>

    {(requests.data?.items.length ?? 0) > 0 && <section className="card"><h3>Requests</h3><ul className="tb-requests">{(requests.data?.items ?? []).map(r => <li key={r.id} className={`tb-req tb-${r.status.toLowerCase()}`}>
      <div><strong>{r.caretaker.name}</strong> <span className="chip">{roleText(r.intended_role)}</span> <span className="chip">{r.status_text}</span></div>
      <p className="small">{requestStatusText(r)}</p>{r.capacity_note && <p className="small tb-warn">{r.capacity_note}</p>}
      {r.status === 'PENDING' && <button className="cp-btn" onClick={() => void withdraw(r)}>Withdraw</button>}</li>)}</ul></section>}

    <div className="cp-filters dir-tabs" role="tablist" aria-label="Sector">
      {[{ code: '', name: 'All sectors' }, ...(sectors.data?.items ?? [])].map(s => <button key={s.code || 'all'} role="tab" aria-selected={filters.sector === s.code}
        className={`cp-filter${filters.sector === s.code ? ' on' : ''}`} onClick={() => set({ sector: s.code, agency: '', state: [], city: [] })}>{s.name}</button>)}
    </div>
    <form className="dir-filters card" onSubmit={e => e.preventDefault()} aria-label="Filters">
      <label>Agency<select value={filters.agency} onChange={e => set({ agency: e.target.value })}><option value="">Any agency</option>
        {(agencies.data?.items ?? []).map(a => <option key={a.id} value={a.id}>{a.name} · {a.city}</option>)}</select></label>
      <label>Agency rating<select value={String(filters.min_agency_rating ?? '')} onChange={e => set({ min_agency_rating: e.target.value })}>{AGENCY_STARS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <MultiSelect label="States" options={states.map(s => ({ value: s, label: s }))} value={filters.state} searchable
        onChange={state => set({ state, city: filters.city.filter(c => (options.data?.cities ?? []).some(x => x.city === c && (!state.length || state.includes(x.state)))) })}/>
      <MultiSelect label="Cities" options={cityOptions((options.data?.cities ?? []).filter(c => sectorStates.has(c.state)), filters.state, filters.city)} value={filters.city} searchable onChange={city => set({ city })}/>
      <label>Gender<select value={filters.gender} onChange={e => set({ gender: e.target.value })}><option value="">Any</option>{GENDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <MultiSelect label="Languages" options={(options.data?.languages ?? []).map(l => ({ value: l, label: l }))} value={filters.language} searchable onChange={language => set({ language })}/>
      <MultiSelect label="Can help with" options={(options.data?.capabilities ?? CAPS).map(c => ({ value: c, label: supportLabel(c) }))} value={filters.capability} onChange={capability => set({ capability })}/>
      <label>Min. experience (years)<input type="number" min={0} max={60} value={filters.min_experience} onChange={e => set({ min_experience: e.target.value })}/></label>
      <label>Available on<input type="date" value={filters.available_on} onChange={e => set({ available_on: e.target.value })}/></label>
      <label>Order<select value={sort} onChange={e => setSort(e.target.value as MatchSort)}><option value="best">Best match first</option><option value="experience">Most experience</option><option value="name">Name</option></select></label>
      {active && <button type="button" className="cp-btn dir-clear" onClick={() => set({ ...BLANK, sector: filters.sector })}>Clear filters</button>}
    </form>

    {matches.isError && <p className="error" role="alert">Could not load caretakers.</p>}
    {matches.isLoading ? <div className="skeleton"/> : page && <>
      <p className="muted small" role="status">{page.total ? `Top ${items.length} of ${page.total} caretakers who fit` : 'No caretakers fit these filters and needs.'}{page.needs.length ? ` · ranked for: ${page.needs.map(supportLabel).join(', ')}` : ''}</p>
      {items.length > 0 ? <ul className="tb-matches">{items.map((m, i) => { const t = cardText({ ...m, id: m.caregiver_id, gender_label: m.gender_label ?? m.gender, origin_city: m.origin_city ?? '', origin_state: m.origin_state ?? '',
        current_city: m.city, current_state: m.state, agency: m.agency ?? null, is_synthetic: true }); return <li key={m.caregiver_id} className="tb-match">
        <div className="tb-match-head"><span className="tb-rank">{i + 1}</span><strong>{m.name}</strong>{m.reputation && <span className="chip">{compositeText(m.reputation)}</span>}<span className="chip">{m.score} match points</span></div>
        <p className="small muted">{t.lines.join(' · ')}</p>
        <p className="dir-skills">{t.skills.map(s => <span key={s} className="chip">{s}</span>)}</p>
        <ul className="tb-why">{m.why.map(w => <li key={w}>{w}</li>)}</ul>
        {m.capacity_note && <p className="small tb-warn">{m.capacity_note}</p>}
        <div className="tb-actions"><button className="cp-btn" onClick={() => setOpenId(m.caregiver_id)}>View profile</button>
          <label className="tb-check"><input type="checkbox" checked={compare.includes(m.caregiver_id)} disabled={!compare.includes(m.caregiver_id) && compare.length >= MAX_COMPARE}
            onChange={() => setCompare(toggleCompare(compare, m.caregiver_id))}/>Compare</label>
          {m.request_pending ? <span className="chip">Request waiting</span> : <button className="cp-btn cp-primary" onClick={() => setAsking(m)}>Send request</button>}</div>
      </li>; })}</ul> : <section className="card cp-empty"><p>Loosen a filter or a must-have to see more caretakers.</p></section>}
      {page.total > items.length && top < 50 && <div className="dir-pager"><button className="cp-btn" onClick={() => setTop(Math.min(50, top + TOP_DEFAULT))}>Show more</button></div>}
    </>}

    {picked.length > 0 && <section className="card tb-compare"><h3>Compare ({picked.length}/{MAX_COMPARE})</h3><div className="tb-table-wrap"><table><thead><tr><th scope="col"></th>{picked.map(m => <th key={m.caregiver_id} scope="col">{m.name}</th>)}</tr></thead>
      <tbody>{compareRows(picked).map(r => <tr key={r.label}><th scope="row">{r.label}</th>{r.values.map((v, i) => <td key={i}>{v}</td>)}</tr>)}</tbody></table></div>
      <button className="text-button" onClick={() => setCompare([])}>Clear comparison</button></section>}

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
