import { useState } from 'react';
import { Copy, Sparkles, X } from 'lucide-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api, ApiError } from './api/client.ts';
import { groupFacts, reportToText, type ProgressReport as Report } from './lib/report.ts';

const WINDOWS = [14, 30, 60];

/** A draft progress report for one patient. Facts come from the record; the AI only phrases them and cannot add to them. */
export function ProgressReport({ patientId, patientName, aiAvailable, onClose }: { patientId: string; patientName: string; aiAvailable: boolean; onClose: () => void }) {
  const [days, setDays] = useState(30);
  const [copied, setCopied] = useState(false);
  const base = useQuery({ queryKey: ['progress-report', patientId, days], queryFn: () => api<Report>(`/api/v1/patients/${patientId}/progress-report?days=${days}`) });
  const draft = useMutation({ mutationFn: () => api<Report>(`/api/v1/patients/${patientId}/progress-report/draft`, { method: 'POST', body: JSON.stringify({ days }) }) });
  const shown = draft.data && draft.data.days === days ? draft.data : base.data;
  const error = draft.error instanceof ApiError && draft.error.status === 429 ? 'Too many drafts just now. Wait a few minutes.' : draft.isError ? 'Could not write the draft. The recorded facts are shown below.' : '';

  async function copy() {
    if (!shown) return;
    try { await navigator.clipboard.writeText(reportToText(shown, patientName)); setCopied(true); window.setTimeout(() => setCopied(false), 2000); } catch { setCopied(false); }
  }
  return <section className="card pr" aria-label={`Progress report for ${patientName}`}>
    <div className="section-head"><div><p className="eyebrow">PROGRESS REPORT · DRAFT</p><h3>{patientName}</h3></div>
      <div className="cp-filters" role="group" aria-label="Report period">{WINDOWS.map(d => <button key={d} className={`cp-filter${days === d ? ' on' : ''}`} aria-pressed={days === d} onClick={() => setDays(d)}>Last {d} days</button>)}
        <button className="icon-button" aria-label="Close report" onClick={onClose}><X size={18}/></button></div></div>
    {base.isLoading && <div className="skeleton"/>}
    {base.isError && <p className="error" role="alert">Could not load the report.</p>}
    {shown && <>
      <p className="pr-notice" role="note">{shown.notice}</p>
      <div className="pr-summary">
        <div className="pr-actions">
          <button className="primary" disabled={draft.isPending || !aiAvailable} onClick={() => draft.mutate()}><Sparkles size={15} aria-hidden="true"/>{draft.isPending ? 'Writing…' : shown.narrated_by === 'ai' && draft.data ? 'Write again' : 'Write summary with AI'}</button>
          <button className="cp-btn" onClick={() => void copy()}><Copy size={14} aria-hidden="true"/>{copied ? 'Copied' : 'Copy draft'}</button>
        </div>
        {!aiAvailable && <p className="muted small">AI is not configured; the summary below is the recorded facts.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <ul className="pr-sentences">{shown.summary.map(s => <li key={s.text}>{s.text} {s.facts.map(f => <span key={f} className="pr-cite">{f}</span>)}</li>)}</ul>
        <p className="muted small">{shown.narrated_by === 'ai'
          ? `Phrased by AI (${shown.provider ?? 'model'}) and checked against the facts below${shown.dropped ? `; ${shown.dropped} sentence${shown.dropped === 1 ? '' : 's'} left out because they did not match the record` : ''}.`
          : 'These are the recorded facts in plain sentences.'}</p>
      </div>
      {groupFacts(shown.facts).map(g => <div key={g.section} className="pr-group"><h4>{g.label}</h4>
        <ul>{g.facts.map(f => <li key={f.id}><span className="pr-cite">{f.id}</span> {f.text}</li>)}</ul></div>)}
      <ul className="pr-limits muted small">{shown.limits.map(l => <li key={l}>{l}</li>)}</ul>
    </>}
  </section>;
}
