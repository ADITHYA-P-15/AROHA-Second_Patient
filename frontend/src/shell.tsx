import { FormEvent, Fragment, useEffect, useRef, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, CalendarClock, CalendarDays, HandHelping, HeartHandshake, History, LifeBuoy, ListChecks, LogOut, Menu, Network, RotateCcw, Pill, Scale, Siren, Stethoscope, Sun, UserRound, Users, X, type LucideIcon } from 'lucide-react';
import { CommandCenter } from './CommandCenter.tsx';
import { WorkloadBalancer } from './WorkloadBalancer.tsx';
import { CoverRequests } from './CoverRequests.tsx';
import { CoverageForecast } from './CoverageForecast.tsx';
import { CareTeam, CareCodeCard } from './CareTeam.tsx';
import { ProfessionalPatients } from './ProfessionalPatients.tsx';
import { MedicinesAppointments } from './MedicinesAppointments.tsx';
import { MyDay } from './MyDay.tsx';
import { CarePlan } from './CarePlan.tsx';
import { usePatientPick } from './PatientPick.tsx';
import { scheduleSummary, supportLabel, type WeeklyWindow } from './lib/plan.ts';
import { api } from './api/client.ts';
import { formatAppTime, localInputToIso, nowLocalInput } from './lib/time.ts';
import { newId } from './lib/id.ts';

