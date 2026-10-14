import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from './api/client.ts';
import { formatAppTime } from './lib/time.ts';
import { barPercent, delegationLabel, shortDay, statusLabel } from './lib/workload.ts';

type Person = { id: string; name: string; is_synthetic?: boolean };
type Breakdown = { label: string; points: number };
type Daily = { date: string; tasks: number; hours: number; limit: number; ratio: number };
type Weekly = { week: string; hours: number; limit_hours: number; ratio: number };
type CaregiverLoad = { caregiver_id: string; name: string; kind: string; is_professional: boolean; status: string; load_score: number; daily: Daily[]; weekly: Weekly[]; this_patient_tasks: number; other_commitments: number; reasons: string[]; flags: { code: string }[] };
type Demand = { date: string; tasks: number; level: 'HIGH' | 'ELEVATED' | 'NORMAL'; reasons: string[] };
type Alternative = { caregiver_id: string; name: string; score: number; score_breakdown: Breakdown[] };
type Recommendation = {
  id: string; kind: 'REDISTRIBUTE' | 'REDUCE_DEPENDENCY' | 'NO_ELIGIBLE_RECEIVER'; priority: string; trigger?: string;
  activity: { id: string; title: string; delegation_class: string; scheduled_start: string; window_start?: string; window_end?: string };
  from?: { caregiver_id: string; name: string } | null; to: { caregiver_id: string; name: string } | null;
  score?: number; score_breakdown?: Breakdown[]; alternatives?: Alternative[]; excluded?: { caregiver_id: string; name: string; reasons: string[] }[]; reasons: string[];
  unresolved_tasks?: { id: string; title: string }[];
  effect?: { date: string; from: { tasks_before: number; tasks_after: number; limit: number }; to: { tasks_before: number; tasks_after: number; limit: number } } | null;
};
type Balance = {
  patient: Person; as_of: string; role_view: 'COORDINATOR' | 'ADMIN' | 'FAMILY'; permissions: { can_apply: boolean }; basis_note: string;
  summary: { overloaded: number; needs_review: number; near_limit: number; high_demand_days: number; recommendations: number };
  caregivers: CaregiverLoad[]; demand: Demand[]; dependency: { message: string }[]; recommendations: Recommendation[];
  delegation_rules: { class: string; label: string; supports: string[]; description: string }[];
};
type Mode = 'REQUEST_CONFIRMATION' | 'CONFIRM_NOW';
const pretty = (code: string) => code.replace(/_/g, ' ').toLowerCase();
const hours = (n: number) => (Math.round(n * 10) / 10).toString();

