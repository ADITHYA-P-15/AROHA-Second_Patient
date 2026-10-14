import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from './api/client.ts';
import { formatAppTime } from './lib/time.ts';
import { delegationLabel, shortDay } from './lib/workload.ts';
import { formatLeadHours, formatSecureBy, horizons, inHorizon, kindLabel, leadRules, levelLabel, severityLabel, standByNotice, tabLabel, trimNote, type HorizonKey } from './lib/forecast.ts';
import { formatPercent } from './lib/cover.ts';

type Person = { id: string; name: string; is_synthetic?: boolean };
type Counts = { tasks: number; gaps: number; unconfirmed: number; single_points: number; covered_with_backup: number; secure_now: number };
type NearMiss = { caregiver_id: string; name: string; status: string; headline: string };
type Finding = {
  id: string; kind: string; severity: string; horizon: string;
  activity: { id: string; title: string; importance: string; scheduled_start: string; delegation_class: string };
  holder: { caregiver_id: string; name: string; assignment_id: string; status: string } | null;
  headline: string; reason: string; secure_by: string; secure_now: boolean; suggestion: string;
  alternatives: unknown[]; near_miss: NearMiss[]; eligible_alternatives: number; backup_requested?: { caregiver_id: string; name: string }[];
  action: { option: string };
};
type Day = { date: string; level: string; tasks: number; gaps: number; single_points: number; unconfirmed: number; reasons: string[] };
type Away = { caregiver_id: string; name: string; tasks: number; message: string };
type Forecast = {
  patient: Person; as_of: string; role_view: string; permissions: { can_act: boolean };
  horizons: Record<HorizonKey, Counts>; findings: Finding[]; days: Day[]; people: Away[]; basis_note: string; lead_times_hours: Record<string, number>;
};
type Metrics = { days: number; identified_before_deadline_pct: number | null; median_lead_hours: number | null; gaps_closed_before_start: number; preventable_uncovered: number; definition: string };

const KEYS = ['forecast', 'cover', 'command-center', 'activities', 'workload'];

function altText(a: unknown) {
  if (typeof a === 'string') return a;
  const o = a as { headline?: string; name?: string } | null;
  return o?.headline ?? o?.name ?? '';
}

