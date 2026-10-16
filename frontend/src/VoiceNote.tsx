import { useEffect, useRef, useState } from 'react';
import { Check, Mic, RefreshCw, Send, Square, Trash2 } from 'lucide-react';
import { api } from './api/client.ts';
import { newId } from './lib/id.ts';
import { MAX_SECONDS, assistantLine, clock, isStale, languageName, notifyLine, pickMime, routingHeadline, type VoiceNoteInfo, type VoicePreview } from './lib/voice.ts';

type Sent = { id: string; voice_note: VoiceNoteInfo | null };
type Phase = 'idle' | 'recording' | 'checking' | 'review' | 'rechecking' | 'sending' | 'sent';

/**
 * Patient-side recorder. Record, then a preview: what was heard in the spoken language and in English, and who will be told.
 * Only after the sender has looked at the preview and confirmed is anything sent. Works without AI: the care team can always play it.
 */
export function VoiceRecorder({ patientId, onSent }: { patientId: string | undefined; onSent?: (incident: Sent) => void }) {
  const [phase, setPhase] = useState<Phase>('idle'); const [seconds, setSeconds] = useState(0); const [error, setError] = useState('');
  const [url, setUrl] = useState(''); const [draft, setDraft] = useState<VoicePreview | null>(null); const [text, setText] = useState(''); const [checked, setChecked] = useState('');
  const recorder = useRef<MediaRecorder | null>(null); const chunks = useRef<Blob[]>([]); const timer = useRef<number | null>(null); const key = useRef(newId());
  const supported = typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); recorder.current?.stream.getTracks().forEach(t => t.stop()); }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function start() {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMime(t => MediaRecorder.isTypeSupported(t));
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunks.current = [];
      rec.ondataavailable = e => { if (e.data.size > 0) chunks.current.push(e.data); };
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
        void checkRecording(new Blob(chunks.current, { type: rec.mimeType || mimeType || 'audio/webm' }));
      };
      recorder.current = rec; rec.start(); setSeconds(0); setPhase('recording');
      timer.current = window.setInterval(() => setSeconds(s => { if (s + 1 >= MAX_SECONDS) rec.state === 'recording' && rec.stop(); return s + 1; }), 1000);
    } catch {
      setError('We could not use the microphone. Allow microphone access in your browser, or type your message instead.');
    }
  }
  const stop = () => { if (recorder.current?.state === 'recording') recorder.current.stop(); };

  async function checkRecording(blob: Blob) {
    setPhase('checking'); setUrl(URL.createObjectURL(blob));
    try {
      const response = await fetch(`/api/v1/patients/${patientId}/voice-notes/preview`, { method: 'POST', credentials: 'include', body: blob,
        headers: { 'Content-Type': blob.type || 'audio/webm', 'X-Requested-With': 'second-patient' } });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.error?.message ?? 'Could not check the recording');
      const preview = body as VoicePreview;
      setDraft(preview); setText(preview.transcript); setChecked(preview.transcript); setPhase('review');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach AROHA. If it is urgent, call 108/112 or your family.'); setPhase('idle');
    }
  }

  async function recheck() {
    if (!draft) return;
    setPhase('rechecking'); setError('');
    try {
      const next = await api<VoicePreview>(`/api/v1/voice-notes/${draft.id}/check`, { method: 'POST', body: JSON.stringify({ transcript: text }) });
      setDraft(next); setText(next.transcript); setChecked(next.transcript);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not check your change.'); }
    setPhase('review');
  }

  async function discard() {
    const id = draft?.id;
    setDraft(null); setUrl(''); setText(''); setChecked(''); setPhase('idle'); setSeconds(0); setError(''); key.current = newId();
    if (id) await api(`/api/v1/voice-notes/${id}`, { method: 'DELETE' }).catch(() => undefined);
  }

  async function send() {
    if (!draft) return;
    setPhase('sending'); setError('');
    try {
      const body = await api<Sent>(`/api/v1/voice-notes/${draft.id}/send`, { method: 'POST', headers: { 'Idempotency-Key': key.current }, body: JSON.stringify({ transcript: text }) });
      setPhase('sent'); onSent?.(body); key.current = newId();
    } catch (err) {
      setPhase('review'); setError(err instanceof Error ? err.message : 'Could not reach AROHA. If it is urgent, call 108/112 or your family.');
    }
  }

  const stale = isStale(text, checked);
  const spoken = draft?.language ? languageName(draft.language) : '';
  const showEnglish = !!draft && !!draft.english && !(draft.language ?? '').toLowerCase().startsWith('en') && !stale;
  return <section className="card vn" aria-labelledby="vn-h"><h3 id="vn-h">Say it instead</h3>
    <p className="muted small">Record a short voice note, up to a minute, in any language. You will see what we heard before anything is sent.</p>
    {!supported && <p className="error">Voice notes are not available in this browser. Please type your message.</p>}
    {supported && phase === 'idle' && <button className="vn-big" onClick={() => void start()} disabled={!patientId}><Mic size={22} aria-hidden="true"/>Record a voice note</button>}
    {phase === 'recording' && <div className="vn-live" role="status"><span className="vn-dot" aria-hidden="true"/>Recording… {clock(seconds)} <span className="muted small">of {clock(MAX_SECONDS)}</span>
      <button className="vn-big vn-stop" onClick={stop}><Square size={20} aria-hidden="true"/>Stop</button></div>}
    {phase === 'checking' && <p role="status" className="vn-wait">Listening to your recording…</p>}

    {draft && (phase === 'review' || phase === 'rechecking' || phase === 'sending') && <div className="vn-preview">
      {url && <audio controls src={url} aria-label="Your recording"/>}

      <div className="vn-field">
        <label htmlFor="vn-text"><strong>What we heard</strong>{spoken && <span className="chip">{spoken}</span>}</label>
        {!draft.heard && <p className="vn-warn">We could not make out the words. Type what you said below, or send the recording as it is.</p>}
        {draft.heard && draft.low_confidence && <p className="vn-warn">We are not sure we heard this correctly. Please check the words.</p>}
        <textarea id="vn-text" rows={3} maxLength={1000} value={text} onChange={e => setText(e.target.value)} disabled={phase !== 'review'} placeholder="Type what you said, if the words are missing"/>
        <p className="muted small">If anything is wrong, correct it here.</p>
      </div>

      {showEnglish && <div className="vn-field"><strong>In English</strong><p className="vn-english">{draft.english}</p></div>}
      {stale && <div className="vn-stale"><span>You changed the words. Check again to update the English and who will be told.</span>
        <button onClick={() => void recheck()} disabled={phase !== 'review'}><RefreshCw size={15} aria-hidden="true"/>{phase === 'rechecking' ? 'Checking…' : 'Check again'}</button></div>}

      {!stale && <div className={`vn-route${draft.routing.emergency ? ' vn-route-urgent' : ''}`}>
        <strong>Who will be told</strong>
        <p>{routingHeadline(draft.routing)}</p>
        <p className="muted small">{notifyLine(draft.routing)}{draft.routing.no_recipients ? 'No one on the care team can be reached yet.' : ''}</p>
        {draft.routing.applied_level !== null && draft.routing.reason && <p className="vn-assist">{draft.routing.reason}</p>}
        {draft.routing.emergency && <p className="vn-urgent-note">If you are in danger, call 108 or 112 now.</p>}
      </div>}

      <div className="md-row">
        <button className="primary" onClick={() => void send()} disabled={phase !== 'review' || stale}><Send size={16} aria-hidden="true"/>{phase === 'sending' ? 'Sending…' : 'Yes, this is right. Send it'}</button>
        <button onClick={() => void discard()} disabled={phase === 'sending' || phase === 'rechecking'}><Trash2 size={16} aria-hidden="true"/>Record again</button>
      </div>
    </div>}

    {phase === 'sent' && <div className="vn-done" role="status"><strong><Check size={16} aria-hidden="true"/> Sent. Your care team has been told.</strong>
      {draft && <p className="muted small">{routingHeadline(draft.routing)}</p>}
      <button onClick={() => void discard()}>Record another</button></div>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}

/** What the care team sees on a request that came from a voice note. */
export function VoiceNoteBlock({ note }: { note: VoiceNoteInfo }) {
  const line = assistantLine(note);
  const spoken = !!note.language && !note.language.toLowerCase().startsWith('en');
  return <div className="vn-block">
    <audio controls preload="none" src={note.audio_url} aria-label="Play the voice note"/>
    {note.status === 'TRANSCRIBED' ? <>
      <p className="vn-text">“{note.transcript}” {note.language && <span className="chip">{languageName(note.language)}</span>}{note.edited && <span className="chip">Corrected by the sender</span>}</p>
      {spoken && note.english && <p className="vn-text"><span className="muted">In English:</span> “{note.english}”</p>}
    </> : <p className="vn-text muted">Not transcribed. Please play the recording.</p>}
    {note.low_confidence && note.status === 'TRANSCRIBED' && !note.edited && <p className="vn-warn">The transcript may be wrong. Please play the recording.</p>}
    {line && <p className="vn-assist">{line}</p>}
  </div>;
}