type User = { id: string; email: string; name: string; role: string; role_label?: string };
type Patient = { id: string; name: string; birth_year?: number; care_notes: string; clinical_notes?: string | null; is_synthetic: boolean };
const demo: Record<string, string> = { PRIMARY_CONTACT: 'anita.iyer@secondpatient.demo', CARETAKER: 'savitha@secondpatient.demo', PROFESSIONAL: 'dr.arjun.nair@secondpatient.demo', PATIENT: 'ramesh.iyer@secondpatient.demo' };
const roleLabels: Record<string, string> = { PRIMARY_CONTACT: 'Primary contact', CARETAKER: 'Caretaker', PROFESSIONAL: 'Healthcare professional', PATIENT: 'Patient' };
const signUpRoles: { role: string; blurb: string }[] = [
  { role: 'PRIMARY_CONTACT', blurb: 'a relative who registers the patient and oversees care' },
  { role: 'CARETAKER', blurb: 'carries out medication doses and appointments' },
  { role: 'PROFESSIONAL', blurb: 'hospital staff who prescribe and schedule' },
];
type NavItem = { title: string; path: string; icon: LucideIcon; group?: string };
// Grouped so each role sees its daily screens first; only screens that work today are listed.
const roleNav: Record<string, NavItem[]> = {
  PRIMARY_CONTACT: [
    { title: 'Command Center', path: '/command-center', icon: ListChecks, group: 'Today' },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'Medicines & Appointments', path: '/medicines', icon: Pill },
    { title: 'Cover Requests', path: '/cover', icon: LifeBuoy, group: 'Planning' },
    { title: 'Coverage Forecast', path: '/forecast', icon: CalendarClock },
    { title: 'Workload Balancer', path: '/workload', icon: Scale },
    { title: 'Care Team', path: '/care-team', icon: Network, group: 'People' },
    { title: 'Caretakers', path: '/care-network', icon: Users },
    { title: 'Patient Profile', path: '/patient-profile', icon: UserRound },
    { title: 'Help Requests', path: '/incidents', icon: Siren, group: 'Records' },
    { title: 'History', path: '/history', icon: History },
  ],
  CARETAKER: [
    { title: 'My Day', path: '/my-day', icon: Sun },
    { title: 'Cover Requests', path: '/cover', icon: LifeBuoy },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'My Availability', path: '/care-network', icon: Users },
    { title: 'Help Requests', path: '/incidents', icon: Siren },
  ],
  PROFESSIONAL: [
    { title: 'Patients', path: '/patients', icon: Stethoscope },
    { title: 'Medicines & Appointments', path: '/medicines', icon: Pill },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'Help Requests', path: '/incidents', icon: Siren },
    { title: 'History', path: '/history', icon: History },
  ],
  PATIENT: [
    { title: 'Today', path: '/my-day', icon: Sun },
    { title: 'Request Help', path: '/request-help', icon: HandHelping },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
  ],
};
const homeFor = (role: string) => (roleNav[role] ?? roleNav.PRIMARY_CONTACT)[0].path;
function Login({ onLogin, demoMode }: { onLogin: (u: User) => void; demoMode: boolean }) {
  const [registering, setRegistering] = useState(false); const [name, setName] = useState('');
  const [role, setRole] = useState('PRIMARY_CONTACT'); const [email, setEmail] = useState(demo.PRIMARY_CONTACT); const [password, setPassword] = useState('Demo@1234'); const [error, setError] = useState('');
  async function submit(e: FormEvent) {
    e.preventDefault(); setError('');
    try {
      const u = registering
        ? await api<User>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password, role }) })
        : await api<User>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      onLogin(u);
    } catch (err) { setError(err instanceof Error ? err.message : 'Sign-in failed'); }
  }
  return <><main className="login"><div className="brand"><span className="brand-icon"><HeartHandshake/></span><span>CareCircle</span></div><p className="eyebrow">THE CAREGIVER IS THE SECOND PATIENT</p><h1>{registering ? 'Start a care circle.' : 'Support that stays connected.'}</h1><p className="muted">{registering ? 'Choose your role to create an account. Patients get their login from their primary contact.' : 'Sign in to coordinate the everyday care around someone you love.'}</p><form onSubmit={submit}>{registering&&<label>Your name<input required minLength={1} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label>}{registering&&<fieldset className="ct-roles"><legend>I am a…</legend>{signUpRoles.map(r=><label key={r.role} className="ct-role"><input type="radio" name="role" value={r.role} checked={role===r.role} onChange={()=>setRole(r.role)}/><span><strong>{roleLabels[r.role]}</strong> — {r.blurb}</span></label>)}</fieldset>}<label>Email<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<input type="password" required minLength={8} value={password} onChange={e=>setPassword(e.target.value)}/></label>{error&&<p className="error">{error}</p>}<button className="primary">{registering?'Create account':'Sign in'}</button></form><button className="text-button" onClick={()=>{setRegistering(!registering);setError('');}}>{registering?'Already have an account? Sign in':'Create an account'}</button>{demoMode&&!registering&&<><p className="eyebrow demo-label">DEMO ACCOUNTS</p><div className="chips">{Object.keys(demo).map(r=><button key={r} onClick={()=>setEmail(demo[r])}>{roleLabels[r]}</button>)}</div><p className="muted small">Demo password: Demo@1234</p></>}</main><div className="login-disclaimer">Operational care-coordination tool — not a diagnostic or emergency service. Demo data is fictional.</div></>;
}
function App() {
  const queryClient = useQueryClient(); const navigate = useNavigate();
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<User>('/api/v1/auth/me'), retry: false });
const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{phase:number;version:string;demo_mode:boolean;escalation_scaled:boolean;escalation_time_scale:number}>('/api/v1/meta') });
  if (me.isLoading) return <div className="loading">Loading your workspace…</div>;
  if (me.isError) return <Login demoMode={meta.data?.demo_mode ?? false} onLogin={u=>{ queryClient.setQueryData(['me'],u); navigate(homeFor(u.role)); }} />;
  return <Workspace user={me.data!} meta={meta.data}/>;
}