export function CoverageForecast() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Person[] }>('/api/v1/patients') });
  const [params] = useSearchParams();
  const [selected, setSelected] = useState(params.get('patient') ?? '');
  const [horizon, setHorizon] = useState<HorizonKey>('3d');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const patient = patients.data?.items.find(x => x.id === selected) ?? patients.data?.items[0];
  const pid = patient?.id;
  const forecast = useQuery({ queryKey: ['forecast', pid], queryFn: () => api<Forecast>(`/api/v1/patients/${pid}/coverage-forecast`), enabled: !!pid, retry: false, refetchInterval: 60000 });
  const metrics = useQuery({ queryKey: ['forecast', pid, 'metrics'], queryFn: () => api<Metrics>(`/api/v1/patients/${pid}/coverage-forecast/metrics?days=30`), enabled: !!pid && !!forecast.data, refetchInterval: 60000 });
  const data = forecast.data;
  const canAct = !!data?.permissions.can_act;

  async function refresh() { await Promise.all(KEYS.map(k => client.invalidateQueries({ queryKey: [k] }))); }
  async function run(work: () => Promise<string | void>) {
    if (busy) return;
    setBusy(true);
    try { const message = await work(); if (message) setNotice(message); }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not complete this action.'); }
    finally { await refresh().catch(() => undefined); setBusy(false); }
  }
  const post = <T,>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });

  function findCover(f: Finding) {
    void run(async () => {
      await post(`/api/v1/activities/${f.activity.id}/cover-requests`, { note: trimNote(f.headline), only_if_uncovered: true });
      navigate(`/cover?patient=${pid}`);
    });
  }
  function requestConfirmation(f: Finding) {
    if (!f.holder) return;
    const h = f.holder;
    void run(async () => { await post(`/api/v1/assignments/${h.assignment_id}/request-confirmation`, {}); return `Asked ${h.name} to confirm ${f.activity.title}.`; });
  }
  function standBy(f: Finding, n: NearMiss) {
    void run(async () => {
      const created = await post<{ id: string }>(`/api/v1/activities/${f.activity.id}/assignments`, { caregiver_id: n.caregiver_id, role: 'BACKUP' });
      await post(`/api/v1/assignments/${created.id}/request-confirmation`, {});
      return standByNotice(n.name);
    });
  }

  if (patients.isLoading) return <section className="card"><div className="skeleton"/></section>;
  const tools = (patients.data?.items.length ?? 0) > 1 && patient
    ? <label className="cc-select">Care circle<select value={patient.id} onChange={e => setSelected(e.target.value)}>{patients.data!.items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label> : null;

  function actions(f: Finding) {
    if (!canAct) return null;
    const opt = f.action.option;
    if (opt === 'FIND_COVER') return <div className="wb-actions"><button className="wb-btn wb-primary" disabled={busy} onClick={() => findCover(f)}>Find cover</button></div>;
    if (opt === 'REQUEST_CONFIRMATION' && f.holder) {
      return f.holder.status === 'PROPOSED'
        ? <div className="wb-actions"><button className="wb-btn wb-primary" disabled={busy} onClick={() => requestConfirmation(f)}>Ask {f.holder.name} to confirm</button></div>
        : <div className="wb-actions"><span className="cf-wait">Waiting for {f.holder.name}</span><button className="wb-btn" onClick={() => navigate('/care-plan')}>Open Care Plan</button></div>;
    }
    if (opt === 'SECURE_BACKUP') {
      if (f.backup_requested?.length) return <p className="muted" role="status">Waiting for {f.backup_requested.map(b => b.name).join(', ')} to confirm as backup.</p>;
      return f.near_miss.length > 0
        ? <div className="wb-actions">{f.near_miss.map(n => <button className="wb-btn wb-primary" key={n.caregiver_id} disabled={busy} onClick={() => standBy(f, n)}>Ask {n.name} to stand by</button>)}</div>
        : <div className="wb-actions"><button className="wb-btn" onClick={() => navigate('/care-network')}>Open Care Network</button></div>;
    }
    return null;
  }

  function renderFinding(f: Finding) {
    const help = [...f.alternatives.map(altText), ...f.near_miss.map(n => n.headline)].filter(Boolean);
    return <article className={`wb-rec cf-card ${f.severity === 'HIGH' ? 'high' : ''}`} key={f.id}>
      <div className="wb-rec-head">
        <span className="wb-badge">{kindLabel(f.kind)}</span>
        <span className="wb-badge wb-class">Severity: {severityLabel(f.severity)}</span>
        <span className="wb-badge wb-class">{delegationLabel(f.activity.delegation_class)}</span>
      </div>
      <h3>{f.activity.title}</h3>
      <p className="muted wb-when">{formatAppTime(f.activity.scheduled_start)}</p>
      <p className="cf-headline">{f.headline}</p>
      <p><span className={`wb-badge ${f.secure_now ? 'wb-s-overloaded' : 'wb-s-balanced'}`}>{f.secure_now ? 'Secure now' : `Secure by ${formatSecureBy(f.secure_by)}`}</span></p>
      {f.suggestion && <p className="wb-small">{f.suggestion}</p>}
      {help.length > 0 && <details><summary>Who else could help</summary><ul>{help.map((t, i) => <li key={i}>{t}</li>)}</ul></details>}
      {actions(f)}
    </article>;
  }

  const counts = data?.horizons[horizon];
  const visible = data ? data.findings.filter(f => inHorizon(f.activity.scheduled_start, data.as_of, horizon)) : [];
  const chips: [string, number][] = counts ? [['Gaps', counts.gaps], ['Unconfirmed', counts.unconfirmed], ['Single points of failure', counts.single_points], ['Secure now', counts.secure_now]] : [];
  const m = metrics.data;
  const metricChips: [string, string][] = m ? [
    ['Found before deadline', formatPercent(m.identified_before_deadline_pct)], ['Median warning time', formatLeadHours(m.median_lead_hours)],
    ['Gaps closed before start', String(m.gaps_closed_before_start)], ['Preventable uncovered', String(m.preventable_uncovered)],
  ] : [];

  return <div className="wb cf">
    <section className="card wb-head">
      <div className="wb-head-top">
        <div><p className="eyebrow">PREDICTIVE PLANNING</p><h1>{patient ? `${patient.name}’s coverage ahead` : 'Coverage ahead'}</h1>{patient?.is_synthetic && <p className="cc-demo">DEMO · SYNTHETIC DATA</p>}</div>
        <div className="wb-tools">{tools}<button className="wb-btn" aria-label="Refresh coverage forecast" onClick={() => void refresh()}><RefreshCw size={16}/> Refresh</button></div>
      </div>
      {data && <p className="cc-basis">{data.basis_note}</p>}
      {data && <div className="cf-tabs" role="group" aria-label="Forecast window">{horizons.map(h => <button key={h.key} className="wb-btn cf-tab" aria-pressed={horizon === h.key} onClick={() => setHorizon(h.key)}>{tabLabel(h.label, data.horizons[h.key])}</button>)}</div>}
      {chips.length > 0 && <div className="cf-chips">{chips.map(([label, value]) => <div className="wb-chip" key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>}
    </section>

    {forecast.isLoading && <section className="card"><div className="skeleton"/></section>}
    {forecast.isError && <section className="card"><div className="cc-empty"><span>—</span><div><strong>The forecast is not available for your role</strong><p>{forecast.error instanceof Error ? forecast.error.message : ''}</p></div></div></section>}

    {data && <>
      <section className="wb-section" aria-labelledby="cf-act"><h2 id="cf-act">Act before the deadline<span className="cc-count">{visible.length}</span></h2>
        {visible.length === 0
          ? <div className="cc-empty"><span>—</span><div><strong>Nothing to secure in this window</strong><p>Based on recorded schedules and availability.</p></div></div>
          : <div className="wb-list">{visible.map(renderFinding)}</div>}
      </section>

      <section className="wb-section" aria-labelledby="cf-days"><h2 id="cf-days">Days</h2>
        <ul className="cf-days">{data.days.map(d => <li key={d.date} className={`cf-day cf-${d.level.toLowerCase()}`}>
          <strong>{shortDay(d.date)}</strong>
          <span className="cf-level">{levelLabel(d.level)}</span>
          <small>{d.tasks} tasks · {d.gaps} gaps · {d.single_points} single · {d.unconfirmed} unconfirmed</small>
          {d.reasons.length > 0 && <details><summary>Why</summary><ul>{d.reasons.map(r => <li key={r}>{r}</li>)}</ul></details>}
        </li>)}</ul>
      </section>

      <section className="wb-section" aria-labelledby="cf-away"><h2 id="cf-away">If someone is away</h2>
        {data.people.length === 0 ? <p className="muted wb-small">No task depends on a single person in this window.</p>
          : <ul className="cf-away">{data.people.map(p => <li key={p.caregiver_id}>{p.message}</li>)}</ul>}
      </section>

      <section className="card" aria-labelledby="cf-metrics"><h2 id="cf-metrics">How early we spot problems</h2>
        {metricChips.length > 0 && <div className="cv-chips">{metricChips.map(([label, value]) => <div className="wb-chip" key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>}
        {m && <p className="cc-basis">{m.definition}</p>}
        <details><summary>Lead-time rules</summary>
          <ul>{leadRules(data.lead_times_hours).map(r => <li key={r}>{r}</li>)}</ul>
          <p className="wb-small">Deadlines that would fall at night move to 20:00 the evening before.</p>
        </details>
      </section>
    </>}
    {notice && <p className="cc-notice" role="status">{notice}</p>}
  </div>;
}
