import { FormEvent, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api/client.ts';
import { supportLabel } from './lib/plan.ts';
import { ReputationBlock } from './Reputation.tsx';
import { GENDERS, splitLanguages, type MyDirectoryProfile as Profile, type Sector } from './lib/directory.ts';

const BIO_MAX = 500;

/** A caretaker's own directory listing. Skills and hours are edited in My Availability; this is how families find them. */
export function MyDirectoryProfile() {
  const client = useQueryClient();
  const mine = useQuery({ queryKey: ['directory-me'], queryFn: () => api<Profile>('/api/v1/directory/me') });
  const sectors = useQuery({ queryKey: ['directory-sectors'], queryFn: () => api<{ items: Sector[] }>('/api/v1/directory/sectors'), staleTime: 300_000 });
  const states = (sectors.data?.items ?? []).flatMap(s => s.states).sort();
  const [form, setForm] = useState({ name: '', gender: 'UNDISCLOSED', origin_state: '', origin_city: '', current_state: '', current_city: '', current_district: '', languages: '', bio: '', listed: false });
  const [message, setMessage] = useState(''); const [saving, setSaving] = useState(false);
  useEffect(() => {
    const p = mine.data; if (!p) return;
    setForm({ name: p.name, gender: p.gender, origin_state: p.origin_state, origin_city: p.origin_city, current_state: p.current_state, current_city: p.current_city,
      current_district: p.current_district, languages: p.languages.join(', '), bio: p.bio, listed: p.listed });
  }, [mine.data]);
  const set = (patch: Partial<typeof form>) => setForm(f => ({ ...f, ...patch }));

  async function save(e: FormEvent) {
    e.preventDefault(); setMessage(''); setSaving(true);
    try {
      await api('/api/v1/directory/me', { method: 'PATCH', body: JSON.stringify({ ...form, languages: splitLanguages(form.languages) }) });
      await client.invalidateQueries({ queryKey: ['directory-me'] }); await client.invalidateQueries({ queryKey: ['me'] });
      setMessage(form.listed ? 'Saved. Families can now find you in the directory.' : 'Saved. You are not listed in the directory.');
    } catch (err) { setMessage(err instanceof Error ? err.message : 'Could not save your profile.'); }
    finally { setSaving(false); }
  }
  if (mine.isLoading) return <div className="skeleton"/>;
  if (mine.isError) return <section className="card"><p className="error" role="alert">Could not load your profile.</p></section>;
  const p = mine.data!;
  const stateSelect = (value: string, onChange: (v: string) => void) => <select value={value} onChange={e => onChange(e.target.value)}><option value="">Not given</option>{states.map(s => <option key={s}>{s}</option>)}</select>;
  return <div className="dir dir-me">
    <div className="section-head"><div><p className="eyebrow">CARETAKER DIRECTORY</p><h3>My profile</h3></div></div>
    <p className="muted small">What families see when they look for a caretaker. Your phone number and district are only shown to care teams you are already on.</p>
    {message && <p role="status" className="md-notice">{message}</p>}
    <form className="card pp-form" onSubmit={save}>
      <label className="dir-listed"><input type="checkbox" checked={form.listed} onChange={e => set({ listed: e.target.checked })}/>List me in the caretaker directory</label>
      <label>Name<input value={form.name} onChange={e => set({ name: e.target.value })} required maxLength={160}/></label>
      <label>Gender<select value={form.gender} onChange={e => set({ gender: e.target.value })}>{GENDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <div className="dir-two"><label>Home state{stateSelect(form.origin_state, v => set({ origin_state: v }))}</label><label>Home town<input value={form.origin_city} onChange={e => set({ origin_city: e.target.value })} maxLength={80}/></label></div>
      <div className="dir-two"><label>State you live in now{stateSelect(form.current_state, v => set({ current_state: v }))}</label><label>City<input value={form.current_city} onChange={e => set({ current_city: e.target.value })} maxLength={80}/></label></div>
      <label>Area or district (shown only to your care teams)<input value={form.current_district} onChange={e => set({ current_district: e.target.value })} maxLength={80}/></label>
      <label>Languages you speak (separate with commas)<input value={form.languages} onChange={e => set({ languages: e.target.value })} placeholder="e.g. Kannada, Hindi, English"/></label>
      <label>About you<textarea value={form.bio} maxLength={BIO_MAX} onChange={e => set({ bio: e.target.value })}/><small className="muted">{form.bio.length}/{BIO_MAX}</small></label>
      <p className="muted small">Can help with: {p.capabilities.length ? p.capabilities.map(supportLabel).join(', ') : 'not set yet'}. Change skills and hours in My Availability.</p>
      <button className="primary" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
    </form>
    {p.id && <section className="card"><h3>My reputation</h3><p className="muted small">Families and professionals see this on your profile. You see review text and stars, never who wrote them.</p><ReputationBlock caregiverId={p.id} canReport/></section>}
  </div>;
}
