import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from './api/client.ts';
import { formatAppTime } from './lib/time.ts';
import { delegationLabel } from './lib/workload.ts';
import { candidateLabel, formatMinutes, formatPercent, resolutionLabel, signedPoints, splitCandidates } from './lib/cover.ts';

type Person = { id: string; name: string; is_synthetic?: boolean };
type Ref = { caregiver_id: string; name: string };
type Breakdown = { label: string; points: number };
type Candidate = { caregiver_id: string; name: string; kind: string; status: string; eligible: boolean; reasons: string[]; score: number; score_breakdown: Breakdown[]; headline: string; rank?: number };
type CoverActivity = { id: string; title: string; category: string; delegation_class: string; scheduled_start: string; scheduled_end: string };
type CoverRequest = {
  id: string; patient: Person; status: string; reason: string; reason_label: string; reason_note: string;
  replaced: Ref | null; activity: CoverActivity; offered: (Ref & { since: string }) | null; auto_advance: boolean;
  opened_at: string; closed_at: string | null; resolution: string | null; covered_by: Ref | null; minutes_open: number | null;
  ranking?: { summary: string; eligible_count: number; candidates: Candidate[] };
};
type CoverList = { items: CoverRequest[]; role_view: string; permissions: { can_manage: boolean } };
type Metrics = { days: number; open: number; covered: number; median_minutes_to_cover: number | null; resolved_without_manual_search_pct: number | null; definition: string };

const KEYS = ['cover', 'cover-offers', 'command-center', 'activities', 'workload', 'notifications'];
const closedLabel: Record<string, string> = { COVERED: 'Covered', CANCELLED: 'Cancelled', EXPIRED: 'Expired' };