function Workspace({ user, meta }: { user: User; meta?: { phase: number; version: string; demo_mode: boolean; escalation_scaled: boolean; escalation_time_scale: number } }) {
  const queryClient = useQueryClient(); const navigate = useNavigate(); const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { setMenuOpen(false); }, [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);
  const [resetting, setResetting] = useState(false);
  const resetDemo = async () => {
    if (!window.confirm('Reset the demo? Every demo patient goes back to the starting story (doses, appointments, caretakers). Your demo logins stay the same.')) return;
    setResetting(true);
    try { await api('/api/v1/demo/reset', { method: 'POST' }); try { sessionStorage.clear(); } catch { /* ignore */ } await queryClient.invalidateQueries(); navigate(homeFor(user.role)); }
    catch (err) { window.alert(err instanceof Error ? err.message : 'Could not reset the demo.'); }
    finally { setResetting(false); }
  };
  const logout = async () => { try { await api('/api/v1/auth/logout', { method: 'POST' }); } finally { queryClient.clear(); navigate('/', { replace: true }); } };
  const menu = roleNav[user.role] ?? roleNav.PRIMARY_CONTACT;
  const roleLabel = user.role_label ?? roleLabels[user.role] ?? user.role;
  const current = menu.find(item => item.path === location.pathname);
  const page = (path: string) => {
    switch (path) {
      case '/command-center': return <CommandCenter/>;
      case '/cover': return <CoverRequests/>;
      case '/medicines': return <MedicinesAppointments/>;
      case '/my-day': return <MyDay/>;
      case '/forecast': return <CoverageForecast/>;
      case '/workload': return <WorkloadBalancer/>;
      case '/incidents': return <IncidentCenter/>;
      case '/request-help': return <HelpPage/>;
      case '/care-team': return <CareTeam/>;
      case '/patients': return <ProfessionalPatients/>;
      case '/patient-profile': return <PatientProfile/>;
      case '/care-network': return <CareNetwork role={user.role}/>;
      case '/care-plan': return <CarePlan role={user.role}/>;
      case '/history': return <HistoryPage/>;
      default: return <Placeholder role={roleLabel} title="Coming in a later phase"/>;
    }
  };
  return <div className="app">
    <aside className="sidebar" data-open={menuOpen} aria-label="Main menu">
      <div className="sidebar-top"><div className="brand"><span className="brand-icon"><HeartHandshake/></span><span>CareCircle</span></div><button className="icon-button menu-close" aria-label="Close menu" onClick={() => setMenuOpen(false)}><X size={20}/></button></div>
      {meta?.demo_mode && <div className="demo-tag">DEMO · SYNTHETIC DATA</div>}
      <nav className="side-nav">{menu.map(({ title, path, icon: Icon, group }) => <Fragment key={path}>{group && <p className="nav-group">{group}</p>}<NavLink to={path} end className={({ isActive }) => isActive ? 'active' : undefined}><Icon size={18} aria-hidden="true"/>{title}</NavLink></Fragment>)}</nav>
      {meta?.demo_mode && user.email.endsWith('@secondpatient.demo') && <button className="reset-demo" disabled={resetting} onClick={() => void resetDemo()}><RotateCcw size={15} aria-hidden="true"/>{resetting ? 'Resetting…' : 'Reset demo data'}</button>}
      <div className="side-bottom"><span className="avatar">{user.name[0]}</span><div className="identity"><strong>{user.name}</strong><small>{roleLabel}</small></div><button className="icon-button" aria-label="Log out" title="Log out" onClick={() => void logout()}><LogOut size={18}/></button></div>
    </aside>
    {menuOpen && <div className="scrim" aria-hidden="true" onClick={() => setMenuOpen(false)}/>}
    <main className="workspace">
      <header className="topbar">
        <button className="icon-button menu-toggle" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}><Menu size={22}/></button>
        <div className="topbar-title"><p className="eyebrow">{roleLabel.toUpperCase()} · {user.name.toUpperCase()}</p><h2>{current?.title ?? 'CareCircle'}</h2></div>
        <div className="topbar-actions"><NotificationBell/><button className="logout-button" onClick={() => void logout()}><LogOut size={16} aria-hidden="true"/><span>Log out</span></button></div>
      </header>
      {meta?.escalation_scaled && <div className="demo-tag" role="status">DEMO TIMER SCALE · {meta.escalation_time_scale}×</div>}
      <div className="page" key={location.pathname}>
        <Routes>{menu.map(item => <Route key={item.path} path={item.path} element={page(item.path)}/>)}<Route path="*" element={<Navigate to={homeFor(user.role)} replace/>}/></Routes>
      </div>
      <footer>Operational care-coordination tool — not a diagnostic or emergency service. Demo data is fictional.<span>Phase {meta?.phase ?? 4} · v{meta?.version ?? '0.4.0'}</span></footer>
    </main>
  </div>;
}

