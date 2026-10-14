import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Clock3, RefreshCw, Send } from 'lucide-react';
import { api } from './api/client.ts';

type Person = { id: string; name: string; is_synthetic?: boolean };
type Action = { id: string; kind: string; title: string; reason: string; reasons: string[]; severity: string; status: string; age_seconds: number; related_activity_ids: string[]; suggested_actions: { option: string; activity_id?: string; assignment_id?: string; incident_id?: string }[] };
type Block = { kind: string; title: string; daypart?: string; start?: string; end?: string; activity_id?: string; status?: string; activities?: { activity_id: string; title: string; start: string; end: string; status: string }[] };
type Brief = { id: string; kind: string; status: string; rendered_text: string; auto_generated: boolean; to_user_id?: string | null } | null;
type Center = { role_view: string; patient: Person; as_of: string; basis_note: string; summary: Record<string, number>; needs_now: Action[]; at_risk: Action[]; decisions_waiting: Action[]; pending_actions: Action[]; handled: Action[]; todays_plan: { blocks: Block[]; timeline: Block[] }; load_today: { hours: number; tasks: number; next_free_window: { start: string; end: string } | null }; briefs: { morning: Brief; handover: Brief }; setup_hints: string[] };
const today = () => new Intl.DateTimeFormat('en-CA').format(new Date());
const time = (value?: string) => value ? new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value)) : '';
const age = (seconds: number) => seconds < 3600 ? `${Math.max(1, Math.floor(seconds / 60))}m` : `${Math.floor(seconds / 3600)}h`;

