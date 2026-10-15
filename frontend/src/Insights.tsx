import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Download, Search } from 'lucide-react';
import { api } from './api/client.ts';
import { ProgressReport } from './ProgressReport.tsx';
import { formatAppTime } from './lib/time.ts';
import { BAND_LABEL, bandOf, filterPatients, pctText, teamReputationText, toCsv, trendText, type Band, type BandFilter, type Insights as InsightsData, type PatientInsight } from './lib/insights.ts';

const WINDOWS = [7, 14, 30];
const BAND_ORDER: Band[] = ['follow_up', 'watch', 'on_track', 'no_data'];

function Spark({ values }: { values: (number | null)[] }) {
  const w = 84, h = 22, step = w / Math.max(values.length - 1, 1);
  const points = values.map((v, i) => (v === null ? null : `${(i * step).toFixed(1)},${(h - 2 - (v / 100) * (h - 4)).toFixed(1)}`)).filter(Boolean).join(' ');
  return <svg className="in-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Doses given, last 14 days"><polyline fill="none" strokeWidth="1.6" points={points}/></svg>;
}

function DailyChart({ data }: { data: InsightsData['daily'] }) {
  const w = 720, h = 150, pad = 22, bar = (w - pad) / data.length;
  return <svg className="in-chart" viewBox={`0 0 ${w} ${h + 22}`} role="img" aria-label="Share of doses recorded as given, per day">
    {[0, 50, 100].map(t => <g key={t}><line x1={pad} x2={w} y1={h - (t / 100) * (h - 8)} y2={h - (t / 100) * (h - 8)} className="in-grid"/><text x={0} y={h - (t / 100) * (h - 8) + 4} className="in-axis">{t}</text></g>)}
    {data.map((d, i) => {
      const x = pad + i * bar + 1; const height = d.taken_pct === null ? 0 : (d.taken_pct / 100) * (h - 8);
      const tone = d.taken_pct === null ? 'none' : d.taken_pct >= 90 ? 'ok' : d.taken_pct >= 75 ? 'watch' : 'bad';
      return <g key={d.date}><rect x={x} y={h - height} width={Math.max(bar - 2, 2)} height={height} rx="2" className={`in-bar in-${tone}`}><title>{`${d.date}: ${pctText(d.taken_pct)} given, ${d.missed} missed of ${d.due}`}</title></rect>
        {(data.length <= 14 || i % 5 === 0) && <text x={x + bar / 2} y={h + 16} textAnchor="middle" className="in-axis">{d.date.slice(8)}</text>}</g>;
    })}
  </svg>;
}

function Row({ p, onReport }: { p: PatientInsight; onReport?: () => void }) {
  const band = bandOf(p);
  return <li className={`in-row in-b-${band}`}>
    <div className="in-who"><strong>{p.name}</strong><small>{p.birth_year ? `Born ${p.birth_year}` : ''}{p.care_code ? ` · ${p.care_code}` : ''}</small>{p.team_reputation !== undefined && <small className="in-team">Team: {teamReputationText(p.team_reputation)}</small>}</div>
    <div className="in-pct" aria-label={`Doses given ${pctText(p.taken_pct)}`}><span className="in-meter"><i style={{ width: `${p.taken_pct ?? 0}%` }} className={`in-${band}`}/></span><b>{pctText(p.taken_pct)}</b><small>{p.missed} missed of {p.due}</small></div>
    <div className="in-trend"><Spark values={p.spark}/><span className={`in-t in-t-${p.trend}`}>{trendText(p.trend)}</span></div>
    <div className="in-next">{p.next_appointment ? <><span>{p.next_appointment.title}</span><small>{formatAppTime(p.next_appointment.start, { timeStyle: undefined })}{p.next_appointment.covered ? '' : ' · no escort yet'}</small></> : <small>No appointment booked</small>}</div>
    <div className="in-flags">{p.flags.length ? p.flags.map(f => <span key={f.code} className={`in-flag in-f-${f.code.toLowerCase()}`}>{f.text}</span>) : <span className="muted small">Nothing to follow up</span>}</div>
    <div className="in-links"><Link className="cp-btn" to={`/medicines?patient=${p.id}`}>Medicines</Link><Link className="cp-btn" to={`/care-plan?patient=${p.id}`}>Care plan</Link>{onReport && <button className="cp-btn" onClick={onReport}>Progress report</button>}</div>
  </li>;
}

