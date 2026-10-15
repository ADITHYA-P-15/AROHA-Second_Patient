import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { api } from './api/client.ts';
import { supportLabel } from './lib/plan.ts';
import { experienceText, place, type CaretakerDetail } from './lib/directory.ts';
import { ReputationBlock } from './Reputation.tsx';

/** A caretaker's directory profile in a side drawer, used by Find & build care team. Contact details only for their own care teams. */
export function ProfileDrawer({ id, onClose }: { id: string; onClose: () => void }) {
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