function NotificationBell(){
  const [open,setOpen]=useState(false);const client=useQueryClient();const navigate=useNavigate();
  const query=useQuery({queryKey:['notifications'],queryFn:()=>api<{items:{id:string;incident_id?:string|null;title:string;body:string;read_at?:string|null;created_at:string}[];unread_count:number}>('/api/v1/notifications'),refetchInterval:10000});
  async function choose(item:{id:string;incident_id?:string|null}){await api(`/api/v1/notifications/${item.id}/read`,{method:'POST'});await client.invalidateQueries({queryKey:['notifications']});setOpen(false);if(item.incident_id)navigate('/incidents');}
  return <div className="notification-menu"><button className="icon-button" aria-label={`Notifications, ${query.data?.unread_count ?? 0} unread`} aria-expanded={open} onClick={()=>setOpen(!open)}><Bell/>{Boolean(query.data?.unread_count)&&<span>{query.data?.unread_count}</span>}</button>{open&&<section className="card" aria-label="Notifications"><h3>Notifications</h3>{query.data?.items.length?query.data.items.slice(0,8).map(item=><button key={item.id} onClick={()=>void choose(item).catch(()=>undefined)}><strong>{item.title}</strong><small>{item.body}</small></button>):<p>No notifications.</p>}</section>}</div>;
}
type IncidentRow = { id:string; patient_id:string; current_level:number; category:string; severity:string; status:string; title:string; safe_summary:string; created_at?:string; current_deadline_at?:string|null; deadline_kind?:string|null; emergency_unacknowledged?:boolean; acknowledged_at?:string|null; resolved_at?:string|null };
// Routing levels describe who is asked to respond, not a medical judgement.
const levelNames = ['For information','Caretakers asked','Family asked','Healthcare team asked','Doctor asked','Emergency'];
const incidentStatus = (s:string) => s==='OPEN'?'Waiting for someone':s==='ACKNOWLEDGED'?'Being handled':s==='RESOLVED'?'Handled':s==='CANCELLED'?'Cancelled':s.toLowerCase();
function IncidentCenter() {
  const client=useQueryClient(); const [notice,setNotice]=useState(''); const [showClosed,setShowClosed]=useState(false);
  const incidents=useQuery({queryKey:['incidents'],queryFn:()=>api<{items:IncidentRow[]}>('/api/v1/incidents'),refetchInterval:5000});
  async function act(item:IncidentRow,verb:'acknowledge'|'resolve'){
    let body:Record<string,string>={};
    if(verb==='resolve'){const note=item.current_level===5?window.prompt('What happened? (required for an emergency)',''):'';if(note===null||(item.current_level===5&&!note.trim()))return;body={code:'HANDLED',note:note.trim()};}
    try{await api(`/api/v1/incidents/${item.id}/${verb}`,{method:'POST',body:JSON.stringify(body)});setNotice(verb==='acknowledge'?'Thanks — the others can see you are handling it.':'Marked as handled. The patient has been told.');}
    catch(err){setNotice(err instanceof Error?err.message:'Could not update this request.');}
    await client.invalidateQueries({queryKey:['incidents']});await client.invalidateQueries({queryKey:['notifications']});
  }
  const items=incidents.data?.items??[];
  const open=items.filter(i=>i.status==='OPEN'||i.status==='ACKNOWLEDGED');const closed=items.filter(i=>!open.includes(i));
  const emergency=open.find(item=>item.emergency_unacknowledged);
  const row=(item:IncidentRow)=><li key={item.id} className={`hr-item hr-l${item.current_level}`}>
    <div className="cp-title"><strong>{item.title}</strong><span className="chip">{levelNames[item.current_level]??`Level ${item.current_level}`}</span><span className={`md-status ${item.status==='OPEN'?'md-st-bad':item.status==='ACKNOWLEDGED'?'md-st-pending':'md-st-muted'}`}>{incidentStatus(item.status)}</span></div>
    <p className="cp-detail">{item.safe_summary}{item.status==='OPEN'&&item.current_deadline_at?` · goes to the next person at ${formatAppTime(item.current_deadline_at,{dateStyle:undefined,timeStyle:'short'})}`:''}</p>
    {(item.status==='OPEN'||item.status==='ACKNOWLEDGED')&&<div className="cp-actions">{item.status==='OPEN'&&<button className="cp-btn cp-primary" onClick={()=>void act(item,'acknowledge')}>I’ve got this</button>}{item.status==='ACKNOWLEDGED'&&<button className="cp-btn cp-primary" onClick={()=>void act(item,'resolve')}>Mark handled</button>}</div>}
  </li>;
  return <div className="cp"><div className="section-head"><div><p className="eyebrow">HELP REQUESTS</p><h3>{open.length?`${open.length} open request${open.length===1?'':'s'}`:'No open requests'}</h3></div><button className="cp-filter" onClick={()=>setShowClosed(!showClosed)}>{showClosed?'Hide handled':'Show handled'}</button></div>
    <p className="muted small">Messages and SOS from the patient, and alerts the care team needs to answer. Levels say who is asked to respond; they are not a medical diagnosis.</p>
    {notice&&<p className="md-notice" role="status">{notice}</p>}
    {emergency&&<section className="card hr-emergency" role="alert" aria-live="assertive"><h3>Emergency — nobody has responded yet</h3><p>{emergency.safe_summary}</p><p>If there is immediate danger, call now: <a href="tel:108">108</a> · <a href="tel:112">112</a></p></section>}
    {incidents.isLoading?<div className="skeleton"/>:open.length?<ul className="hr-list">{open.map(row)}</ul>:<section className="card cp-empty"><p>Nothing needs an answer right now.</p></section>}
    {showClosed&&closed.length>0&&<><h4 className="hr-sub">Handled</h4><ul className="hr-list">{closed.slice(0,20).map(row)}</ul></>}
  </div>;
}