export function Insights() {
  const [days, setDays] = useState(30); const [query, setQuery] = useState(''); const [band, setBand] = useState<BandFilter>('all'); const [reportFor, setReportFor] = useState<string | null>(null);
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{ features?: string[]; ai_enabled?: boolean }>('/api/v1/meta') });
  const reportOn = !meta.data?.features || meta.data.features.includes('progress_report');
  const insights = useQuery({ queryKey: ['insights', days], queryFn: () => api<InsightsData>(`/api/v1/insights/professional?days=${days}`), refetchInterval: 60000 });
  const data = insights.data;
  const shown = useMemo(() => filterPatients(data?.patients ?? [], query, band), [data, query, band]);
  const low = data?.thresholds.low_taken_pct ?? 75;

  function download() {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([toCsv(data)], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `patients-${data.days}d.csv`; a.click(); URL.revokeObjectURL(url);
  }
  if (insights.isLoading) return <section className="card"><div className="skeleton"/></section>;
  if (insights.isError || !data) return <section className="card"><p className="error">Could not load insights. Try again in a moment.</p></section>;
  if (data.patients.length === 0) return <section className="card"><h3>No patients yet</h3><p className="muted">Find a patient with their CareCircle ID on the Patients page to see insights here.</p></section>;
  const t = data.totals;

  return <div className="in">
    <div className="section-head"><div><p className="eyebrow">INSIGHTS</p><h3>How your {t.patients} patients are doing</h3></div>
      <div className="cp-filters" role="group" aria-label="Period">{WINDOWS.map(d => <button key={d} className={`cp-filter${days === d ? ' on' : ''}`} aria-pressed={days === d} onClick={() => setDays(d)}>Last {d} days</button>)}</div></div>

    <div className="cc-metrics in-kpis">
      <div className="cc-metric"><strong>{pctText(t.taken_pct)}</strong><span>Doses given ({t.decided} recorded)</span></div>
      <div className="cc-metric"><strong className={t.missed ? 'in-warn' : ''}>{t.missed}</strong><span>Missed doses · {t.late} late</span></div>
      <div className="cc-metric"><strong className={t.needs_follow_up ? 'in-warn' : ''}>{t.needs_follow_up}</strong><span>Follow-up suggested</span></div>
      <div className="cc-metric"><strong>{t.appointments_next_7_days}</strong><span>Appointments, next 7 days{t.uncovered_appointments ? ` · ${t.uncovered_appointments} no escort` : ''}</span></div>
      <div className="cc-metric"><strong>{t.open_requests}</strong><span>Open help requests{t.avg_ack_minutes !== null ? ` · ${Math.round(t.avg_ack_minutes)} min to answer` : ''}</span></div>
    </div>

    <div className="in-two">
      <section className="card"><h3>Doses given each day</h3><DailyChart data={data.daily}/>
        <p className="muted small">Share of that day’s doses recorded as given, across all your patients.</p></section>
      <section className="card"><h3>Where patients stand</h3>
        <ul className="in-bands">{BAND_ORDER.map(b => <li key={b}><button className={`cp-filter${band === b ? ' on' : ''}`} onClick={() => setBand(band === b ? 'all' : b)}><i className={`in-dot in-${b}`}/>{BAND_LABEL[b]}<span className="cp-badge in-count">{data.bands[b]}</span></button></li>)}</ul>
        <p className="muted small">Follow-up is suggested at {data.thresholds.missed_recent}+ missed doses in {data.thresholds.recent_days} days, or under {low}% given. Select a band to filter the list.</p></section>
    </div>

    {reportFor && data.patients.some(p => p.id === reportFor) && <ProgressReport key={reportFor} patientId={reportFor} patientName={data.patients.find(p => p.id === reportFor)?.name ?? ''} aiAvailable={!!meta.data?.ai_enabled} onClose={() => setReportFor(null)}/>}

    <section className="card">
      <div className="in-toolbar">
        <h3>Patients</h3>
        <label className="in-search"><Search size={16} aria-hidden="true"/><input type="search" placeholder="Search name or CareCircle ID" value={query} onChange={e => setQuery(e.target.value)} aria-label="Search patients"/></label>
        <button className="cp-filter" onClick={download}><Download size={15} aria-hidden="true"/>Export CSV</button>
      </div>
      {shown.length === 0 ? <p className="muted">No patients match.</p> : <ul className="in-list">{shown.map(p => <Row key={p.id} p={p} onReport={reportOn ? () => setReportFor(p.id) : undefined}/>)}</ul>}
    </section>

    {data.medicines.length > 0 && <section className="card"><h3>Medicines most often missed</h3>
      <ul className="in-meds">{data.medicines.map(m => <li key={m.medicine}><strong>{m.medicine}</strong><span className="muted">{m.patients} patient{m.patients === 1 ? '' : 's'}</span>
        <span className="in-meter"><i style={{ width: `${m.taken_pct ?? 0}%` }} className={`in-${(m.taken_pct ?? 0) >= 90 ? 'on_track' : (m.taken_pct ?? 0) >= low ? 'watch' : 'follow_up'}`}/></span><b>{pctText(m.taken_pct)}</b><small>{m.missed} missed of {m.due}</small></li>)}</ul></section>}
    <p className="muted small">{data.note}</p>
  </div>;
}
