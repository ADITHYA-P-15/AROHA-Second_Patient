import { FormEvent, useEffect, useRef, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, CalendarClock, CalendarDays, HandHelping, HeartHandshake, History, LifeBuoy, ListChecks, LogOut, Menu, Network, Pill, Scale, Siren, Stethoscope, Sun, UserRound, Users, X, type LucideIcon } from 'lucide-react';
import { CommandCenter } from './CommandCenter.tsx';
import { WorkloadBalancer } from './WorkloadBalancer.tsx';
import { CoverRequests } from './CoverRequests.tsx';
import { CoverageForecast } from './CoverageForecast.tsx';
import { CareTeam, CareCodeCard } from './CareTeam.tsx';
import { ProfessionalPatients } from './ProfessionalPatients.tsx';
import { MedicinesAppointments } from './MedicinesAppointments.tsx';
import { MyDay } from './MyDay.tsx';
import { sourceLabel, statusLabel, statusTone } from './lib/care.ts';
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
type NavItem = { title: string; path: string; icon: LucideIcon };
// Only screens that work today are listed; later-phase screens join the menu when they ship.
const roleNav: Record<string, NavItem[]> = {
  PRIMARY_CONTACT: [
    { title: 'Command Center', path: '/command-center', icon: ListChecks },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'Medicines & Appointments', path: '/medicines', icon: Pill },
    { title: 'Cover Requests', path: '/cover', icon: LifeBuoy },
    { title: 'Coverage Forecast', path: '/forecast', icon: CalendarClock },
    { title: 'Workload Balancer', path: '/workload', icon: Scale },
    { title: 'Care Team', path: '/care-team', icon: Network },
    { title: 'Caretakers', path: '/care-network', icon: Users },
    { title: 'Patient Profile', path: '/patient-profile', icon: UserRound },
    { title: 'Incident Center', path: '/incidents', icon: Siren },
    { title: 'History', path: '/history', icon: History },
  ],
  CARETAKER: [
    { title: 'My Day', path: '/my-day', icon: Sun },
    { title: 'Cover Requests', path: '/cover', icon: LifeBuoy },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'My Availability', path: '/care-network', icon: Users },
    { title: 'Incident Center', path: '/incidents', icon: Siren },
  ],
  PROFESSIONAL: [
    { title: 'Patients', path: '/patients', icon: Stethoscope },
    { title: 'Medicines & Appointments', path: '/medicines', icon: Pill },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'Incident Center', path: '/incidents', icon: Siren },
    { title: 'History', path: '/history', icon: History },
  ],
  PATIENT: [
    { title: 'Today', path: '/my-day', icon: Sun },
    { title: 'Request Help', path: '/request-help', icon: HandHelping },
    { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
    { title: 'Incident Center', path: '/incidents', icon: Siren },
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
      <nav className="side-nav">{menu.map(({ title, path, icon: Icon }) => <NavLink key={path} to={path} end className={({ isActive }) => isActive ? 'active' : undefined}><Icon size={18} aria-hidden="true"/>{title}</NavLink>)}</nav>
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
type IncidentRow = { id:string; patient_id:string; current_level:number; category:string; severity:string; status:string; title:string; safe_summary:string; current_deadline_at?:string|null; deadline_kind?:string|null; emergency_unacknowledged?:boolean; acknowledged_at?:string|null; resolved_at?:string|null };
const levelNames = ['L0 · Information','L1 · Daily help','L2 · Coordination decision','L3 · Healthcare review','L4 · Doctor review','L5 · Emergency report'];
function IncidentCenter() {
  const client=useQueryClient();
  const incidents=useQuery({queryKey:['incidents'],queryFn:()=>api<{items:IncidentRow[]}>('/api/v1/incidents'),refetchInterval:5000});
  async function acknowledge(id:string){await api(`/api/v1/incidents/${id}/acknowledge`,{method:'POST'});await client.invalidateQueries({queryKey:['incidents']});}
  const emergency=incidents.data?.items.find(item=>item.emergency_unacknowledged&&item.status!=='RESOLVED'&&item.status!=='CANCELLED');
  return <section className="card"><div className="card-head"><div><p className="eyebrow">CARE COORDINATION</p><h2>Incident Center</h2></div><button onClick={()=>void incidents.refetch()}>Refresh</button></div><p className="muted">Routing levels describe coordination routes. They are not medical diagnoses.</p>{emergency&&<section className="card" role="alert" aria-live="assertive"><h2>UNACKNOWLEDGED EMERGENCY</h2><p>{emergency.safe_summary}</p><p>No one has acknowledged yet — call 108/112 now if there is immediate danger.</p><a href="tel:108">Call 108</a> · <a href="tel:112">Call 112</a></section>}{incidents.isLoading?<div className="skeleton"/>:incidents.data?.items.length?<ul className="history-list">{incidents.data.items.map(item=><li key={item.id}><i className="timeline-dot"/><span><strong>{levelNames[item.current_level] ?? `L${item.current_level}`}</strong> · {item.title}<small>{item.safe_summary} · {item.status.toLowerCase()}{item.current_deadline_at&&item.status==='OPEN'?` · next review ${new Date(item.current_deadline_at).toLocaleTimeString()}`:''}</small>{item.status==='OPEN'&&<button onClick={()=>void acknowledge(item.id).catch(()=>undefined)}>I've got this</button>}</span></li>)}</ul>:<p>No incidents are visible to your role.</p>}</section>;
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
  return <section className="card"><p className="eyebrow">PATIENT HELP</p><h2>Tell us what you need</h2><p>CareCircle routes your message to the right people. It is not a medical diagnosis and cannot replace emergency services. In immediate danger call 108 / 112.</p><div className="chips">{chips.map(chip=><button key={chip} onClick={()=>void send(chip)}>{chip}</button>)}</div><label>Your message<textarea maxLength={1000} value={message} onChange={e=>setMessage(e.target.value)} rows={4}/></label><button className="primary" disabled={!message.trim()} onClick={()=>void send()}>Send request</button><div className="card" style={{marginTop:20,borderColor:'#b42318'}}><h3>Emergency SOS</h3>{countdown===null?<button className="primary" onClick={()=>{setError('');setCountdown(3);}}>Start SOS · 3 second countdown</button>:<><p role="status">SOS will be sent in {countdown}…</p><button onClick={()=>setCountdown(null)}>Cancel SOS</button></>}</div>{error&&<p role="alert" className="error">{error}</p>}{liveIncident&&<div className="system" role="status"><div><strong>{levelNames[liveIncident.current_level]}</strong><small>{liveIncident.status==='ACKNOWLEDGED'?'Being handled':liveIncident.status==='RESOLVED'?'Resolved':'Sent — waiting for a care team response'}</small></div></div>}{liveIncident?.current_level===5&&<section className="card" aria-label="Emergency contacts"><strong>In immediate danger, call now.</strong><p>{liveIncident.acknowledged_at?'A care team member has acknowledged.':'No one has acknowledged yet — please call 108/112 now.'}</p><a href="tel:108">Call 108</a> · <a href="tel:112">Call 112</a></section>}</section>;
}

function Placeholder({role,title}:{role:string;title:string}){return <section className="card placeholder"><p className="eyebrow">{role} WORKSPACE</p><h2>{title}</h2><p>This part of the care continuity workspace is planned for a later phase.</p></section>}

type PatientRow = { id: string; name: string };
type SupportNeed = { support_code: string; notes: string };
type PatientDetails = PatientRow & { care_code?: string | null; care_notes: string; clinical_notes?: string | null; mobility_level: string; my_permissions: string[]; support_needs: SupportNeed[] };
type Caregiver = { id: string; user_id?: string | null; is_main_caretaker?: boolean; name: string; kind: string; relationship: string; is_active: boolean; capabilities: string[]; max_activities_per_day: number; max_hours_per_week: number; phone?: string | null };
type WeeklyWindow = { weekday: number; start_min: number; end_min: number };
type Warning = { code: string; message: string; details: unknown };
type Assignment = { id: string; caregiver_id: string; caregiver_name: string; role: string; status: string; is_mine: boolean };
type Activity = { id: string; title: string; category: string; requires_caregiver?: boolean; importance: string; scheduled_start: string; scheduled_end: string; lifecycle_status: string; care_status?: string; source?: string; completed_late?: boolean; preliminary_support_status: string; my_permissions: string[]; assignments: Assignment[]; warnings?: Warning[] };
type HistoryEvent = { id: string; summary: string; event_type: string; occurred_at: string };
type Overview = { upcoming_activities: Activity[]; not_yet_confirmed_count: number; caregivers: Caregiver[]; recent_history: HistoryEvent[] };
// Matches DETECTION_DAYS in services/backup_matcher.py: absences further out are not picked up yet.
const COVER_WINDOW_DAYS = 60;
const withinCoverWindow = (start: string) => { const t = new Date(start).getTime() - Date.now(); return t > 0 && t < COVER_WINDOW_DAYS * 86_400_000; };
function usePatient() {
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{items:PatientRow[]}>('/api/v1/patients') });
  const [params] = useSearchParams();
  const [selected, setSelected] = useState(params.get('patient') ?? '');
  const id = selected || patients.data?.items?.[0]?.id || '';
  const picker = <label>Patient<select value={id} onChange={e=>setSelected(e.target.value)}>{patients.data?.items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>;
  return { patients, id, picker };
}
function PatientProfile() {
  const {id,picker}=usePatient(); const client=useQueryClient();
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});
  const overview=useQuery({queryKey:['overview',id],queryFn:()=>api<Overview>(`/api/v1/patients/${id}/overview`),enabled:!!id});
  const [name,setName]=useState(''); const [notes,setNotes]=useState(''); const [mobility,setMobility]=useState('INDEPENDENT'); const [needs,setNeeds]=useState<string[]>([]); const [message,setMessage]=useState('');
  useEffect(()=>{if(patient.data){setName(patient.data.name);setNotes(patient.data.care_notes??'');setMobility(patient.data.mobility_level??'INDEPENDENT');setNeeds((patient.data.support_needs??[]).map(x=>x.support_code));}},[patient.data]);
  const canEdit=patient.data?.my_permissions?.includes('plan:manage');
  async function save(e:FormEvent){e.preventDefault();setMessage('');try{await api(`/api/v1/patients/${id}`,{method:'PATCH',body:JSON.stringify({name,care_notes:notes,mobility_level:mobility})});await api(`/api/v1/patients/${id}/support-needs`,{method:'PUT',body:JSON.stringify(needs.map(support_code=>({support_code,notes:''})))});await client.invalidateQueries({queryKey:['patient',id]});setMessage('Patient profile saved.');}catch(err){setMessage(err instanceof Error?err.message:'Could not save profile.');}}
  if(!id)return <section className="card">No patient is linked to this account yet.</section>;
  return <><div className="section-head"><div><p className="eyebrow">PATIENT PROFILE</p><h3>Patient and support needs</h3></div>{picker}</div>{message&&<p role="status" className="muted">{message}</p>}{patient.data?.care_code&&<CareCodeCard name={patient.data.name} code={patient.data.care_code} patientId={patient.data.my_permissions?.includes('plan:manage')?id:undefined}/>}<div className="grid"><section className="card"><div className="card-head"><div><p className="eyebrow">PROFILE</p><h3>{patient.data?.name??'Loading…'}</h3></div></div>{patient.data?.clinical_notes&&<p><strong>Clinical notes</strong><br/>{patient.data.clinical_notes}</p>}{canEdit?<form onSubmit={save}><label>Name<input value={name} onChange={e=>setName(e.target.value)} required/></label><label>Mobility<select value={mobility} onChange={e=>setMobility(e.target.value)}><option>INDEPENDENT</option><option>NEEDS_AID</option><option>WHEELCHAIR</option><option>BEDBOUND</option></select></label><label>Shared care notes<textarea value={notes} onChange={e=>setNotes(e.target.value)}/></label><fieldset><legend>Support needs</legend>{['TRANSPORT','MEDICATION_ASSIST','PRESCRIPTION_PICKUP','DAILY_ASSIST','MOBILITY_ASSIST','LAB_ESCORT','SUPPLIES','APPOINTMENT_ESCORT'].map(code=><label key={code}><input type="checkbox" checked={needs.includes(code)} onChange={e=>setNeeds(e.target.checked?[...needs,code]:needs.filter(n=>n!==code))}/>{code.replace(/_/g,' ').toLowerCase()}</label>)}</fieldset><button className="primary">Save profile</button></form>:<p>{patient.data?.care_notes}</p>}</section><section className="card"><p className="eyebrow">NEXT 7 DAYS</p><h3>{overview.data?.upcoming_activities?.length??0} upcoming activities</h3><p>{overview.data?.not_yet_confirmed_count??0} not yet confirmed</p><h4>Caregivers</h4><ul>{overview.data?.caregivers?.map((c:Caregiver)=><li key={c.id}>{c.name} · {c.kind}</li>)}</ul><h4>Recent changes</h4><ul>{overview.data?.recent_history?.slice(0,5).map((h,i)=><li key={i}>{h.summary}</li>)}</ul></section></div></>;
}
function CareNetwork({role}:{role:string}) {
  const {id,picker}=usePatient();
  const me=useQuery({queryKey:['me'],queryFn:()=>api<{id:string}>('/api/v1/auth/me')});
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});
  const network=useQuery({queryKey:['caregivers',id],queryFn:()=>api<{items:Caregiver[]}>(`/api/v1/patients/${id}/caregivers`),enabled:!!id});
  const [message,setMessage]=useState('');
  const [mainId,setMainId]=useState('');
  const currentMain=network.data?.items.find(c=>c.is_main_caretaker)?.id??'';
  useEffect(()=>{setMainId(currentMain);},[currentMain]);
  const [scheduleId,setScheduleId]=useState('');const [overrideStart,setOverrideStart]=useState(nowLocalInput());const [overrideEnd,setOverrideEnd]=useState('');
  const canManage=patient.data?.my_permissions?.includes('network:manage');
  async function preset(c:Caregiver,preset:string){let windows:WeeklyWindow[]=[];if(preset==='Anytime')windows=Array.from({length:7},(_,weekday)=>({weekday,start_min:0,end_min:1440}));if(preset==='Weekdays 9–18')windows=Array.from({length:5},(_,weekday)=>({weekday,start_min:540,end_min:1080}));if(preset==='Weekends only')windows=[5,6].map(weekday=>({weekday,start_min:0,end_min:1440}));if(preset==='Evenings 17–21')windows=Array.from({length:7},(_,weekday)=>({weekday,start_min:1020,end_min:1260}));if(preset==='Mornings 6–12')windows=Array.from({length:7},(_,weekday)=>({weekday,start_min:360,end_min:720}));try{await api(`/api/v1/caregivers/${c.id}/schedule`,{method:'PUT',body:JSON.stringify({windows})});setMessage(`${preset} availability saved.`);}catch(err){setMessage(err instanceof Error?err.message:'Could not save schedule.');}}
  async function markUnavailable(c:Caregiver){try{await api(`/api/v1/caregivers/${c.id}/availability-overrides`,{method:'POST',body:JSON.stringify({start_at:localInputToIso(overrideStart),end_at:localInputToIso(overrideEnd),status:'UNAVAILABLE',reason:'PERSONAL',note:'Added in Care Network'})});setMessage('Unavailable time recorded in History.');}catch(err){setMessage(err instanceof Error?err.message:'Could not add override.');}}
  async function saveMain(){if(!mainId)return;try{await api(`/api/v1/patients/${id}/main-caretaker`,{method:'PUT',body:JSON.stringify({caregiver_id:mainId})});setMessage(`${network.data?.items.find(c=>c.id===mainId)?.name??'Caretaker'} is now the main caretaker.`);}catch(err){setMessage(err instanceof Error?err.message:'Could not save the main caretaker.');}}
  if(!id)return <section className="card">No patient is linked to this account.</section>;
  return <><div className="section-head"><div><p className="eyebrow">CARE NETWORK</p><h3>{role==='CARETAKER'?'My availability':'Caretakers'}</h3></div>{picker}</div>{message&&<p role="status" className="muted">{message}</p>}{role==='PRIMARY_CONTACT'&&canManage&&<section className="card"><h3>Main caretaker</h3><p className="muted">New doses and appointments go to the main caretaker when they are free; otherwise a replacement is asked automatically.</p><div className="md-row"><label>Main caretaker<select value={mainId} onChange={e=>setMainId(e.target.value)}><option value="">Select caretaker</option>{network.data?.items.filter(c=>c.is_active).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button disabled={!mainId} onClick={()=>void saveMain()}>Save main caretaker</button></div></section>}<div className="grid">{network.data?.items.map(c=><section className="card" key={c.id}><div className="card-head"><div><p className="eyebrow">{c.kind} · {c.relationship||'care network'}</p><h3>{c.name}</h3></div><span className="status-pill">{c.is_active?'Active':'Inactive'}</span></div><p>{c.capabilities.map((x:string)=><span className="chip" key={x}>{x.replace(/_/g,' ')}</span>)}</p><p className="muted">Daily limit {c.max_activities_per_day} activities · weekly limit {c.max_hours_per_week} hours {c.phone?`· ${c.phone}`:''}</p>{canManage||c.user_id===me.data?.id?<><div className="chips">{['Anytime','Weekdays 9–18','Weekends only','Evenings 17–21','Mornings 6–12'].map(x=><button key={x} onClick={()=>preset(c,x)}>{x}</button>)}</div><label>Unavailable from<input type="datetime-local" value={overrideStart} onChange={e=>setOverrideStart(e.target.value)}/></label><label>Until<input type="datetime-local" value={overrideEnd} onChange={e=>setOverrideEnd(e.target.value)}/></label><button onClick={()=>void markUnavailable(c)}>Mark unavailable</button><button onClick={()=>setScheduleId(scheduleId===c.id?'':c.id)}>View schedule</button>{scheduleId===c.id&&<ScheduleView caregiverId={c.id}/>}</>:null}</section>)}</div></>;
}
function ScheduleView({caregiverId}:{caregiverId:string}){const q=useQuery({queryKey:['schedule',caregiverId],queryFn:()=>api<{windows:WeeklyWindow[]}>(`/api/v1/caregivers/${caregiverId}/schedule`)});return <ul>{q.data?.windows.map((w,i)=><li key={i}>Day {w.weekday}: {w.start_min}–{w.end_min}</li>)}</ul>}
function CarePlan({role}:{role:string}) {
  const {id,picker}=usePatient(); const client=useQueryClient();
  const activities=useQuery({queryKey:['activities',id],queryFn:()=>api<{items:Activity[]}>(`/api/v1/patients/${id}/activities?limit=100`),enabled:!!id});
  const caregivers=useQuery({queryKey:['caregivers',id],queryFn:()=>api<{items:Caregiver[]}>(`/api/v1/patients/${id}/caregivers`),enabled:!!id});
  const [title,setTitle]=useState('');const [category,setCategory]=useState('APPOINTMENT');const [support,setSupport]=useState('TRANSPORT');const [start,setStart]=useState(nowLocalInput());const [end,setEnd]=useState('');const [caregiverId,setCaregiverId]=useState('');const [message,setMessage]=useState('');
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});const canManage=patient.data?.my_permissions?.includes('plan:manage');const canSchedule=!!canManage;
  async function addActivity(e:FormEvent){e.preventDefault();try{const made=await api<Activity>(`/api/v1/patients/${id}/activities`,{method:'POST',body:JSON.stringify({title,category,scheduled_start:localInputToIso(start),scheduled_end:localInputToIso(end),required_support:[support],requires_caregiver:true,importance:'MEDIUM'})});setMessage(made.warnings?.length?made.warnings.map((w)=>w.message).join(' '):'Activity added.');setTitle('');await client.invalidateQueries({queryKey:['activities',id]});}catch(err){setMessage(err instanceof Error?err.message:'Could not create activity.');}}
  async function assign(activityId:string){if(!caregiverId)return;try{const result=await api<{warnings:Warning[]}>(`/api/v1/activities/${activityId}/assignments`,{method:'POST',body:JSON.stringify({caregiver_id:caregiverId,role:'PRIMARY',confirm_now:true,scope:'THIS'})});setMessage(result.warnings?.length?result.warnings.map((w)=>w.message).join(' '):'Primary support confirmed.');await client.invalidateQueries({queryKey:['activities',id]});}catch(err){setMessage(err instanceof Error?err.message:'Could not assign caregiver.');}}
  const navigate=useNavigate();
  async function findCover(a:Activity){if(!window.confirm(`Look for someone to cover “${a.title}”? Primary contacts are notified and the current caregiver stays on it until a replacement confirms.`))return;const activityId=a.id;try{await api(`/api/v1/activities/${activityId}/cover-requests`,{method:'POST',body:JSON.stringify({note:'Primary contact asked for cover from Care Plan'})});navigate(`/cover?patient=${id}`);}catch(err){setMessage(err instanceof Error?err.message:'Could not open a cover request.');}}
  async function cannotMakeIt(a:Activity,x:Assignment){if(!window.confirm(`Tell the care circle you can't make “${a.title}”? You will be marked unavailable for that time (other tasks then will need cover too), and a replacement search starts right away.`))return;try{await api(`/api/v1/caregivers/${x.caregiver_id}/availability-overrides`,{method:'POST',body:JSON.stringify({start_at:a.scheduled_start,end_at:a.scheduled_end,status:'UNAVAILABLE',reason:'PERSONAL',note:`Can't make ${a.title}`.slice(0,1000)})});await client.invalidateQueries({queryKey:['activities',id]});setMessage('Thanks — the primary contact has been told and a replacement search has started. You stay on the task until someone confirms.');}catch(err){setMessage(err instanceof Error?err.message:'Could not record that you are unavailable.');}}
  async function action(assignmentId:string,verb:string){try{await api(`/api/v1/assignments/${assignmentId}/${verb}`,{method:'POST',body:verb==='decline'?JSON.stringify({reason:'Unable to attend'}):JSON.stringify({})});await client.invalidateQueries({queryKey:['activities',id]});setMessage(`Assignment ${verb} complete.`);}catch(err){setMessage(err instanceof Error?err.message:'Assignment update failed.');}}
  if(!id)return <section className="card">No patient is linked to this account.</section>;
  return <><div className="section-head"><div><p className="eyebrow">CARE PLAN</p><h3>Scheduled support</h3></div>{picker}</div>{message&&<p role="status" className="card">{message}</p>}{canSchedule&&<form className="card" onSubmit={addActivity}><h3>Add another care task</h3><label>Title<input required value={title} onChange={e=>setTitle(e.target.value)}/></label><label>Category<select value={category} onChange={e=>setCategory(e.target.value)}>{['APPOINTMENT','TRANSPORT','PRESCRIPTION','MEDICATION','FOLLOW_UP','DAILY_ROUTINE','MOBILITY','LAB','SUPPLIES','POST_APPOINTMENT','OTHER'].map(x=><option key={x}>{x}</option>)}</select></label><label>Required support<select value={support} onChange={e=>setSupport(e.target.value)}>{['TRANSPORT','MEDICATION_ASSIST','PRESCRIPTION_PICKUP','DAILY_ASSIST','MOBILITY_ASSIST','LAB_ESCORT','SUPPLIES','APPOINTMENT_ESCORT'].map(x=><option key={x}>{x}</option>)}</select></label><label>Start (Asia/Kolkata)<input type="datetime-local" required value={start} onChange={e=>setStart(e.target.value)}/></label><label>End (Asia/Kolkata)<input type="datetime-local" required value={end} onChange={e=>setEnd(e.target.value)}/></label><button className="primary">Create activity</button></form>}<div className="grid">{activities.data?.items.map(a=><section className="card" key={a.id}><div className="card-head"><div><p className="eyebrow">{a.category} · {a.importance}</p><h3>{a.title}</h3></div><span className="status-pill">{a.lifecycle_status}</span></div><p><span className={`md-status md-st-${statusTone(a.care_status,a.completed_late)}`}>{statusLabel(a.care_status,a.completed_late)}</span> <span className="chip">{sourceLabel(a.source)}</span></p><p>{formatAppTime(a.scheduled_start)} – {formatAppTime(a.scheduled_end)}</p><p><strong>{a.preliminary_support_status}</strong> <small>(preliminary — full coverage analysis arrives with the care-gap engine)</small></p><ul>{a.assignments?.map((x)=><li key={x.id}>{x.role}: {x.caregiver_name} · {x.status}{x.status==='PROPOSED'&&canManage&&<button onClick={()=>void action(x.id,'request-confirmation')}>Request confirmation</button>}{x.status==='AWAITING_CONFIRMATION'&&(canManage||x.is_mine)&&<><button onClick={()=>void action(x.id,'confirm')}>Confirm</button>{x.is_mine&&!canManage&&<button onClick={()=>void action(x.id,'decline')}>Decline</button>}{canManage&&<button onClick={()=>void action(x.id,'reject')}>Reject</button>}</>}{x.status==='CONFIRMED'&&canManage&&<button onClick={()=>void action(x.id,'cancel')}>Cancel assignment</button>}{x.status==='CONFIRMED'&&x.is_mine&&x.role==='PRIMARY'&&a.lifecycle_status==='SCHEDULED'&&withinCoverWindow(a.scheduled_start)&&<button onClick={()=>void cannotMakeIt(a,x)}>I can't make it</button>}</li>)}</ul>{canManage&&role==='PRIMARY_CONTACT'&&a.requires_caregiver!==false&&a.lifecycle_status==='SCHEDULED'&&new Date(a.scheduled_start)>new Date()&&<button onClick={()=>void findCover(a)}>Find cover</button>}{canManage&&<div><select aria-label="Assign caregiver" value={caregiverId} onChange={e=>setCaregiverId(e.target.value)}><option value="">Select caregiver</option>{caregivers.data?.items.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select><button onClick={()=>void assign(a.id)}>Assign and confirm primary</button></div>}</section>)}</div></>;
}
function HistoryPage(){const {id,picker}=usePatient();const history=useQuery({queryKey:['history',id],queryFn:()=>api<{items:HistoryEvent[];total:number}>(`/api/v1/patients/${id}/history?limit=100`),enabled:!!id});return <><div className="section-head"><div><p className="eyebrow">HISTORY</p><h3>Recent changes</h3></div>{picker}</div><section className="card"><ul className="history-list">{history.data?.items.map((x)=><li key={x.id}><i className="timeline-dot"/><span>{x.summary}<small>{x.event_type} · {formatAppTime(x.occurred_at)}</small></span></li>)}</ul>{history.data?.total===0&&<p>No activity history yet.</p>}</section></>}
export default App;
