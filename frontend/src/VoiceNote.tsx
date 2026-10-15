import { useEffect, useRef, useState } from 'react';
import { Mic, Send, Square, Trash2 } from 'lucide-react';
import { newId } from './lib/id.ts';
import { MAX_SECONDS, assistantLine, clock, languageName, pickMime, type VoiceNoteInfo } from './lib/voice.ts';

type Sent = { id: string; voice_note: VoiceNoteInfo | null };
type Phase = 'idle' | 'recording' | 'review' | 'sending' | 'sent';

/** Patient-side recorder: tap, speak (up to a minute), listen back, send. Works without any AI: the care team can always play it. */
export function VoiceRecorder({ patientId, onSent }: { patientId: string | undefined; onSent?: (incident: Sent) => void }) {
  const [phase, setPhase] = useState<Phase>('idle'); const [seconds, setSeconds] = useState(0); const [error, setError] = useState('');
  const [blob, setBlob] = useState<Blob | null>(null); const [url, setUrl] = useState(''); const [result, setResult] = useState<Sent | null>(null);
  const recorder = useRef<MediaRecorder | null>(null); const chunks = useRef<Blob[]>([]); const timer = useRef<number | null>(null); const key = useRef(newId());
  const supported = typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); recorder.current?.stream.getTracks().forEach(t => t.stop()); }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function start() {
    setError(''); setResult(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMime(t => MediaRecorder.isTypeSupported(t));
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunks.current = [];
      rec.ondataavailable = e => { if (e.data.size > 0) chunks.current.push(e.data); };
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
        const made = new Blob(chunks.current, { type: rec.mimeType || mimeType || 'audio/webm' });
        setBlob(made); setUrl(URL.createObjectURL(made)); setPhase('review');
      };
      recorder.current = rec; rec.start(); setSeconds(0); setPhase('recording');
      timer.current = window.setInterval(() => setSeconds(s => { if (s + 1 >= MAX_SECONDS) rec.state === 'recording' && rec.stop(); return s + 1; }), 1000);
    } catch {
      setError('We could not use the microphone. Allow microphone access in your browser, or type your message instead.');
    }
  }
  const stop = () => { if (recorder.current?.state === 'recording') recorder.current.stop(); };
  function discard() { setBlob(null); setUrl(''); setPhase('idle'); setSeconds(0); key.current = newId(); }

  async function send() {
    if (!blob || !patientId) return;
    setPhase('sending'); setError('');
    try {
      const response = await fetch(`/api/v1/patients/${patientId}/voice-notes`, { method: 'POST', credentials: 'include', body: blob,
        headers: { 'Content-Type': blob.type || 'audio/webm', 'X-Requested-With': 'second-patient', 'Idempotency-Key': key.current } });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.error?.message ?? 'Could not send the voice note');
      setResult(body as Sent); setPhase('sent'); onSent?.(body as Sent); key.current = newId();
    } catch (err) {
      setPhase('review'); setError(err instanceof Error ? err.message : 'Could not reach CareCircle. If it is urgent, call 108/112 or your family.');
    }
  }

  const note = result?.voice_note;
  return <section className="card vn" aria-labelledby="vn-h"><h3 id="vn-h">Say it instead</h3>
    <p className="muted small">Record a short voice note, up to a minute. In any language you like. Your care team can listen to it.</p>
    {!supported && <p className="error">Voice notes are not available in this browser. Please type your message.</p>}
    {supported && phase === 'idle' && <button className="vn-big" onClick={() => void start()} disabled={!patientId}><Mic size={22} aria-hidden="true"/>Record a voice note</button>}
    {phase === 'recording' && <div className="vn-live" role="status"><span className="vn-dot" aria-hidden="true"/>Recording… {clock(seconds)} <span className="muted small">of {clock(MAX_SECONDS)}</span>
      <button className="vn-big vn-stop" onClick={stop}><Square size={20} aria-hidden="true"/>Stop</button></div>}
    {(phase === 'review' || phase === 'sending') && url && <div className="vn-review"><audio controls src={url} aria-label="Your recording"/>
      <div className="md-row"><button className="primary" onClick={() => void send()} disabled={phase === 'sending'}><Send size={16} aria-hidden="true"/>{phase === 'sending' ? 'Sending…' : 'Send to my care team'}</button>
        <button onClick={discard} disabled={phase === 'sending'}><Trash2 size={16} aria-hidden="true"/>Record again</button></div></div>}
    {phase === 'sent' && <div className="vn-done" role="status"><strong>Sent. Your care team has been told.</strong>
      {note?.status === 'TRANSCRIBED' && <p>We heard{note.language ? ` (${languageName(note.language)})` : ''}: “{note.transcript}”</p>}
      {note?.status === 'UNTRANSCRIBED' && <p className="muted">Your voice note will be listened to by a person.</p>}
      <button onClick={discard}>Record another</button></div>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}

/** What the care team sees on a request that came from a voice note. */
export function VoiceNoteBlock({ note }: { note: VoiceNoteInfo }) {
  const line = assistantLine(note);
  return <div className="vn-block">
    <audio controls preload="none" src={note.audio_url} aria-label="Play the voice note"/>
    {note.status === 'TRANSCRIBED' ? <p className="vn-text">“{note.transcript}” {note.language && <span className="chip">{languageName(note.language)}</span>}</p>
      : <p className="vn-text muted">Not transcribed. Please play the recording.</p>}
    {note.low_confidence && note.status === 'TRANSCRIBED' && <p className="vn-warn">The transcript may be wrong. Please play the recording.</p>}
    {line && <p className="vn-assist">{line}</p>}
  </div>;
}