function HelpPage() {
  const patients=useQuery({queryKey:['patients'],queryFn:()=>api<{items:Patient[]}>('/api/v1/patients')});
  // One idempotency key per draft: retrying after a dropped connection reuses it, so no duplicate request is created.
  const draftKey=useRef(newId());
  const [message,setMessage]=useState('');const [incident,setIncident]=useState<IncidentRow|null>(null);const [error,setError]=useState('');const [countdown,setCountdown]=useState<number|null>(null);
  const tracked=useQuery({queryKey:['patient-incidents'],queryFn:()=>api<{items:IncidentRow[]}>('/api/v1/incidents'),enabled:!!incident,refetchInterval:5000});
  const liveIncident=tracked.data?.items.find(item=>item.id===incident?.id)??incident;
  const patientId=patients.data?.items[0]?.id;
  useEffect(()=>{
    if(countdown===null||!patientId)return;
    if(countdown===0){setCountdown(null);void api<IncidentRow>(`/api/v1/patients/${patientId}/sos`,{method:'POST'}).then(setIncident).catch(()=>setError('Could not reach CareCircle — call 108/112 or your family directly.'));return;}
    const timer=window.setTimeout(()=>setCountdown(countdown-1),1000);return()=>window.clearTimeout(timer);
  },[countdown,patientId]);
  async function send(text=message){if(!patientId||!text.trim())return;setError('');try{const item=await api<IncidentRow>(`/api/v1/patients/${patientId}/messages`,{method:'POST',headers:{'Idempotency-Key':draftKey.current},body:JSON.stringify({body:text.trim(),channel:'TEXT'})});setIncident(item);setMessage('');draftKey.current=newId();}catch{setError('Could not reach CareCircle — call 108/112 or your family directly.');}}
  const chips=['I need water','Help me to the bathroom','I missed my medicine','I feel dizzy','Nobody came',"I'm fine/took my medicine"];
  return <section className="card"><p className="eyebrow">PATIENT HELP</p><h2>Tell us what you need</h2><p>CareCircle routes your message to the right people. It is not a medical diagnosis and cannot replace emergency services. In immediate danger call 108 / 112.</p><div className="chips help-chips">{chips.map(chip=><button key={chip} onClick={()=>void send(chip)}>{chip}</button>)}</div><label>Your message<textarea maxLength={1000} value={message} onChange={e=>setMessage(e.target.value)} rows={4}/></label><button className="primary" disabled={!message.trim()} onClick={()=>void send()}>Send request</button><div className="card" style={{marginTop:20,borderColor:'#b42318'}}><h3>Emergency SOS</h3>{countdown===null?<button className="primary sos" onClick={()=>{setError('');setCountdown(3);}}>Start SOS · 3 second countdown</button>:<><p role="status">SOS will be sent in {countdown}…</p><button onClick={()=>setCountdown(null)}>Cancel SOS</button></>}</div>{error&&<p role="alert" className="error">{error}</p>}{liveIncident&&<div className="system" role="status"><div><strong>{levelNames[liveIncident.current_level]}</strong><small>{liveIncident.status==='ACKNOWLEDGED'?'Being handled':liveIncident.status==='RESOLVED'?'Resolved':'Sent — waiting for a care team response'}</small></div></div>}{liveIncident?.current_level===5&&<section className="card" aria-label="Emergency contacts"><strong>In immediate danger, call now.</strong><p>{liveIncident.acknowledged_at?'A care team member has acknowledged.':'No one has acknowledged yet — please call 108/112 now.'}</p><a href="tel:108">Call 108</a> · <a href="tel:112">Call 112</a></section>}</section>;
}

