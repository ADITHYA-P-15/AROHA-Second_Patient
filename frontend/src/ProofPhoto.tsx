import { useEffect, useRef, useState } from 'react';
import { Camera, Check, MapPin, X } from 'lucide-react';
import { getLocation, loadImage, locationLine, watermark, type Geo } from './lib/proofPhoto.ts';

type Phase = 'idle' | 'processing' | 'ready' | 'uploading';

/**
 * Caretaker accountability: a photo of the dose being given is required before the activity can be recorded as done.
 * Captured locally, geotagged (best-effort) and the timestamp + location are burned into the image before upload, so
 * the care team sees the same evidence that was sent — not a photo picked from the gallery after the fact.
 */
export function ProofPhotoCapture({ activityId, title, timeZone, onDone, onCancel }: { activityId: string; title: string; timeZone: string; onDone: (message: string) => void; onCancel: () => void }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');
  const [geo, setGeo] = useState<Geo>({ status: 'UNAVAILABLE' });
  const [capturedAt, setCapturedAt] = useState<Date | null>(null);
  const blobRef = useRef<Blob | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(''); setPhase('processing');
    try {
      const [image, location] = await Promise.all([loadImage(file), getLocation()]);
      const when = new Date();
      const blob = await watermark(image, when, location, timeZone);
      blobRef.current = blob; setGeo(location); setCapturedAt(when);
      setPreviewUrl(URL.createObjectURL(blob)); setPhase('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not use that photo. Try again.'); setPhase('idle');
    }
  }

  async function confirm() {
    if (!blobRef.current || !capturedAt) return;
    setPhase('uploading'); setError('');
    try {
      const params = new URLSearchParams({ captured_at: capturedAt.toISOString(), location_status: geo.status });
      if (geo.latitude != null) params.set('latitude', String(geo.latitude));
      if (geo.longitude != null) params.set('longitude', String(geo.longitude));
      if (geo.accuracyM != null) params.set('accuracy_m', String(geo.accuracyM));
      const uploaded = await fetch(`/api/v1/activities/${activityId}/proof-photo?${params}`, { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'image/jpeg', 'X-Requested-With': 'second-patient' }, body: blobRef.current });
      if (!uploaded.ok) { const body = await uploaded.json().catch(() => ({})); throw new Error(body?.error?.message ?? 'Could not upload the photo'); }
      const done = await fetch(`/api/v1/activities/${activityId}/complete`, { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'second-patient' }, body: '{}' });
      const body = await done.json().catch(() => ({}));
      if (!done.ok) throw new Error(body?.error?.message ?? 'Could not record this as done');
      onDone(body.completed_late ? `${title} recorded as done (late). Photo saved.` : `${title} marked done. Photo saved.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save this.'); setPhase('ready');
    }
  }

  function retake() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    blobRef.current = null; setPreviewUrl(''); setCapturedAt(null); setPhase('idle'); setError('');
    if (inputRef.current) inputRef.current.value = '';
  }

  return <div className="pp" role="group" aria-label={`Proof photo for ${title}`}>
    <p className="pp-why"><Camera size={15} aria-hidden="true"/> A photo is required to record <strong>{title}</strong> as given.</p>

    {(phase === 'idle' || phase === 'processing') && <>
      <input ref={inputRef} id={`pp-file-${activityId}`} className="pp-file-input" type="file" accept="image/*" capture="environment"
             disabled={phase === 'processing'} onChange={e => void onFile(e.target.files?.[0])}/>
      <label htmlFor={`pp-file-${activityId}`} className="primary pp-take">
        <Camera size={16} aria-hidden="true"/>{phase === 'processing' ? 'Preparing photo…' : 'Take photo'}
      </label>
    </>}

    {phase === 'ready' || phase === 'uploading' ? <div className="pp-preview">
      {previewUrl && <img src={previewUrl} alt={`Proof that ${title} was given, with time and location`}/>}
      <p className="md-small pp-meta"><MapPin size={13} aria-hidden="true"/>{locationLine(geo)}</p>
      <div className="md-row">
        <button className="primary" disabled={phase === 'uploading'} onClick={() => void confirm()}><Check size={16} aria-hidden="true"/>{phase === 'uploading' ? 'Saving…' : 'Confirm & mark done'}</button>
        <button disabled={phase === 'uploading'} onClick={retake}>Retake</button>
      </div>
    </div> : null}

    {error && <p role="alert" className="error pp-error">{error}</p>}
    <button className="pp-cancel" disabled={phase === 'uploading'} onClick={onCancel}><X size={14} aria-hidden="true"/>Cancel</button>
  </div>;
}