export function CommandCenter() {
  const client = useQueryClient();
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Person[] }>('/api/v1/patients') });
  const [selected, setSelected] = useState('');
  const patient = patients.data?.items.find(x => x.id === selected) ?? patients.data?.items[0];
  const date = today();
  const query = useQuery({ queryKey: ['command-center', patient?.id, date], queryFn: () => api<Center>(`/api/v1/command-center?patient_id=${patient!.id}&date=${date}`), enabled: !!patient, refetchInterval: 15000 });
  const [notice, setNotice] = useState('');
  const [reminder, setReminder] = useState('');
  const [notes, setNotes] = useState('');
  const data = query.data;
  async function refresh() { await client.invalidateQueries({ queryKey: ['command-center'] }); }
  async function action(path: string, method = 'POST', body?: unknown) { await api(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) }); await refresh(); }
  async function resolve(item: Action, verb: 'done' | 'dismiss' | 'snooze') {
    const url = `/api/v1/action-items/${item.id}/${verb}`;
    const payload = verb === 'dismiss' ? { reason: 'Reviewed in Command Center' } : verb === 'snooze' ? { until: new Date(Date.now() + 30 * 60_000).toISOString() } : {};
    await action(url, 'POST', payload);
  }
  async function runSuggested(item: Action) {
    const suggested = item.suggested_actions[0];
    if (!suggested) return;
    if (suggested.option === 'ACKNOWLEDGE_INCIDENT' && suggested.incident_id) {
      await action(`/api/v1/incidents/${suggested.incident_id}/acknowledge`); return;
    }
    if (suggested.option === 'OPEN_HANDOVER') return;
    setNotice('This item needs a coordinator to choose a caregiver or confirm the assignment.');
  }
  async function generateMorning() { if (!patient) return; await action(`/api/v1/patients/${patient.id}/briefs/morning`, 'POST', { for_date: date }); setNotice('Morning brief generated from the current care plan.'); }
  async function createHandover() { if (!patient) return; const result = await api<Exclude<Brief, null>>(`/api/v1/patients/${patient.id}/briefs/handover/draft`, { method: 'POST', body: JSON.stringify({ for_date: date, notes }) }); await refresh(); setNotice(`Handover draft ${result.status.toLowerCase()}.`); }
  async function publish(brief: Brief) { if (!brief) return; await action(`/api/v1/briefs/${brief.id}/publish`); setNotice('Handover published for its care-team recipient.'); }
  async function ack(brief: Brief) { if (!brief) return; await action(`/api/v1/briefs/${brief.id}/acknowledge`); setNotice('Handover acknowledged.'); }
  async function addReminder() { if (!patient || !reminder.trim()) return; await action(`/api/v1/action-items?patient_id=${patient.id}`, 'POST', { title: reminder.trim() }); setReminder(''); setNotice('Reminder added to the pending actions list.'); }
  if (patients.isLoading) return <section className="card"><div className="skeleton"/></section>;
  if (!patient) return <section className="card"><h2>Caregiver Command Center</h2><p>No care circle is available for this account.</p></section>;
  if (query.isLoading || !data) return <section className="card"><div className="skeleton"/><p className="muted">Loading today’s coordination view…</p></section>;
  const cards = (title: string, items: Action[], empty: string, urgent = false) => <section className="cc-section"><div className="section-head"><h3>{title}<span className="cc-count">{items.length}</span></h3></div>{items.length ? <div className="cc-items">{items.map(item => <article className={`cc-item ${urgent ? 'urgent' : ''}`} key={item.id}><div className="cc-item-head"><strong>{item.title}</strong><span className={`cc-severity ${item.severity.toLowerCase()}`}>{item.severity}</span></div><p>{item.reason}</p>{item.reasons.length > 1 && <details><summary>Why this is here</summary><ul>{item.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></details>}<div className="cc-actions">{item.suggested_actions.length > 0 && <button onClick={() => void runSuggested(item).catch(() => setNotice('Could not complete that action.'))}>Review action</button>}<span className="muted">Open · {age(item.age_seconds)}</span>{data.role_view !== 'FAMILY' && <><button aria-label={`Snooze ${item.title}`} onClick={() => void resolve(item, 'snooze').catch(() => setNotice('Could not snooze this item.'))}><Clock3 size={16}/> 30 min</button>{item.kind === 'MANUAL_REMINDER' && <button onClick={() => void resolve(item, 'done').catch(() => setNotice('Could not complete the reminder.'))}><Check size={16}/> Done</button>}</>}</div></article>)}</div> : <div className="cc-empty"><span>✓</span><div><strong>{empty}</strong><p>Based on confirmed assignments and logged updates.</p></div></div>}</section>;
  return <div className="command-center"><div className="cc-top"><div><p className="eyebrow">PHASE 4 · CAREGIVER COMMAND CENTER</p><h1>{patient.name}’s care today</h1><p className="muted">A shared view of coordination work and what needs follow-up.</p></div><div className="cc-tools">{(patients.data?.items.length ?? 0) > 1 && <label className="cc-select">Care circle<select value={patient.id} onChange={e => setSelected(e.target.value)}>{patients.data!.items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}<button aria-label="Refresh command center" onClick={() => void query.refetch()}><RefreshCw size={16}/> Refresh</button></div></div>
    {patient.is_synthetic && <p className="cc-demo">DEMO · SYNTHETIC DATA</p>}
    <p className="cc-basis">{data.basis_note} Updated {time(data.as_of)}.</p>
    <div className="cc-metrics">{[['On track',data.summary.on_track],['Needs now',data.summary.needs_now],['At risk',data.summary.at_risk],['Decisions',data.summary.decisions_waiting],['Handled today',data.summary.handled_today]].map(([label,value]) => <div className="cc-metric" key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
    {data.setup_hints.map(hint => <p className="cc-hint" key={hint}>{hint}</p>)}
    <div className="cc-layout"><div className="cc-main">{cards('Needs now', data.needs_now, 'Nothing needs your attention right now.', true)}{cards('Decisions waiting', data.decisions_waiting, 'No care decisions are waiting.')}{cards('At risk', data.at_risk, 'No upcoming coordination gaps found.')}
      <section className="cc-section"><div className="section-head"><h3>Today’s plan</h3><span className="muted">{data.load_today.tasks} tasks · {data.load_today.hours} scheduled hours</span></div>{data.todays_plan.blocks.length ? <div className="cc-plan">{data.todays_plan.blocks.map((block,i) => <details key={`${block.title}-${i}`} open={i < 2}><summary><span>{block.daypart ?? 'Scheduled'}</span><strong>{block.title}</strong><span>{time(block.start)}{block.end ? `–${time(block.end)}` : ''}</span></summary>{block.activities?.map(activity => <div className="cc-task" key={activity.activity_id}><span>{time(activity.start)}</span><span>{activity.title}</span><span>{activity.status === 'COMPLETED' ? 'Done' : data.role_view === 'MY_DAY' ? <button onClick={e=>{e.preventDefault();void action(`/api/v1/activities/${activity.activity_id}/complete`).catch(()=>setNotice('Could not mark this task done.'));}}>Done</button> : 'Scheduled'}</span></div>)}{block.activity_id && <div className="cc-task"><span>{time(block.start)}</span><span>{block.title}</span><span>{block.status === 'COMPLETED' ? 'Done' : data.role_view === 'MY_DAY' ? <button onClick={e=>{e.preventDefault();void action(`/api/v1/activities/${block.activity_id}/complete`).catch(()=>setNotice('Could not mark this task done.'));}}>Done</button> : 'Scheduled'}</span></div>}</details>)}</div> : <div className="cc-empty"><span>—</span><strong>No activities scheduled for this day.</strong></div>}</section>
      {cards('Pending actions', data.pending_actions, 'No reminders are pending.')}
      {data.role_view !== 'FAMILY' && <section className="cc-section"><div className="section-head"><h3>Add a reminder</h3></div><div className="cc-add"><input aria-label="Reminder" maxLength={200} value={reminder} onChange={e=>setReminder(e.target.value)} placeholder="A task for the care team"/><button onClick={()=>void addReminder().catch(()=>setNotice('Could not add the reminder.'))}>Add reminder</button></div></section>}
      {cards('Handled today', data.handled, 'Nothing has been marked handled today.')}
    </div><aside className="cc-rail"><section className="card"><p className="eyebrow">BRIEFINGS</p><h3>Morning summary</h3>{data.briefs.morning ? <><pre className="cc-brief">{data.briefs.morning.rendered_text}</pre><button onClick={()=>void navigator.clipboard.writeText(data.briefs.morning!.rendered_text).then(()=>setNotice('Morning summary copied.'))}>Copy summary</button></> : <><p className="muted">A factual recap of the current plan and coordination items.</p><button onClick={()=>void generateMorning().catch(()=>setNotice('Could not generate the morning summary.'))}>Generate morning summary</button></>}</section>
      <section className="card"><p className="eyebrow">SHIFT CHANGE</p><h3>End-of-day handover</h3>{data.briefs.handover && <><p className="cc-status">{data.briefs.handover.status}{data.briefs.handover.auto_generated?' · auto-generated, not reviewed':''}</p><pre className="cc-brief">{data.briefs.handover.rendered_text}</pre>{data.briefs.handover.status === 'DRAFT' && data.role_view !== 'FAMILY' && <button onClick={()=>void publish(data.briefs.handover).catch(()=>setNotice('Could not publish the handover.'))}><Send size={16}/> Publish handover</button>}{data.briefs.handover.status === 'PUBLISHED' && data.briefs.handover.to_user_id && <button onClick={()=>void ack(data.briefs.handover).catch(()=>setNotice('Could not acknowledge this handover.'))}>Acknowledge handover</button>}</>}{(!data.briefs.handover || data.briefs.handover.status !== 'DRAFT') && data.role_view !== 'FAMILY' && <><label className="cc-notes">Outgoing caretaker notes<textarea maxLength={2000} rows={3} value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Factual handover notes"/></label><button onClick={()=>void createHandover().catch(()=>setNotice('Could not create the handover draft.'))}>Create handover draft</button></>}</section>
      <section className="card cc-load"><p className="eyebrow">COORDINATION LOAD</p><strong>{data.load_today.hours} hours</strong><span>{data.load_today.tasks} scheduled tasks today</span>{data.load_today.next_free_window && <p>Next free window: {time(data.load_today.next_free_window.start)}–{time(data.load_today.next_free_window.end)}</p>}</section>
    </aside></div>{notice && <p className="cc-notice" role="status">{notice}</p>}</div>;
}