function Placeholder({role,title}:{role:string;title:string}){return <section className="card placeholder"><p className="eyebrow">{role} WORKSPACE</p><h2>{title}</h2><p>This part of the care continuity workspace is planned for a later phase.</p></section>}

type SupportNeed = { support_code: string; notes: string };
type PatientDetails = { id: string; name: string; care_code?: string | null; care_notes: string; clinical_notes?: string | null; mobility_level: string; my_permissions: string[]; support_needs: SupportNeed[] };
type Caregiver = { id: string; user_id?: string | null; is_main_caretaker?: boolean; name: string; kind: string; relationship: string; is_active: boolean; capabilities: string[]; max_activities_per_day: number; max_hours_per_week: number; phone?: string | null };
type HistoryEvent = { id: string; summary: string; event_type: string; occurred_at: string };
type Overview = { upcoming_activities: { id: string }[]; not_yet_confirmed_count: number; caregivers: Caregiver[]; recent_history: HistoryEvent[] };
const MOBILITY: [string, string][] = [['INDEPENDENT', 'Walks independently'], ['NEEDS_AID', 'Needs a walking aid'], ['WHEELCHAIR', 'Uses a wheelchair'], ['BEDBOUND', 'Bed-bound']];
const SUPPORT_CODES = ['MEDICATION_ASSIST', 'APPOINTMENT_ESCORT', 'TRANSPORT', 'DAILY_ASSIST', 'MOBILITY_ASSIST', 'PRESCRIPTION_PICKUP', 'LAB_ESCORT', 'SUPPLIES'];
const PRESETS: [string, WeeklyWindow[]][] = [
  ['Every day 08:00–20:00', Array.from({ length: 7 }, (_, weekday) => ({ weekday, start_min: 480, end_min: 1200 }))],
  ['Weekdays 09:00–18:00', Array.from({ length: 5 }, (_, weekday) => ({ weekday, start_min: 540, end_min: 1080 }))],
  ['Mornings 06:00–12:00', Array.from({ length: 7 }, (_, weekday) => ({ weekday, start_min: 360, end_min: 720 }))],
  ['Evenings 17:00–21:00', Array.from({ length: 7 }, (_, weekday) => ({ weekday, start_min: 1020, end_min: 1260 }))],
  ['Weekends only', [5, 6].map(weekday => ({ weekday, start_min: 0, end_min: 1440 }))],
  ['Any time', Array.from({ length: 7 }, (_, weekday) => ({ weekday, start_min: 0, end_min: 1440 }))],
];
function PatientProfile() {
  const {id,picker}=usePatientPick(); const client=useQueryClient();
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});
  const overview=useQuery({queryKey:['overview',id],queryFn:()=>api<Overview>(`/api/v1/patients/${id}/overview`),enabled:!!id});
  const [name,setName]=useState(''); const [notes,setNotes]=useState(''); const [mobility,setMobility]=useState('INDEPENDENT'); const [needs,setNeeds]=useState<string[]>([]); const [message,setMessage]=useState('');
  useEffect(()=>{if(patient.data){setName(patient.data.name);setNotes(patient.data.care_notes??'');setMobility(patient.data.mobility_level??'INDEPENDENT');setNeeds((patient.data.support_needs??[]).map(x=>x.support_code));}},[patient.data]);
  const canEdit=patient.data?.my_permissions?.includes('plan:manage');
  async function save(e:FormEvent){e.preventDefault();setMessage('');try{await api(`/api/v1/patients/${id}`,{method:'PATCH',body:JSON.stringify({name,care_notes:notes,mobility_level:mobility})});await api(`/api/v1/patients/${id}/support-needs`,{method:'PUT',body:JSON.stringify(needs.map(support_code=>({support_code,notes:''})))});await client.invalidateQueries({queryKey:['patient',id]});setMessage('Patient profile saved.');}catch(err){setMessage(err instanceof Error?err.message:'Could not save profile.');}}
  if(!id)return <section className="card">No patient is linked to this account yet.</section>;
  const o=overview.data;
  return <><div className="section-head"><div><p className="eyebrow">PATIENT PROFILE</p><h3>{patient.data?.name??'Patient'}</h3></div>{picker}</div>
    {message&&<p role="status" className="md-notice">{message}</p>}
    {patient.data?.care_code&&<CareCodeCard name={patient.data.name} code={patient.data.care_code} patientId={canEdit?id:undefined}/>}
    <div className="grid"><section className="card"><h3>Profile</h3>{patient.data?.clinical_notes&&<p className="pp-note"><strong>Clinical notes</strong><br/>{patient.data.clinical_notes}</p>}
      {canEdit?<form className="pp-form" onSubmit={save}><label>Name<input value={name} onChange={e=>setName(e.target.value)} required/></label><label>Mobility<select value={mobility} onChange={e=>setMobility(e.target.value)}>{MOBILITY.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><label>Shared care notes<textarea value={notes} onChange={e=>setNotes(e.target.value)}/></label><fieldset className="pp-needs"><legend>Help needed</legend>{SUPPORT_CODES.map(code=><label key={code}><input type="checkbox" checked={needs.includes(code)} onChange={e=>setNeeds(e.target.checked?[...needs,code]:needs.filter(n=>n!==code))}/>{supportLabel(code)}</label>)}</fieldset><button className="primary">Save profile</button></form>:<p>{patient.data?.care_notes}</p>}</section>
    <section className="card"><h3>Next 7 days</h3><p className="pp-stat"><strong>{o?.upcoming_activities?.length??0}</strong> doses and appointments · <strong>{o?.not_yet_confirmed_count??0}</strong> without a confirmed caretaker</p><h4>Caretakers</h4><ul className="pp-list">{o?.caregivers?.map(c=><li key={c.id}>{c.name}<small>{c.relationship||'caretaker'}{c.is_main_caretaker?' · main caretaker':''}</small></li>)}</ul><h4>Recent changes</h4><ul className="pp-list">{o?.recent_history?.slice(0,5).map((h,i)=><li key={i}>{h.summary}<small>{formatAppTime(h.occurred_at)}</small></li>)}</ul></section></div></>;
}
function CareNetwork({role}:{role:string}) {
  const {id,picker}=usePatientPick();
  const me=useQuery({queryKey:['me'],queryFn:()=>api<{id:string}>('/api/v1/auth/me')});
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});
  const network=useQuery({queryKey:['caregivers',id],queryFn:()=>api<{items:Caregiver[]}>(`/api/v1/patients/${id}/caregivers`),enabled:!!id});
  const [message,setMessage]=useState('');
  const [mainId,setMainId]=useState('');
  const currentMain=network.data?.items.find(c=>c.is_main_caretaker)?.id??'';
  useEffect(()=>{setMainId(currentMain);},[currentMain]);
  const canManage=!!patient.data?.my_permissions?.includes('network:manage');
  async function saveMain(){if(!mainId)return;try{await api(`/api/v1/patients/${id}/main-caretaker`,{method:'PUT',body:JSON.stringify({caregiver_id:mainId})});await network.refetch();setMessage(`${network.data?.items.find(c=>c.id===mainId)?.name??'Caretaker'} is now the main caretaker.`);}catch(err){setMessage(err instanceof Error?err.message:'Could not save the main caretaker.');}}
  if(!id)return <section className="card">No patient is linked to this account.</section>;
  const people=(network.data?.items??[]).filter(c=>role!=='CARETAKER'||c.user_id===me.data?.id).sort((a,b)=>Number(!!b.is_main_caretaker)-Number(!!a.is_main_caretaker)||a.name.localeCompare(b.name));
  return <><div className="section-head"><div><p className="eyebrow">{role==='CARETAKER'?'MY AVAILABILITY':'CARETAKERS'}</p><h3>{role==='CARETAKER'?'When you can help':'Who can help, and when'}</h3></div>{role==='CARETAKER'?null:picker}</div>
    {message&&<p role="status" className="md-notice">{message}</p>}
    {role==='PRIMARY_CONTACT'&&canManage&&<section className="card"><h3>Main caretaker</h3><p className="muted small">New doses and appointments go to the main caretaker when they are free. Otherwise the next best caretaker is asked automatically.</p><div className="md-row"><label className="md-pick">Main caretaker<select value={mainId} onChange={e=>setMainId(e.target.value)}><option value="">Select caretaker</option>{network.data?.items.filter(c=>c.is_active).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button disabled={!mainId||mainId===currentMain} onClick={()=>void saveMain()}>Save</button></div></section>}
    {people.length===0&&<section className="card"><p className="muted">No caretakers yet. Invite them from Care Team.</p></section>}
    <div className="grid">{people.map(c=><CaretakerCard key={c.id} c={c} editable={canManage||c.user_id===me.data?.id} onMessage={setMessage}/>)}</div></>;
}
function CaretakerCard({c,editable,onMessage}:{c:Caregiver;editable:boolean;onMessage:(m:string)=>void}){
  const client=useQueryClient();
  const schedule=useQuery({queryKey:['schedule',c.id],queryFn:()=>api<{windows:WeeklyWindow[]}>(`/api/v1/caregivers/${c.id}/schedule`)});
  const [from,setFrom]=useState(nowLocalInput());const [until,setUntil]=useState('');const [editing,setEditing]=useState(false);
  async function preset(label:string,windows:WeeklyWindow[]){try{await api(`/api/v1/caregivers/${c.id}/schedule`,{method:'PUT',body:JSON.stringify({windows})});await client.invalidateQueries({queryKey:['schedule',c.id]});setEditing(false);onMessage(`${c.name}: usual hours set to ${label}.`);}catch(err){onMessage(err instanceof Error?err.message:'Could not save hours.');}}
  async function away(e:FormEvent){e.preventDefault();try{await api(`/api/v1/caregivers/${c.id}/availability-overrides`,{method:'POST',body:JSON.stringify({start_at:localInputToIso(from),end_at:localInputToIso(until),status:'UNAVAILABLE',reason:'PERSONAL',note:'Time away'})});setUntil('');onMessage(`${c.name} is away ${formatAppTime(localInputToIso(from))} – ${formatAppTime(localInputToIso(until))}. Their tasks in that time will be offered to others.`);}catch(err){onMessage(err instanceof Error?err.message:'Could not record time away.');}}
  return <section className="card cn-card"><div className="card-head"><div><h3>{c.name}</h3><p className="muted small">{c.relationship||'caretaker'}{c.phone?` · ${c.phone}`:''}</p></div>{c.is_main_caretaker?<span className="status-pill">Main caretaker</span>:!c.is_active?<span className="status-pill">Inactive</span>:null}</div>
    <p className="cn-line"><span>Can help with</span>{c.capabilities.map(x=><span className="chip" key={x}>{supportLabel(x)}</span>)}</p>
    <p className="cn-line"><span>Usual hours</span>{schedule.isLoading?'…':scheduleSummary(schedule.data?.windows??[])}</p>
    <p className="cn-line"><span>Limits</span>{c.max_activities_per_day} tasks a day · {c.max_hours_per_week} hours a week</p>
    {editable&&<div className="cn-edit">{editing?<div className="chips">{PRESETS.map(([label,windows])=><button key={label} onClick={()=>void preset(label,windows)}>{label}</button>)}<button onClick={()=>setEditing(false)}>Cancel</button></div>:<button onClick={()=>setEditing(true)}>Change usual hours</button>}
      <details><summary>Add time away</summary><form className="md-form" onSubmit={away}><label>From<input type="datetime-local" required value={from} onChange={e=>setFrom(e.target.value)}/></label><label>Until<input type="datetime-local" required min={from} value={until} onChange={e=>setUntil(e.target.value)}/></label><button className="primary">Save time away</button></form></details></div>}
  </section>;
}
function HistoryPage(){const {id,picker}=usePatientPick();const history=useQuery({queryKey:['history',id],queryFn:()=>api<{items:HistoryEvent[];total:number}>(`/api/v1/patients/${id}/history?limit=100`),enabled:!!id});return <><div className="section-head"><div><p className="eyebrow">HISTORY</p><h3>What changed, and when</h3></div>{picker}</div><section className="card"><ul className="history-list">{history.data?.items.map((x)=><li key={x.id}><i className="timeline-dot"/><span>{x.summary}<small>{formatAppTime(x.occurred_at)}</small></span></li>)}</ul>{history.data?.total===0&&<p>No activity history yet.</p>}</section></>}
export default App;
