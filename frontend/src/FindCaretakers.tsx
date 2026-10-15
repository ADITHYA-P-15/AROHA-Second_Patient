import { useEffect, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { api } from './api/client.ts';
import { supportLabel } from './lib/plan.ts';
import { compositeText } from './lib/reputation.ts';
import { ReputationBlock } from './Reputation.tsx';
import { GENDERS, PAGE_SIZE, buildDirectoryQuery, cardText, experienceText, pageLabel, place, type Agency, type CaretakerDetail, type DirectoryFilters, type DirectoryPage, type Sector } from './lib/directory.ts';

const CAPABILITIES = ['MEDICATION_ASSIST', 'APPOINTMENT_ESCORT', 'TRANSPORT', 'DAILY_ASSIST', 'MOBILITY_ASSIST', 'PRESCRIPTION_PICKUP', 'LAB_ESCORT', 'SUPPLIES'];
const BLANK: DirectoryFilters = { sector: '', agency: '', state: '', city: '', gender: '', language: '', capability: '', min_experience: '', available_on: '', sort: 'name' };

/** Browse fictional caretakers by sector and agency. Adding someone to a care team still goes through Care Team (invite by email). */
export function FindCaretakers() {
  const [filters, setFilters] = useState<DirectoryFilters>(BLANK);
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const sectors = useQuery({ queryKey: ['directory-sectors'], queryFn: () => api<{ items: Sector[] }>('/api/v1/directory/sectors'), staleTime: 300_000 });
  const agencies = useQuery({ queryKey: ['directory-agencies', filters.sector], staleTime: 300_000,
    queryFn: () => api<{ items: Agency[] }>(`/api/v1/directory/agencies${filters.sector ? `?sector=${filters.sector}` : ''}`) });
  const query = buildDirectoryQuery({ ...filters, limit: PAGE_SIZE, offset });
  const results = useQuery({ queryKey: ['directory', query], queryFn: () => api<DirectoryPage>(`/api/v1/directory/caretakers${query}`), placeholderData: keepPreviousData });
  const set = (patch: DirectoryFilters) => { setFilters(f => ({ ...f, ...patch })); setOffset(0); };
  const states = (sectors.data?.items ?? []).filter(s => !filters.sector || s.code === filters.sector).flatMap(s => s.states).sort();
  const page = results.data;
  const active = Object.entries(filters).some(([k, v]) => k !== 'sort' && k !== 'sector' && v !== '' && v !== undefined);

  return <div className="dir">
    <div className="section-head"><div><p className="eyebrow">CARETAKER DIRECTORY · FICTIONAL PEOPLE</p><h3>Find caretakers</h3></div></div>
    <p className="muted small">Browse caretakers by region and agency. Phone numbers and exact addresses stay hidden until a caretaker is on your care team. To add someone, invite them by email in Care Team.</p>
    <div className="cp-filters dir-tabs" role="tablist" aria-label="Sector">
      {[{ code: '', name: 'All sectors' }, ...(sectors.data?.items ?? [])].map(s => <button key={s.code || 'all'} role="tab" aria-selected={filters.sector === s.code}
        className={`cp-filter${filters.sector === s.code ? ' on' : ''}`} onClick={() => set({ sector: s.code, agency: '', state: '' })}>{s.name}</button>)}
    </div>
    <form className="dir-filters card" onSubmit={e => e.preventDefault()} aria-label="Filters">
      <label>Agency<select value={filters.agency} onChange={e => set({ agency: e.target.value })}><option value="">Any agency</option>
        {(agencies.data?.items ?? []).map(a => <option key={a.id} value={a.id}>{a.name} · {a.city}</option>)}</select></label>
      <label>State<select value={filters.state} onChange={e => set({ state: e.target.value })}><option value="">Any state</option>{states.map(s => <option key={s}>{s}</option>)}</select></label>
      <label>City<input value={filters.city} onChange={e => set({ city: e.target.value })} placeholder="e.g. Pune" maxLength={80}/></label>
      <label>Gender<select value={filters.gender} onChange={e => set({ gender: e.target.value })}><option value="">Any</option>{GENDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <label>Language<input value={filters.language} onChange={e => set({ language: e.target.value })} placeholder="e.g. Tamil" maxLength={40}/></label>
      <label>Can help with<select value={filters.capability} onChange={e => set({ capability: e.target.value })}><option value="">Anything</option>{CAPABILITIES.map(c => <option key={c} value={c}>{supportLabel(c)}</option>)}</select></label>
      <label>Min. experience (years)<input type="number" min={0} max={60} value={filters.min_experience} onChange={e => set({ min_experience: e.target.value })}/></label>
      <label>Available on<input type="date" value={filters.available_on} onChange={e => set({ available_on: e.target.value })}/></label>
      <label>Sort by<select value={filters.sort} onChange={e => set({ sort: e.target.value as 'name' | 'experience' })}><option value="name">Name</option><option value="experience">Most experience</option></select></label>
      {active && <button type="button" className="cp-btn dir-clear" onClick={() => set({ ...BLANK, sector: filters.sector })}>Clear filters</button>}
    </form>
    {results.isError && <p className="error" role="alert">Could not load the directory.</p>}
    {results.isLoading ? <div className="skeleton"/> : page && <>
      <p className="muted small" role="status">{pageLabel(page, page.items.length)}</p>
      {page.items.length ? <ul className="dir-grid">{page.items.map(c => { const t = cardText(c); return <li key={c.id} className="dir-card">
        <button className="dir-open" onClick={() => setOpenId(c.id)} aria-label={`Open profile of ${t.title}`}>
          <span className="dir-name">{t.title}</span>
          {c.reputation && <span className={`dir-rep${c.reputation.composite === null ? ' none' : ''}`}>{compositeText(c.reputation)}</span>}
          {t.lines.map(line => <span key={line} className="dir-line">{line}</span>)}
          <span className="dir-skills">{t.skills.map(s => <span key={s} className="chip">{s}</span>)}</span>
        </button></li>; })}</ul>
        : <section className="card cp-empty"><p>No caretakers match these filters. Try a wider sector or fewer filters.</p></section>}
      {page.total > PAGE_SIZE && <div className="dir-pager">
        <button className="cp-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
        <button className="cp-btn" disabled={offset + PAGE_SIZE >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div>}
    </>}
    {openId && <ProfileDrawer id={openId} onClose={() => setOpenId(null)}/>}
  </div>;
}

function ProfileDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const profile = useQuery({ queryKey: ['directory-profile', id], queryFn: () => api<CaretakerDetail>(`/api/v1/directory/caretakers/${id}`) });
  useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  const p = profile.data;
  return <><div className="scrim dir-scrim" aria-hidden="true" onClick={onClose}/>
    <aside className="dir-drawer" role="dialog" aria-modal="true" aria-label="Caretaker profile">
      <div className="section-head"><div><p className="eyebrow">CARETAKER PROFILE{p?.is_synthetic ? ' · FICTIONAL' : ''}</p><h3>{p?.name ?? 'Loading…'}</h3></div>
        <button className="icon-button" aria-label="Close profile" onClick={onClose} autoFocus><X size={18}/></button></div>
      {profile.isError && <p className="error" role="alert">This caretaker is not in the directory.</p>}
      {p && <>
        {p.bio && <p>{p.bio}</p>}
        <dl className="dir-facts">
          <dt>Gender</dt><dd>{p.gender_label}</dd>
          <dt>From</dt><dd>{place(p.origin_city, p.origin_state) || 'Not given'}</dd>
          <dt>Lives in</dt><dd>{place(p.current_city, p.current_state) || 'Not given'}{p.private?.current_district ? ` · ${p.private.current_district}` : ''}</dd>
          <dt>Agency</dt><dd>{p.agency?.name ?? 'Independent'}</dd>
          <dt>Languages</dt><dd>{p.languages.join(', ') || 'Not given'}</dd>
          <dt>Experience</dt><dd>{experienceText(p.years_experience)}</dd>
          <dt>Takes on</dt><dd>Up to {p.max_activities_per_day} tasks a day, {p.max_hours_per_week} hours a week</dd>
        </dl>
        <p className="dir-skills">{p.capabilities.map(c => <span key={c} className="chip">{supportLabel(c)}</span>)}</p>
        {p.private
          ? <div className="md-notice"><strong>On your care team.</strong> Phone: {p.private.phone || 'not given'}{p.private.notes ? <><br/>{p.private.notes}</> : null}</div>
          : <p className="muted small">Contact details are shared once this caretaker is on your care team.</p>}
        <ReputationBlock caregiverId={p.id} canReport/>
      </>}
    </aside></>;
}