export function CoverRequests() {
  const client = useQueryClient();
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Person[] }>('/api/v1/patients') });
  const [params] = useSearchParams();
  const [selected, setSelected] = useState(params.get('patient') ?? '');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(true);
  const patient = patients.data?.items.find(x => x.id === selected) ?? patients.data?.items[0];
  const pid = patient?.id;
  const mine = useQuery({ queryKey: ['cover-offers', 'mine'], queryFn: () => api<{ items: CoverRequest[] }>('/api/v1/cover-offers/mine'), refetchInterval: 20000 });
  const open = useQuery({ queryKey: ['cover', pid, 'open'], queryFn: () => api<CoverList>(`/api/v1/patients/${pid}/cover-requests?status=open`), enabled: !!pid, retry: false, refetchInterval: 20000 });
  const canView = !!open.data;
  const metrics = useQuery({ queryKey: ['cover', pid, 'metrics'], queryFn: () => api<Metrics>(`/api/v1/patients/${pid}/cover-requests/metrics?days=30`), enabled: !!pid && canView, refetchInterval: 20000 });
  const closed = useQuery({ queryKey: ['cover', pid, 'closed'], queryFn: () => api<CoverList>(`/api/v1/patients/${pid}/cover-requests?status=closed`), enabled: !!pid && canView, refetchInterval: 20000 });
  const canManage = !!open.data?.permissions.can_manage;

  async function refresh() {
    await Promise.all(KEYS.map(k => client.invalidateQueries({ queryKey: [k] })));
  }
  async function act(id: string, verb: string, body: Record<string, unknown>, success: string) {
    if (busy) return;
    setBusy(true);
    try {
      const result = await api<{ message?: string }>(`/api/v1/cover-requests/${id}/${verb}`, { method: 'POST', body: JSON.stringify(body) });
      setNotice(result?.message || success);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not update this request.');
    } finally {
      await refresh().catch(() => undefined);
      setBusy(false);
    }
  }
  const askReason = (text: string) => window.prompt(text, '');
  function decline(r: CoverRequest) { const reason = askReason('Reason (optional)'); if (reason === null) return; void act(r.id, 'decline', { reason: reason.trim() }, 'Recorded. The next best match will be considered.'); }
  function confirmAgreed(r: CoverRequest, c: Ref) {
    if (!window.confirm(`Has ${c.name} agreed to take “${r.activity.title}”? Choose OK only if they have.`)) return;
    void act(r.id, 'accept', { caregiver_id: c.caregiver_id }, `${c.name} is confirmed for ${r.activity.title}.`);
  }
  function cancel(r: CoverRequest) { const reason = askReason('Why are you closing this request?'); if (reason === null) return; void act(r.id, 'cancel', { reason: reason.trim() }, 'Request closed.'); }

  if (patients.isLoading) return <section className="card"><div className="skeleton"/></section>;
  const offers = mine.data?.items ?? [];
  const when = (a: CoverActivity) => formatAppTime(a.scheduled_start);

  const offersSection = offers.length > 0 && <section className="wb-section" aria-labelledby="cv-offers"><h2 id="cv-offers">Offers for you<span className="cc-count">{offers.length}</span></h2>
    <div className="wb-list">{offers.map(o => <article className="cv-offer" key={o.id}>
      <h3>{o.activity.title}</h3>
      <p className="muted wb-when">{o.patient.name} · {when(o.activity)}</p>
      {o.reason_note && <p className="wb-small">{o.reason_note}</p>}
      <div className="cv-big">
        <button className="wb-btn wb-primary" disabled={busy} onClick={() => void act(o.id, 'accept', {}, 'Thank you — you are confirmed for this task.')}>I can do it</button>
        <button className="wb-btn" disabled={busy} onClick={() => decline(o)}>I can’t</button>
      </div>
    </article>)}</div></section>;

  const tools = (patients.data?.items.length ?? 0) > 1 && patient
    ? <label className="cc-select">Care circle<select value={patient.id} onChange={e => setSelected(e.target.value)}>{patients.data!.items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label> : null;

  function renderCandidate(r: CoverRequest, c: Candidate) {
    const isOffered = r.offered?.caregiver_id === c.caregiver_id;
    return <li className={`cv-cand ${c.eligible ? 'ok' : ''}`} key={c.caregiver_id}>
      <div className="cv-cand-head">
        {c.eligible && c.rank !== undefined && <span className="cv-rank" aria-label={`Rank ${c.rank}`}>{c.rank}</span>}
        <p className="cv-headline">{c.headline}</p>
        <span className={`wb-badge ${c.eligible ? 'wb-s-balanced' : 'wb-class'}`}>{candidateLabel(c.status)}</span>
      </div>
      {(c.reasons.length > 1 || c.score_breakdown.length > 0) && <details><summary>Why</summary>
        {c.reasons.length > 1 && <ul>{c.reasons.slice(1).map(x => <li key={x}>{x}</li>)}</ul>}
        {c.score_breakdown.length > 0 && <><p className="wb-small">Fit for this task {c.score} (operational, not a medical measure or the caretaker’s reputation)</p><ul>{c.score_breakdown.map(b => <li key={b.label}>{b.label}: {signedPoints(b.points)}</li>)}</ul></>}
      </details>}
      {canManage && c.eligible && <div className="wb-actions">
        <button className="wb-btn wb-primary" disabled={busy || !!r.offered} onClick={() => void act(r.id, 'offer', { caregiver_id: c.caregiver_id, auto_advance: auto }, `Asked ${c.name}.`)}>{isOffered ? `Asked ${c.name}` : `Ask ${c.name}`}</button>
        <button className="wb-btn" disabled={busy || (!!r.offered && !isOffered)} onClick={() => confirmAgreed(r, c)}>They agreed — confirm</button>
      </div>}
    </li>;
  }

  function renderRequest(r: CoverRequest) {
    const { shown, rest } = splitCandidates(r.ranking?.candidates ?? []);
    return <article className="cv-req" key={r.id}>
      <div className="wb-rec-head"><span className="wb-badge">{r.reason_label}</span><span className="wb-badge wb-class">{delegationLabel(r.activity.delegation_class)}</span></div>
      <h3>{r.activity.title}</h3>
      <p className="muted wb-when">{when(r.activity)}</p>
      {r.reason_note && <p className="wb-small">{r.reason_note}</p>}
      <p className="cv-status">{r.status === 'OFFERED' && r.offered
        ? <>Waiting for <strong>{r.offered.name}</strong> since {formatAppTime(r.offered.since, { dateStyle: undefined })}{r.auto_advance ? ' · auto-asks next match if they say no' : ''}</>
        : <strong>Needs cover</strong>}</p>
      {canManage && r.status === 'OFFERED' && r.offered && <div className="wb-actions">
        <button className="wb-btn wb-primary" disabled={busy} onClick={() => void act(r.id, 'accept', { caregiver_id: r.offered!.caregiver_id }, `${r.offered!.name} is confirmed.`)}>Record yes</button>
        <button className="wb-btn" disabled={busy} onClick={() => decline(r)}>Record no</button>
      </div>}
      {r.ranking && <p className="wb-small">{r.ranking.summary}</p>}
      {shown.length > 0 ? <ul className="cv-cands">{shown.map(c => renderCandidate(r, c))}</ul> : r.ranking && <div className="wb-none"><strong>No one is available to take this right now</strong></div>}
      {rest.length > 0 && <details><summary>Everyone else ({rest.length})</summary><ul className="cv-cands">{rest.map(c => renderCandidate(r, c))}</ul></details>}
      <p className="wb-small">A task counts as covered only after the replacement accepts and is confirmed.</p>
      {canManage && <button className="text-button" disabled={busy} onClick={() => cancel(r)}>Close request</button>}
    </article>;
  }

  const chips: [string, string][] = metrics.data ? [
    ['Open', String(metrics.data.open)], [`Covered (${metrics.data.days} days)`, String(metrics.data.covered)],
    ['Median time to secure', formatMinutes(metrics.data.median_minutes_to_cover)], ['Resolved without manual search', formatPercent(metrics.data.resolved_without_manual_search_pct)],
  ] : [];

  return <div className="wb cv">
    {offersSection}
    {canView && patient && <>
      <section className="card wb-head">
        <div className="wb-head-top">
          <div><p className="eyebrow">REPLACEMENTS</p><h1>Cover requests</h1>{patient.is_synthetic && <p className="cc-demo">DEMO · SYNTHETIC DATA</p>}</div>
          <div className="wb-tools">{tools}<button className="wb-btn" aria-label="Refresh cover requests" onClick={() => void refresh()}><RefreshCw size={16}/> Refresh</button></div>
        </div>
        {chips.length > 0 && <div className="cv-chips">{chips.map(([label, value]) => <div className="wb-chip" key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>}
        {metrics.data && <p className="cc-basis">{metrics.data.definition}</p>}
        {canManage && <label className="cv-auto"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)}/> If they say no, ask the next best match automatically</label>}
      </section>

      <section className="wb-section" aria-labelledby="cv-open"><h2 id="cv-open">Open requests<span className="cc-count">{open.data!.items.length}</span></h2>
        {open.data!.items.length === 0
          ? <div className="cc-empty"><span>—</span><div><strong>No cover needed right now</strong><p>Requests open automatically when someone declines a task or reports an absence.</p></div></div>
          : <div className="wb-list">{open.data!.items.map(renderRequest)}</div>}
      </section>

      <section className="wb-section"><details className="cv-closed"><summary>Recently closed ({closed.data?.items.length ?? 0})</summary>
        {closed.data?.items.length ? <ul className="cv-closed-list">{closed.data.items.map(r => <li key={r.id}>
          <strong>{r.activity.title}</strong> <span className="wb-badge wb-class">{closedLabel[r.status] ?? r.status}</span>
          <small>{when(r.activity)}{r.covered_by ? ` · covered by ${r.covered_by.name}` : ''}{r.resolution ? ` · ${resolutionLabel(r.resolution)}` : ''} · open {formatMinutes(r.minutes_open)}</small>
        </li>)}</ul> : <p className="muted wb-small">Nothing closed recently.</p>}
      </details></section>
    </>}
    {!canView && !open.isLoading && offers.length === 0 && <section className="card"><h2>Cover requests</h2><div className="cc-empty"><span>—</span><div><strong>Nothing waiting for you</strong><p>If someone needs cover and you can help, the offer will appear here.</p></div></div></section>}
    {open.isLoading && <section className="card"><div className="skeleton"/></section>}
    {notice && <p className="cc-notice" role="status">{notice}</p>}
  </div>;
}
