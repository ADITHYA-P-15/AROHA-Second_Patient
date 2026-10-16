import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, MapPin, Clock } from 'lucide-react';
import { api } from './api/client.ts';

type ProofPhoto = { activity_id: string; activity_title: string; mime_type: string; captured_at_text: string; location_text: string;
  location_status: 'AVAILABLE' | 'DENIED' | 'UNAVAILABLE'; verified_at: string | null; photo_url: string };

/**
 * The primary contact's review queue: every unverified proof photo for this patient, with its time and location shown
 * as plain text (not only burned into the image), so nothing depends on the viewer opening or zooming the photo.
 */
export function ProofPhotoReview({ patientId, onDone }: { patientId: string; onDone: (message: string) => void }) {
  const client = useQueryClient();
  const photos = useQuery({ queryKey: ['proof-photos', patientId, 'unverified'], enabled: !!patientId, refetchInterval: 30000,
    queryFn: () => api<{ items: ProofPhoto[] }>(`/api/v1/patients/${patientId}/proof-photos?verified=false`) });
  const items = photos.data?.items ?? [];
  if (!items.length) return null;

  async function verify(activityId: string, title: string) {
    try {
      await api(`/api/v1/activities/${activityId}/proof-photo/verify`, { method: 'POST', body: '{}' });
      onDone(`Verified the proof photo for ${title}.`);
    } catch (err) {
      onDone(err instanceof Error ? err.message : 'Could not verify this photo.');
    } finally {
      await client.invalidateQueries({ queryKey: ['proof-photos', patientId] }).catch(() => undefined);
    }
  }

  return <section className="card pr" aria-labelledby="pr-h">
    <h3 id="pr-h"><ShieldCheck size={17} aria-hidden="true"/>Proof photos to verify<span className="cc-count">{items.length}</span></h3>
    <p className="muted small">Each caretaker's dose photo, with the time and location it was taken. Check them against the plan, then verify.</p>
    <ul className="pr-list">{items.map(p => <li key={p.activity_id} className="pr-item">
      <img src={p.photo_url} alt={`Proof photo for ${p.activity_title}`} loading="lazy"/>
      <div className="pr-details">
        <strong>{p.activity_title}</strong>
        <p className="pr-fact"><Clock size={13} aria-hidden="true"/>{p.captured_at_text}</p>
        <p className={`pr-fact${p.location_status !== 'AVAILABLE' ? ' pr-fact-warn' : ''}`}><MapPin size={13} aria-hidden="true"/>{p.location_text}</p>
        <button className="primary pr-verify" onClick={() => void verify(p.activity_id, p.activity_title)}><ShieldCheck size={15} aria-hidden="true"/>Verify</button>
      </div>
    </li>)}</ul>
  </section>;
}
