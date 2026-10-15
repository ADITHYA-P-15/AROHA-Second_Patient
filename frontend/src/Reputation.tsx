import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from './api/client.ts';
import { formatAppTime } from './lib/time.ts';
import { SOURCE_ORDER, authorLabel, compositeText, explanation, includedText, sourceLine, stars, starsLabel, type Rateable, type Reputation, type ReviewItem } from './lib/reputation.ts';

/** Whether a feature is on for this deployment (unknown while /meta loads: shown, as the shell does). */
export function useFeature(name: string): boolean {
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{ features?: string[] }>('/api/v1/meta'), staleTime: 60_000 });
  return !meta.data?.features || meta.data.features.includes(name);
}

/** One tap per star. */
export function StarPicker({ value, onPick, label, disabled }: { value: number; onPick: (n: number) => void; label: string; disabled?: boolean }) {
  return <span className="rp-stars" role="radiogroup" aria-label={label}>
    {[1, 2, 3, 4, 5].map(n => <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={starsLabel(n)} disabled={disabled}
      className={n <= value ? 'on' : undefined} onClick={() => onPick(n)}>★</button>)}
  </span>;
}

/** The explained reputation on a caretaker's profile: per-source lines, metric components, the composite and how it is made. */
export function ReputationBlock({ caregiverId, canReport = false }: { caregiverId: string; canReport?: boolean }) {
  const on = useFeature('ratings');
  const rep = useQuery({ queryKey: ['reputation', caregiverId], queryFn: () => api<Reputation>(`/api/v1/caretakers/${caregiverId}/reputation`), enabled: on });
  const reviews = useQuery({ queryKey: ['reviews', caregiverId], queryFn: () => api<{ items: ReviewItem[]; total: number; text_visible: boolean }>(`/api/v1/caretakers/${caregiverId}/reviews?limit=5`), enabled: on });
  const [reported, setReported] = useState<Record<string, string>>({});
  if (!on) return null;
  if (rep.isError) return <p className="muted small">Reputation is not available.</p>;
  const r = rep.data;
  if (!r) return <div className="skeleton"/>;
  const metric = r.sources.metric;
  async function report(id: string) {
    const reason = window.prompt('What is wrong with this review? Moderators will look at it.', '');
    if (reason === null) return;
    try { await api(`/api/v1/reviews/${id}/report`, { method: 'POST', body: JSON.stringify({ reason: reason.trim().slice(0, 300) }) }); setReported(x => ({ ...x, [id]: 'Reported for moderation.' })); }
    catch (err) { setReported(x => ({ ...x, [id]: err instanceof Error ? err.message : 'Could not report.' })); }
  }
  return <section className="rp" aria-label="Reputation">
    <h4 className="rp-head">{compositeText(r)}</h4>
    {r.composite !== null && <div className="rp-bar" aria-hidden="true"><span style={{ width: `${Math.round(r.composite)}%` }}/></div>}
    <p className="muted small">{includedText(r.included)}.</p>
    <ul className="rp-sources">{SOURCE_ORDER.map(key => { const s = r.sources[key]; const starValue = key === 'metric' ? null : (s.stars ?? null); return <li key={key} className={r.included.includes(key) ? undefined : 'rp-off'}>
      <span className="rp-label">{s.label}{r.effective_weights[key] !== undefined && <small> · {r.effective_weights[key]}% of the total</small>}</span>
      <span>{starValue !== null && <span className="rp-star-text" aria-label={starsLabel(starValue)}>{stars(starValue)} </span>}{sourceLine(key, s)}</span>
      {key === 'customers' && s.by_author && s.by_author.PATIENT.count > 0 && <small className="muted">Family: {s.by_author.PRIMARY_CONTACT.count} · patient (counts {r.policy.patient_review_weight === 0.5 ? 'half' : `${r.policy.patient_review_weight}×`}): {s.by_author.PATIENT.count}</small>}
    </li>; })}</ul>
    <details className="rp-metric"><summary>Reliability record details (not the per-task fit score)</summary>
      <ul>{(metric.components ?? []).map(c => <li key={c.key} className={c.included ? undefined : 'rp-off'}><span>{c.label}</span><span>{c.value === null ? '—' : `${Math.round(c.value)}%`}</span><small className="muted">{c.detail}{c.included ? ` · weight ${c.weight}` : ''}</small></li>)}</ul>
    </details>
    <details className="rp-how"><summary>How this is calculated</summary><ul>{explanation(r).map(line => <li key={line}>{line}</li>)}</ul></details>
    {reviews.data && reviews.data.items.length > 0 && <div className="rp-reviews"><h5>Recent reviews <small className="muted">({reviews.data.total})</small></h5>
      <ul>{reviews.data.items.map(v => <li key={v.id}><span className="rp-star-text" aria-label={starsLabel(v.rating)}>{stars(v.rating)}</span> <small className="muted">{authorLabel(v.author_role)} · {formatAppTime(v.created_at, { dateStyle: 'medium', timeStyle: undefined })}{v.edited ? ' · edited' : ''}</small>
        {v.text && <p>{v.text}</p>}
        {canReport && reviews.data!.text_visible && (reported[v.id] ? <small className="muted" role="status">{reported[v.id]}</small> : <button className="text-button rp-report" onClick={() => void report(v.id)}>Report</button>)}</li>)}</ul>
      {!reviews.data.text_visible && <p className="muted small">Review text is shared with families and healthcare professionals.</p>}
    </div>}
  </section>;
}