export function WorkloadBalancer() {
  const client = useQueryClient();
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Person[] }>('/api/v1/patients') });
  const [selected, setSelected] = useState('');
  const [days, setDays] = useState(7);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const patient = patients.data?.items.find(x => x.id === selected) ?? patients.data?.items[0];
  const query = useQuery({ queryKey: ['workload', patient?.id, days], queryFn: () => api<Balance>(`/api/v1/patients/${patient!.id}/workload-balance?days=${days}`), enabled: !!patient, refetchInterval: 30000 });
  const data = query.data;

  async function refresh() {
    await Promise.all([client.invalidateQueries({ queryKey: ['workload'] }), client.invalidateQueries({ queryKey: ['command-center'] }), client.invalidateQueries({ queryKey: ['activities'] })]);
  }
  async function apply(rec: Recommendation, toId: string, toName: string, mode: Mode) {
    if (!patient || !rec.from || busy) return;
    if (mode === 'CONFIRM_NOW' && !window.confirm(`Has ${toName} already agreed to take “${rec.activity.title}”? Choose OK only if they have.`)) return;
    setBusy(true);
    try {
      const result = await api<{ message: string }>(`/api/v1/patients/${patient.id}/workload-balance/apply`, { method: 'POST', body: JSON.stringify({ activity_id: rec.activity.id, from_caregiver_id: rec.from.caregiver_id, to_caregiver_id: toId, mode }) });
      setNotice(result.message);
      await refresh();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not apply this move.');
      await refresh().catch(() => undefined);
    } finally { setBusy(false); }
  }

  if (patients.isLoading) return <section className="card"><div className="skeleton"/></section>;
  if (!patient) return <section className="card"><h2>Workload Balancer</h2><p>No care circle is available for this account.</p></section>;
  // The care-circle picker stays visible on errors so a 403 for one patient never locks the user out of the others.
  const tools = <div className="wb-tools">
    {(patients.data?.items.length ?? 0) > 1 && <label className="cc-select">Care circle<select value={patient.id} onChange={e => setSelected(e.target.value)}>{patients.data!.items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
    <label className="cc-select">Horizon<select value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 14, 28].map(d => <option key={d} value={d}>{d} days</option>)}</select></label>
    <button className="wb-btn" aria-label="Refresh workload" onClick={() => void query.refetch()}><RefreshCw size={16}/> Refresh</button>
  </div>;
  if (query.isError) return <section className="card wb-head"><div className="wb-head-top"><div><p className="eyebrow">RESOURCE PLANNING</p><h1>Workload Balancer</h1></div>{tools}</div><p role="alert" className="error">{query.error instanceof Error ? query.error.message : 'Could not load workload.'}</p></section>;
  if (query.isLoading || !data) return <section className="card"><div className="skeleton"/><p className="muted">Loading caregiver capacity…</p></section>;

  const canApply = data.permissions.can_apply;
  const chips: [string, number][] = [['Overloaded', data.summary.overloaded], ['Needs review', data.summary.needs_review], ['Near limit', data.summary.near_limit], ['High-demand days', data.summary.high_demand_days], ['Suggestions', data.summary.recommendations]];
  const when = (a: Recommendation['activity']) => formatAppTime(a.scheduled_start);

  return <div className="wb">
    <section className="card wb-head">
      <div className="wb-head-top">
        <div><p className="eyebrow">RESOURCE PLANNING</p><h1>Workload Balancer</h1>{patient.is_synthetic && <p className="cc-demo">DEMO · SYNTHETIC DATA</p>}</div>
        {tools}
      </div>
      <p className="cc-basis">{data.basis_note}</p>
      <div className="wb-chips">{chips.map(([label, value]) => <div className="wb-chip" key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
    </section>

    <section className="wb-section" aria-labelledby="wb-moves"><h2 id="wb-moves">Suggested moves<span className="cc-count">{data.recommendations.length}</span></h2>
      {data.recommendations.length > 1 && <p className="muted wb-small">Suggestions build on each other in order. Each move is re-checked against current data when you apply it.</p>}
      {data.recommendations.length === 0 ? <div className="cc-empty"><span>—</span><div><strong>No moves suggested right now</strong><p>Based on recorded assignments, availability and limits in this view.</p></div></div> :
        <div className="wb-list">{data.recommendations.map(rec => <article className={`wb-rec ${rec.priority.toLowerCase()}`} key={rec.id}>
          <div className="wb-rec-head"><span className="wb-badge">{rec.priority} priority</span><span className="wb-badge wb-class">{delegationLabel(rec.activity.delegation_class)}</span></div>
          <h3>{rec.activity.title}</h3>
          <p className="muted wb-when">{when(rec.activity)}</p>
          {rec.kind === 'NO_ELIGIBLE_RECEIVER'
            ? <div className="wb-none"><strong>No one in the network can take this</strong>{rec.from && <p>Currently with {rec.from.name}.{(rec.unresolved_tasks?.length ?? 0) > 1 ? ` Also affects: ${rec.unresolved_tasks!.slice(1).map(t => t.title).join(', ')}.` : ''}</p>}</div>
            : <p className="wb-move"><strong>{rec.from?.name ?? 'Current owner'}</strong> <span aria-hidden="true">→</span><span className="sr-only"> to </span> <strong>{rec.to?.name}</strong></p>}
          <ul className="wb-reasons">{rec.reasons.map(r => <li key={r}>{r}</li>)}</ul>
          {rec.kind !== 'NO_ELIGIBLE_RECEIVER' && rec.score_breakdown && <details><summary>Why this person</summary>
            <p className="wb-small">Fit score {rec.score} (operational ranking, not a medical measure)</p>
            <ul>{rec.score_breakdown.map(b => <li key={b.label}>{b.label}: {b.points > 0 ? '+' : ''}{b.points}</li>)}</ul>
            {!!rec.alternatives?.length && <><p className="wb-small"><strong>Other options</strong></p>{rec.alternatives.map(alt => <div className="wb-alt" key={alt.caregiver_id}><span>{alt.name} · score {alt.score}</span>{canApply && <button className="wb-btn" disabled={busy} onClick={() => void apply(rec, alt.caregiver_id, alt.name, 'REQUEST_CONFIRMATION')}>Use {alt.name} instead</button>}</div>)}</>}
          </details>}
          {!!rec.excluded?.length && <details><summary>Who was ruled out</summary><ul>{rec.excluded.map(x => <li key={x.caregiver_id}><strong>{x.name}</strong>: {x.reasons.join(' ')}</li>)}</ul></details>}
          {canApply && rec.kind !== 'NO_ELIGIBLE_RECEIVER' && rec.to && rec.from && <div className="wb-actions">
            <button className="wb-btn wb-primary" disabled={busy} onClick={() => void apply(rec, rec.to!.caregiver_id, rec.to!.name, 'REQUEST_CONFIRMATION')}>Ask {rec.to.name} to confirm</button>
            <button className="wb-btn" disabled={busy} onClick={() => void apply(rec, rec.to!.caregiver_id, rec.to!.name, 'CONFIRM_NOW')}>Move &amp; confirm now</button>
          </div>}
        </article>)}</div>}
    </section>

    <section className="wb-section" aria-labelledby="wb-load"><h2 id="wb-load">Caregiver load</h2>
      <div className="wb-list">{data.caregivers.map(c => {
        const pct = barPercent(c.load_score);
        const week = c.weekly.reduce((m, w) => w.ratio > m.ratio ? w : m, c.weekly[0]);
        return <article className="wb-cg" key={c.caregiver_id}>
          <div className="wb-cg-head"><div><strong>{c.name}</strong><span className="muted"> · {c.is_professional ? 'Healthcare professional' : pretty(c.kind)}</span></div><span className={`wb-badge wb-s-${c.status.toLowerCase()}`}>{statusLabel(c.status)}</span></div>
          <div className="wb-bar" role="meter" aria-label={`${c.name} load`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-valuetext={`${c.load_score}% of limit`}><i className={`wb-fill wb-s-${c.status.toLowerCase()}`} style={{ width: `${pct}%` }}/></div>
          <p className="wb-small">Load {c.load_score}% of limit · {c.this_patient_tasks} task{c.this_patient_tasks === 1 ? '' : 's'} for this patient{week ? ` · peak week ${hours(week.hours)} of ${hours(week.limit_hours)} h` : ''}{c.other_commitments > 0 ? ` · ${c.other_commitments} other-patient commitment${c.other_commitments === 1 ? '' : 's'}` : ''}</p>
          <ol className="wb-strip" aria-label={`${c.name} tasks per day`}>{c.daily.map(d => <li key={d.date} className={d.tasks > d.limit ? 'over' : d.tasks === d.limit && d.limit > 0 ? 'at' : ''}><span>{shortDay(d.date)}</span><strong>{d.tasks}/{d.limit}</strong>{d.tasks > d.limit && <em>over limit</em>}</li>)}</ol>
          {c.reasons.length > 0 && <ul className="wb-reasons">{c.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
        </article>;
      })}</div>
    </section>

    <section className="wb-section" aria-labelledby="wb-demand"><h2 id="wb-demand">Demand by day</h2>
      <ul className="wb-demand">{data.demand.map(d => <li key={d.date} className={d.level.toLowerCase()}><span>{shortDay(d.date)}</span><strong>{d.tasks} task{d.tasks === 1 ? '' : 's'}</strong>{d.level !== 'NORMAL' ? <span className="wb-badge">{d.level === 'HIGH' ? 'High demand' : 'Elevated demand'}</span> : <span className="muted wb-small">Normal</span>}{d.reasons.map(r => <small key={r}>{r}</small>)}</li>)}</ul>
    </section>

    <section className="wb-section" aria-labelledby="wb-dep"><h2 id="wb-dep">Dependency</h2>
      {data.dependency.length ? <ul className="wb-reasons">{data.dependency.map(d => <li key={d.message}>{d.message}</li>)}</ul> : <p className="muted">No single-person dependencies found in this view.</p>}
    </section>

    <section className="wb-section" aria-labelledby="wb-rules"><h2 id="wb-rules">Delegation rules</h2>
      <dl className="wb-rules">{data.delegation_rules.map(r => <div key={r.class}><dt>{delegationLabel(r.class)}</dt><dd>{r.description} <span className="muted">({r.supports.map(pretty).join(', ')})</span></dd></div>)}</dl>
    </section>
    {notice && <p className="cc-notice" role="status">{notice}</p>}
  </div>;
}