/** Rate the caretakers on a patient's team: a primary contact or patient writes a review, a professional a doctor rating. */
export function RateCaretakers({ patientId, title = 'Rate caretakers' }: { patientId: string; title?: string }) {
  const on = useFeature('ratings');
  const list = useQuery({ queryKey: ['rateable', patientId], queryFn: () => api<{ items: Rateable[]; author_role: string }>(`/api/v1/patients/${patientId}/rateable-caretakers`), enabled: on && !!patientId });
  if (!on || !list.data || !list.data.items.length) return null;
  const doctor = list.data.author_role === 'PROFESSIONAL';
  return <section className="card rp-rate"><h3>{title}</h3>
    <p className="muted small">{doctor ? 'Your rating is one of four parts of the caretaker’s reputation. It is about care coordination, not a clinical assessment.'
      : 'Optional. Ratings help other families choose; the caretaker sees the stars, never who wrote them.'}</p>
    <ul className="rp-rate-list">{list.data.items.map(item => <RateRow key={item.caregiver_id} item={item} patientId={patientId}/>)}</ul>
  </section>;
}

function RateRow({ item, patientId }: { item: Rateable; patientId: string }) {
  const client = useQueryClient();
  const mine = item.mine;
  const [rating, setRating] = useState(mine?.rating ?? 0);
  const [text, setText] = useState((item.kind === 'doctor' ? mine?.note : mine?.text) ?? '');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const max = item.kind === 'doctor' ? 300 : 500;
  const locked = !!mine && !mine.editable;
  async function save() {
    if (!rating) return;
    setBusy(true); setMessage('');
    const body = item.kind === 'doctor' ? { rating, note: text } : { rating, text };
    try {
      if (mine) await api(item.kind === 'doctor' ? `/api/v1/doctor-ratings/${mine.id}` : `/api/v1/reviews/${mine.id}`, { method: 'PATCH', body: JSON.stringify(body) });
      else await api(item.kind === 'doctor' ? `/api/v1/caretakers/${item.caregiver_id}/doctor-ratings` : `/api/v1/caretakers/${item.caregiver_id}/reviews`, { method: 'POST', body: JSON.stringify({ ...body, patient_id: patientId }) });
      setMessage(mine ? 'Rating updated.' : 'Thanks, your rating is saved.');
      await client.invalidateQueries({ queryKey: ['rateable', patientId] }); await client.invalidateQueries({ queryKey: ['reputation', item.caregiver_id] });
      await client.invalidateQueries({ queryKey: ['command-center'] });
    } catch (err) { setMessage(err instanceof ApiError ? err.message : 'Could not save the rating.'); }
    finally { setBusy(false); }
  }
  return <li className="rp-rate-row">
    <div><strong>{item.name}</strong> <small className="muted">{item.completed_tasks} completed task{item.completed_tasks === 1 ? '' : 's'} for this patient</small></div>
    {!item.eligible && !mine ? <p className="muted small">{item.kind === 'doctor' ? 'You can rate once this caretaker has served this patient.' : `You can rate after ${item.needed_tasks} completed tasks.`}</p> : <>
      <StarPicker value={rating} onPick={setRating} label={`Rate ${item.name}`} disabled={locked || busy}/>
      {locked ? <p className="muted small">You rated {item.name} recently; ratings can be changed for 7 days.</p> : <>
        <textarea aria-label={item.kind === 'doctor' ? 'Note (optional)' : 'Review (optional)'} placeholder={item.kind === 'doctor' ? 'Note (optional)' : 'What went well or could be better? (optional)'}
          value={text} maxLength={max} onChange={e => setText(e.target.value)}/>
        <button className="cp-btn cp-primary" disabled={!rating || busy} onClick={() => void save()}>{mine ? 'Update rating' : 'Save rating'}</button></>}
    </>}
    {message && <p className="small" role="status">{message}</p>}
  </li>;
}

/** The patient's quiet prompt: shown in their own view, never as a notification. */
export function PatientRatePrompt() {
  const on = useFeature('ratings');
  const prompts = useQuery({ queryKey: ['rate-prompts'], queryFn: () => api<{ items: { caregiver_id: string; name: string; patient_id: string }[] }>('/api/v1/reputation/prompts'), enabled: on });
  const [hidden, setHidden] = useState(false);
  if (!on || hidden || !prompts.data?.items.length) return null;
  const first = prompts.data.items[0];
  return <div className="rp-quiet"><RateCaretakers patientId={first.patient_id} title="Would you like to rate your caretaker?"/><button className="text-button" onClick={() => setHidden(true)}>Not now</button></div>;
}

/** One tap to rate from the Command Center item. */
export function QuickRate({ caregiverId, name, onDone }: { caregiverId: string; name: string; onDone: (message: string) => void }) {
  const [rating, setRating] = useState(0);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  async function save(stars: number) {
    setRating(stars); setBusy(true);
    try { await api(`/api/v1/caretakers/${caregiverId}/reviews`, { method: 'POST', body: JSON.stringify({ rating: stars, text }) }); onDone(`Thanks, you rated ${name} ${stars} star${stars === 1 ? '' : 's'}.`); }
    catch (err) { onDone(err instanceof Error ? err.message : 'Could not save the rating.'); }
    finally { setBusy(false); }
  }
  return <div className="rp-quick">
    <input aria-label="Comment (optional)" placeholder="Comment (optional), then tap the stars" maxLength={500} value={text} onChange={e => setText(e.target.value)}/>
    <StarPicker value={rating} onPick={n => void save(n)} label={`Rate ${name}`} disabled={busy}/>
  </div>;
}
