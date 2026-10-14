import { FormEvent, useEffect, useState } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, Bell, CalendarDays, HandHelping, HeartHandshake, History, LayoutDashboard, ListChecks, LogOut, Menu, Scale, Settings, Siren, Timer, UserRound, Users, X, type LucideIcon } from 'lucide-react';
import { CommandCenter } from './CommandCenter.tsx';
import { WorkloadBalancer } from './WorkloadBalancer.tsx';
import { api } from './api/client.ts';
import { formatAppTime, localInputToIso, nowLocalInput } from './lib/time.ts';

type User = { id: string; email: string; name: string; role: string; role_label?: string };
type Patient = { id: string; name: string; birth_year?: number; care_notes: string; clinical_notes?: string | null; is_synthetic: boolean };
const demo: Record<string, string> = { FAMILY: 'anita.iyer@secondpatient.demo', PATIENT: 'ramesh.iyer@secondpatient.demo', HOUSEHELP: 'savitha@secondpatient.demo', NURSE: 'divya.menon@secondpatient.demo', DOCTOR: 'dr.arjun.nair@secondpatient.demo', ADMIN: 'admin@secondpatient.demo' };
const roleLabels: Record<string, string> = { FAMILY: 'Primary contact', PATIENT: 'Patient', HOUSEHELP: 'Personal caretaker', NURSE: 'Healthcare professional', DOCTOR: 'Doctor', ADMIN: 'Administrator' };
type NavItem = { title: string; path: string; icon: LucideIcon };
// Only screens that work today are listed; later-phase screens join the menu when they ship.
const coordinatorNav: NavItem[] = [
  { title: 'Command Center', path: '/command-center', icon: ListChecks },
  { title: 'Dashboard', path: '/', icon: LayoutDashboard },
  { title: 'Incident Center', path: '/incidents', icon: Siren },
  { title: 'Care Plan', path: '/care-plan', icon: CalendarDays },
  { title: 'Workload Balancer', path: '/workload', icon: Scale },
  { title: 'Care Network', path: '/care-network', icon: Users },
  { title: 'Patient Profile', path: '/patient-profile', icon: UserRound },
  { title: 'Escalation Policy', path: '/escalation-policy', icon: Timer },
  { title: 'History', path: '/history', icon: History },
];
const roleNav: Record<string, NavItem[]> = {
  FAMILY: coordinatorNav,
  PATIENT: [{ title: 'Request Help', path: '/request-help', icon: HandHelping }, { title: 'Care Plan', path: '/care-plan', icon: CalendarDays }, { title: 'Incident Center', path: '/incidents', icon: Siren }],
  HOUSEHELP: [{ title: 'My Day', path: '/command-center', icon: ListChecks }, { title: 'Care Plan', path: '/care-plan', icon: CalendarDays }, { title: 'Incident Center', path: '/incidents', icon: Siren }],
  NURSE: [{ title: 'My Day', path: '/command-center', icon: ListChecks }, { title: 'Care Plan', path: '/care-plan', icon: CalendarDays }, { title: 'Incident Center', path: '/incidents', icon: Siren }],
  DOCTOR: [{ title: 'Incident Center', path: '/incidents', icon: Siren }, { title: 'Care Plan', path: '/care-plan', icon: CalendarDays }],
  ADMIN: [...coordinatorNav, { title: 'Admin', path: '/admin', icon: Settings }],
};
const homeFor = (role: string) => (roleNav[role] ?? roleNav.FAMILY)[0].path;
function Login({ onLogin, demoMode }: { onLogin: (u: User) => void; demoMode: boolean }) {
  const [registering, setRegistering] = useState(false); const [name, setName] = useState('');
  const [email, setEmail] = useState(demo.FAMILY); const [password, setPassword] = useState('Demo@1234'); const [error, setError] = useState('');
  async function submit(e: FormEvent) {
    e.preventDefault(); setError('');
    try {
      const u = registering
        ? await api<User>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) })
        : await api<User>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      onLogin(u);
    } catch (err) { setError(err instanceof Error ? err.message : 'Sign-in failed'); }
  }
  return <><main className="login"><div className="brand"><span className="brand-icon"><HeartHandshake/></span><span>CareCircle</span></div><p className="eyebrow">THE CAREGIVER IS THE SECOND PATIENT</p><h1>{registering ? 'Start a care circle.' : 'Support that stays connected.'}</h1><p className="muted">{registering ? 'Create a primary contact account to get started.' : 'Sign in to coordinate the everyday care around someone you love.'}</p><form onSubmit={submit}>{registering&&<label>Your name<input required minLength={1} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label>}<label>Email<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<input type="password" required minLength={8} value={password} onChange={e=>setPassword(e.target.value)}/></label>{error&&<p className="error">{error}</p>}<button className="primary">{registering?'Create account':'Sign in'}</button></form><button className="text-button" onClick={()=>{setRegistering(!registering);setError('');}}>{registering?'Already have an account? Sign in':'Create a family account'}</button>{demoMode&&!registering&&<><p className="eyebrow demo-label">DEMO ACCOUNTS</p><div className="chips">{Object.keys(demo).map(role=><button key={role} onClick={()=>setEmail(demo[role])}>{roleLabels[role]}</button>)}</div><p className="muted small">Demo password: Demo@1234</p></>}</main><div className="login-disclaimer">Operational care-coordination tool — not a diagnostic or emergency service. Demo data is fictional.</div></>;
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
  const menu = roleNav[user.role] ?? roleNav.FAMILY;
  const roleLabel = user.role_label ?? roleLabels[user.role] ?? user.role;
  const current = menu.find(item => item.path === location.pathname);
  const page = (path: string) => {
    switch (path) {
      case '/command-center': return <CommandCenter/>;
      case '/': return <Dashboard/>;
      case '/workload': return <WorkloadBalancer/>;
      case '/incidents': return <IncidentCenter/>;
      case '/request-help': return <HelpPage/>;
      case '/escalation-policy': return <EscalationPolicyPage/>;
      case '/admin': return <AdminDemoPanel/>;
      case '/patient-profile': return <PatientProfile role={user.role}/>;
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
function AdminDemoPanel(){
  const client=useQueryClient();const navigate=useNavigate();const meta=useQuery({queryKey:['meta'],queryFn:()=>api<{demo_mode:boolean;escalation_time_scale:number}>('/api/v1/meta')});
  const [scale,setScale]=useState(1);const [notice,setNotice]=useState('');
  useEffect(()=>{if(meta.data)setScale(meta.data.escalation_time_scale);},[meta.data]);
  async function saveScale(){await api('/api/v1/admin/demo/escalation-speed',{method:'POST',body:JSON.stringify({scale})});await client.invalidateQueries({queryKey:['meta']});setNotice(`Demo timer scale set to ${scale}×.`);}
  async function scenario(name:string){const result=await api<{incident_id?:string;status?:string}>(`/api/v1/admin/demo/scenarios/${name}`,{method:'POST'});setNotice(result.status==='reset'?'Synthetic demo incidents reset.':`Scenario ${name.replace(/_/g,' ')} ${result.status==='cleared'?'cleared':'ready'}.`);await client.invalidateQueries({queryKey:['incidents']});await client.invalidateQueries({queryKey:['notifications']});await client.invalidateQueries({queryKey:['command-center']});if(result.incident_id)navigate('/incidents');else if(name.startsWith('command_center'))navigate('/command-center');}
  if(!meta.data?.demo_mode)return <section className="card"><h2>Admin</h2><p>Demo controls are available only in demo mode.</p></section>;
  return <section className="card"><p className="eyebrow">SYNTHETIC DATA ONLY</p><h2>Admin demo panel</h2><label>Escalation time scale: {scale}×<input type="range" min="0.05" max="1" step="0.05" value={scale} onChange={e=>setScale(Number(e.target.value))}/></label><button className="primary" onClick={()=>void saveScale().catch(()=>setNotice('Could not change demo timer scale.'))}>Save timer scale</button><h3>Run a scripted scenario</h3><div className="chips">{[['daily_help','Daily help'],['missed_task','Missed task'],['health_concern','Health concern'],['logistics_failure','Logistics failure'],['sos','SOS'],['command_center_messy_day','Command Center · messy day']].map(([name,label])=><button key={name} onClick={()=>void scenario(name).catch(()=>setNotice('Scenario could not be created.'))}>{label}</button>)}</div><button onClick={()=>void scenario('command_center_clear_day').catch(()=>setNotice('Command Center demo could not be cleared.'))}>Clear Command Center demo day</button> <button onClick={()=>void scenario('reset_incidents').catch(()=>setNotice('Demo incidents could not be reset.'))}>Reset synthetic incidents</button>{notice&&<p role="status">{notice}</p>}</section>;
}

type PolicyConfig={ack_minutes:Record<string,number>;resolve_minutes:Record<string,number>;family_contact_delay_fraction:number;quiet_hours:{start:string;end:string}};
function EscalationPolicyPage(){
  const client=useQueryClient();const patients=useQuery({queryKey:['patients'],queryFn:()=>api<{items:Patient[]}>('/api/v1/patients')});const patientItems=patients.data?.items??[];const [selected,setSelected]=useState('');const patientId=selected||patientItems[0]?.id;
  const policy=useQuery({queryKey:['escalation-policy',patientId],queryFn:()=>api<{config:PolicyConfig;version:number;is_system_default:boolean}>(`/api/v1/patients/${patientId}/escalation-policy`),enabled:!!patientId});
  const [draft,setDraft]=useState<PolicyConfig|null>(null);const [saved,setSaved]=useState('');
  useEffect(()=>{if(policy.data)setDraft(policy.data.config);},[policy.data]);
  function updateTimer(kind:'ack_minutes'|'resolve_minutes',level:string,value:number){if(!draft)return;setDraft({...draft,[kind]:{...draft[kind],[level]:value}});}
  async function save(){if(!patientId||!draft)return;await api(`/api/v1/patients/${patientId}/escalation-policy`,{method:'PUT',body:JSON.stringify(draft)});await client.invalidateQueries({queryKey:['escalation-policy',patientId]});setSaved('Policy saved. Changes are recorded in History.');}
  async function reset(){if(!patientId)return;await api(`/api/v1/patients/${patientId}/escalation-policy/reset`,{method:'POST'});await client.invalidateQueries({queryKey:['escalation-policy',patientId]});setSaved('System default restored.');}
  return <section className="card"><p className="eyebrow">COORDINATION SETTINGS</p><h2>Escalation Policy</h2><p>Timers set how long a care team has to acknowledge or resolve a request. L5 emergency acknowledgement cadence cannot exceed five minutes.</p>{patientItems.length>1&&<label>Patient<select value={patientId??''} onChange={e=>setSelected(e.target.value)}>{patientItems.map(patient=><option key={patient.id} value={patient.id}>{patient.name}</option>)}</select></label>}{policy.isLoading||!draft?<div className="skeleton"/>:<><div className="grid">{[1,2,3,4,5].map(level=><section className="card" key={level}><h3>{levelNames[level]}</h3><label>Acknowledgement minutes<input type="number" min="1" max={level===5?5:1440} value={draft.ack_minutes[String(level)]} onChange={e=>updateTimer('ack_minutes',String(level),Number(e.target.value))}/></label><label>Resolution minutes<input type="number" min="1" max="1440" value={draft.resolve_minutes[String(level)]} onChange={e=>updateTimer('resolve_minutes',String(level),Number(e.target.value))}/></label></section>)}</div><div className="grid"><label>Quiet hours start<input type="time" value={draft.quiet_hours.start} onChange={e=>setDraft({...draft,quiet_hours:{...draft.quiet_hours,start:e.target.value}})}/></label><label>Quiet hours end<input type="time" value={draft.quiet_hours.end} onChange={e=>setDraft({...draft,quiet_hours:{...draft.quiet_hours,end:e.target.value}})}/></label></div><button className="primary" onClick={()=>void save().catch(()=>setSaved('Could not save this policy. Check timer limits and try again.'))}>Save policy</button> <button onClick={()=>void reset().catch(()=>setSaved('Could not reset this policy.'))}>Reset to system default</button>{saved&&<p role="status">{saved}</p>}</>}</section>;
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
  const [message,setMessage]=useState('');const [incident,setIncident]=useState<IncidentRow|null>(null);const [error,setError]=useState('');const [countdown,setCountdown]=useState<number|null>(null);
  const tracked=useQuery({queryKey:['patient-incidents'],queryFn:()=>api<{items:IncidentRow[]}>('/api/v1/incidents'),enabled:!!incident,refetchInterval:5000});
  const liveIncident=tracked.data?.items.find(item=>item.id===incident?.id)??incident;
  const patientId=patients.data?.items[0]?.id;
  useEffect(()=>{
    if(countdown===null||!patientId)return;
    if(countdown===0){setCountdown(null);void api<IncidentRow>(`/api/v1/patients/${patientId}/sos`,{method:'POST'}).then(setIncident).catch(()=>setError('Could not reach CareCircle — call 108/112 or your family directly.'));return;}
    const timer=window.setTimeout(()=>setCountdown(countdown-1),1000);return()=>window.clearTimeout(timer);
  },[countdown,patientId]);
  async function send(text=message){if(!patientId||!text.trim())return;setError('');try{const item=await api<IncidentRow>(`/api/v1/patients/${patientId}/messages`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({body:text.trim(),channel:'TEXT'})});setIncident(item);setMessage('');}catch{setError('Could not reach CareCircle — call 108/112 or your family directly.');}}
  const chips=['I need water','Help me to the bathroom','I missed my medicine','I feel dizzy','Nobody came',"I'm fine/took my medicine"];
  return <section className="card"><p className="eyebrow">PATIENT HELP</p><h2>Tell us what you need</h2><p>CareCircle routes your message to the right people. It is not a medical diagnosis and cannot replace emergency services. In immediate danger call 108 / 112.</p><div className="chips">{chips.map(chip=><button key={chip} onClick={()=>void send(chip)}>{chip}</button>)}</div><label>Your message<textarea maxLength={1000} value={message} onChange={e=>setMessage(e.target.value)} rows={4}/></label><button className="primary" disabled={!message.trim()} onClick={()=>void send()}>Send request</button><div className="card" style={{marginTop:20,borderColor:'#b42318'}}><h3>Emergency SOS</h3>{countdown===null?<button className="primary" onClick={()=>{setError('');setCountdown(3);}}>Start SOS · 3 second countdown</button>:<><p role="status">SOS will be sent in {countdown}…</p><button onClick={()=>setCountdown(null)}>Cancel SOS</button></>}</div>{error&&<p role="alert" className="error">{error}</p>}{liveIncident&&<div className="system" role="status"><div><strong>{levelNames[liveIncident.current_level]}</strong><small>{liveIncident.status==='ACKNOWLEDGED'?'Being handled':liveIncident.status==='RESOLVED'?'Resolved':'Sent — waiting for a care team response'}</small></div></div>}{liveIncident?.current_level===5&&<section className="card" aria-label="Emergency contacts"><strong>In immediate danger, call now.</strong><p>{liveIncident.acknowledged_at?'A care team member has acknowledged.':'No one has acknowledged yet — please call 108/112 now.'}</p><a href="tel:108">Call 108</a> · <a href="tel:112">Call 112</a></section>}</section>;
}

function Dashboard() {
  const patients = useQuery({ queryKey:['patients'], queryFn:()=>api<{items:Patient[];total:number}>('/api/v1/patients') });
  const [selected, setSelected] = useState(''); const id=selected||patients.data?.items[0]?.id;
  const team = useQuery({queryKey:['team',id],queryFn:()=>api<{items:{name:string;team_role:string;role_label?:string}[]}>(`/api/v1/patients/${id}/care-team`),enabled:!!id});
  const history = useQuery({queryKey:['history',id],queryFn:()=>api<{items:{summary:string;occurred_at:string}[]}>(`/api/v1/patients/${id}/history`),enabled:!!id});
  const health = useQuery({queryKey:['health'],queryFn:()=>api<{status:string}>('/api/health')});
  const openIncidents = useQuery({queryKey:['dashboard-incidents',id],queryFn:()=>api<{items:IncidentRow[]}>(`/api/v1/incidents?patient_id=${id}&status=OPEN`),enabled:!!id});
  return <><section className="welcome"><div><p className="eyebrow">A LITTLE MORE PEACE OF MIND</p><h1>Care works better together.</h1><p>Keep your family's support connected, informed, and ready to help.</p></div><div className="welcome-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="heart"><HeartHandshake size={46}/></div></div></section><div className="section-head"><div><p className="eyebrow">PATIENTS IN YOUR CARE</p><h3>Your people</h3></div><select aria-label="Select patient" value={id??''} onChange={e=>setSelected(e.target.value)}>{patients.data?.items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>{patients.isLoading?<div className="card skeleton"/>:patients.data?.items.length?<section className="patient-card"><div className="patient-avatar">{patients.data.items.find(p=>p.id===id)?.name.split(' ').map(s=>s[0]).join('')}</div><div className="patient-info"><span className="status-pill"><i/> Care circle active</span><h3>{patients.data.items.find(p=>p.id===id)?.name}</h3><p>{patients.data.items.find(p=>p.id===id)?.care_notes}</p></div><div className="patient-age">{patients.data.items.find(p=>p.id===id)?.birth_year?new Date().getFullYear()-patients.data.items.find(p=>p.id===id)!.birth_year!+' years':''}</div></section>:<div className="card empty">Your patient list is empty. Add a patient when you are ready to organize their support.</div>}<div className="grid"><section className="card"><div className="card-head"><div><p className="eyebrow">YOUR SUPPORT NETWORK</p><h3>Care team</h3></div><Users className="soft-icon"/></div>{team.isLoading?<div className="skeleton"/>:<ul className="team-list">{team.data?.items.map((m,i)=><li key={m.name}><span className={'person p'+i}>{m.name[0]}</span><span><strong>{m.name}</strong><small>{m.role_label ?? m.team_role.toLowerCase().replace('_',' ')}</small></span><i className="online"/></li>)}</ul>}</section><section className="card"><div className="card-head"><div><p className="eyebrow">RECENT ACTIVITY</p><h3>History</h3></div><Activity className="soft-icon"/></div>{history.isLoading?<div className="skeleton"/>:<ul className="history-list">{history.data?.items.length?history.data.items.slice(0,4).map((h,i)=><li key={i}><i className="timeline-dot"/><span>{h.summary}<small>{new Date(h.occurred_at).toLocaleString()}</small></span></li>):<li className="muted">No activity yet</li>}</ul>}</section></div><section className="card"><p className="eyebrow">COVERAGE COORDINATION</p><h3>Open incidents</h3><p>{openIncidents.data?.items.length ?? 0} requests need follow-up.</p><Link to="/incidents">Review incident center</Link></section><section className="system"><div><span className="system-icon"><Activity/></span><span><strong>System status</strong><small>Care workspace is running normally</small></span></div><span className="status-pill"><i/> {health.data?.status==='ok'?'All systems operational':'Checking'}</span></section></>;
}
function Placeholder({role,title}:{role:string;title:string}){return <section className="card placeholder"><p className="eyebrow">{role} WORKSPACE</p><h2>{title}</h2><p>This part of the care continuity workspace is planned for a later phase.</p></section>}

type PatientRow = { id: string; name: string };
type SupportNeed = { support_code: string; notes: string };
type PatientDetails = PatientRow & { care_notes: string; clinical_notes?: string | null; mobility_level: string; my_permissions: string[]; support_needs: SupportNeed[] };
type Caregiver = { id: string; user_id?: string | null; name: string; kind: string; relationship: string; is_active: boolean; capabilities: string[]; max_activities_per_day: number; max_hours_per_week: number; phone?: string | null };
type WeeklyWindow = { weekday: number; start_min: number; end_min: number };
type Warning = { code: string; message: string; details: unknown };
type Assignment = { id: string; caregiver_id: string; caregiver_name: string; role: string; status: string; is_mine: boolean };
type Activity = { id: string; title: string; category: string; importance: string; scheduled_start: string; scheduled_end: string; lifecycle_status: string; preliminary_support_status: string; my_permissions: string[]; assignments: Assignment[]; warnings?: Warning[] };
type HistoryEvent = { id: string; summary: string; event_type: string; occurred_at: string };
type Overview = { upcoming_activities: Activity[]; not_yet_confirmed_count: number; caregivers: Caregiver[]; recent_history: HistoryEvent[] };
function usePatient() {
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{items:PatientRow[]}>('/api/v1/patients') });
  const [selected, setSelected] = useState('');
  const id = selected || patients.data?.items?.[0]?.id || '';
  const picker = <label>Patient<select value={id} onChange={e=>setSelected(e.target.value)}>{patients.data?.items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>;
  return { patients, id, picker };
}
function PatientProfile({role}:{role:string}) {
  const {id,picker}=usePatient(); const client=useQueryClient();
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});
  const overview=useQuery({queryKey:['overview',id],queryFn:()=>api<Overview>(`/api/v1/patients/${id}/overview`),enabled:!!id});
  const [name,setName]=useState(''); const [notes,setNotes]=useState(''); const [mobility,setMobility]=useState('INDEPENDENT'); const [needs,setNeeds]=useState<string[]>([]); const [message,setMessage]=useState('');
  useEffect(()=>{if(patient.data){setName(patient.data.name);setNotes(patient.data.care_notes??'');setMobility(patient.data.mobility_level??'INDEPENDENT');setNeeds((patient.data.support_needs??[]).map(x=>x.support_code));}},[patient.data]);
  const canEdit=patient.data?.my_permissions?.includes('plan:manage')||role==='ADMIN';
  async function save(e:FormEvent){e.preventDefault();setMessage('');try{await api(`/api/v1/patients/${id}`,{method:'PATCH',body:JSON.stringify({name,care_notes:notes,mobility_level:mobility})});await api(`/api/v1/patients/${id}/support-needs`,{method:'PUT',body:JSON.stringify(needs.map(support_code=>({support_code,notes:''})))});await client.invalidateQueries({queryKey:['patient',id]});setMessage('Patient profile saved.');}catch(err){setMessage(err instanceof Error?err.message:'Could not save profile.');}}
  if(!id)return <section className="card">No patient is linked to this account yet.</section>;
  return <><div className="section-head"><div><p className="eyebrow">PATIENT PROFILE</p><h3>Patient and support needs</h3></div>{picker}</div>{message&&<p role="status" className="muted">{message}</p>}<div className="grid"><section className="card"><div className="card-head"><div><p className="eyebrow">PROFILE</p><h3>{patient.data?.name??'Loading…'}</h3></div></div>{patient.data?.clinical_notes&&<p><strong>Clinical notes</strong><br/>{patient.data.clinical_notes}</p>}{canEdit?<form onSubmit={save}><label>Name<input value={name} onChange={e=>setName(e.target.value)} required/></label><label>Mobility<select value={mobility} onChange={e=>setMobility(e.target.value)}><option>INDEPENDENT</option><option>NEEDS_AID</option><option>WHEELCHAIR</option><option>BEDBOUND</option></select></label><label>Shared care notes<textarea value={notes} onChange={e=>setNotes(e.target.value)}/></label><fieldset><legend>Support needs</legend>{['TRANSPORT','MEDICATION_ASSIST','PRESCRIPTION_PICKUP','DAILY_ASSIST','MOBILITY_ASSIST','LAB_ESCORT','SUPPLIES','CLINICAL_VISIT','APPOINTMENT_ESCORT'].map(code=><label key={code}><input type="checkbox" checked={needs.includes(code)} onChange={e=>setNeeds(e.target.checked?[...needs,code]:needs.filter(n=>n!==code))}/>{code.replace(/_/g,' ').toLowerCase()}</label>)}</fieldset><button className="primary">Save profile</button></form>:<p>{patient.data?.care_notes}</p>}</section><section className="card"><p className="eyebrow">NEXT 7 DAYS</p><h3>{overview.data?.upcoming_activities?.length??0} upcoming activities</h3><p>{overview.data?.not_yet_confirmed_count??0} not yet confirmed</p><h4>Caregivers</h4><ul>{overview.data?.caregivers?.map((c:Caregiver)=><li key={c.id}>{c.name} · {c.kind}</li>)}</ul><h4>Recent changes</h4><ul>{overview.data?.recent_history?.slice(0,5).map((h,i)=><li key={i}>{h.summary}</li>)}</ul></section></div></>;
}
function CareNetwork({role}:{role:string}) {
  const {id,picker}=usePatient(); const client=useQueryClient();
  const me=useQuery({queryKey:['me'],queryFn:()=>api<{id:string}>('/api/v1/auth/me')});
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});
  const network=useQuery({queryKey:['caregivers',id],queryFn:()=>api<{items:Caregiver[]}>(`/api/v1/patients/${id}/caregivers`),enabled:!!id});
  const [name,setName]=useState('');const [kind,setKind]=useState('FAMILY');const [capability,setCapability]=useState('TRANSPORT');const [message,setMessage]=useState('');
  const [scheduleId,setScheduleId]=useState('');const [overrideStart,setOverrideStart]=useState(nowLocalInput());const [overrideEnd,setOverrideEnd]=useState('');
  const canManage=patient.data?.my_permissions?.includes('network:manage')||role==='ADMIN';
  async function addCaregiver(e:FormEvent){e.preventDefault();try{await api(`/api/v1/patients/${id}/caregivers`,{method:'POST',body:JSON.stringify({name,kind,capabilities:[capability],relationship:'care network',max_activities_per_day:3,max_hours_per_week:40})});setName('');setMessage('Caregiver added.');await client.invalidateQueries({queryKey:['caregivers',id]});}catch(err){setMessage(err instanceof Error?err.message:'Could not add caregiver.');}}
  async function preset(c:Caregiver,preset:string){let windows:WeeklyWindow[]=[];if(preset==='Anytime')windows=Array.from({length:7},(_,weekday)=>({weekday,start_min:0,end_min:1440}));if(preset==='Weekdays 9–18')windows=Array.from({length:5},(_,weekday)=>({weekday,start_min:540,end_min:1080}));if(preset==='Weekends only')windows=[5,6].map(weekday=>({weekday,start_min:0,end_min:1440}));if(preset==='Evenings 17–21')windows=Array.from({length:7},(_,weekday)=>({weekday,start_min:1020,end_min:1260}));if(preset==='Mornings 6–12')windows=Array.from({length:7},(_,weekday)=>({weekday,start_min:360,end_min:720}));try{await api(`/api/v1/caregivers/${c.id}/schedule`,{method:'PUT',body:JSON.stringify({windows})});setMessage(`${preset} availability saved.`);}catch(err){setMessage(err instanceof Error?err.message:'Could not save schedule.');}}
  async function markUnavailable(c:Caregiver){try{await api(`/api/v1/caregivers/${c.id}/availability-overrides`,{method:'POST',body:JSON.stringify({start_at:localInputToIso(overrideStart),end_at:localInputToIso(overrideEnd),status:'UNAVAILABLE',reason:'PERSONAL',note:'Added in Care Network'})});setMessage('Unavailable time recorded in History.');}catch(err){setMessage(err instanceof Error?err.message:'Could not add override.');}}
  if(!id)return <section className="card">No patient is linked to this account.</section>;
  return <><div className="section-head"><div><p className="eyebrow">CARE NETWORK</p><h3>People and availability</h3></div>{picker}</div>{message&&<p role="status" className="muted">{message}</p>}{canManage&&<form className="card" onSubmit={addCaregiver}><h3>Add a caregiver</h3><label>Name<input required value={name} onChange={e=>setName(e.target.value)}/></label><label>Kind<select value={kind} onChange={e=>setKind(e.target.value)}>{['FAMILY','HOUSEHELP','NURSE','NEIGHBOUR','VOLUNTEER','OTHER'].map(x=><option key={x}>{x}</option>)}</select></label><label>Capability<select value={capability} onChange={e=>setCapability(e.target.value)}>{['TRANSPORT','MEDICATION_ASSIST','PRESCRIPTION_PICKUP','DAILY_ASSIST','MOBILITY_ASSIST','LAB_ESCORT','SUPPLIES','CLINICAL_VISIT','APPOINTMENT_ESCORT'].map(x=><option key={x}>{x}</option>)}</select></label><button className="primary">Add caregiver</button></form>}<div className="grid">{network.data?.items.map(c=><section className="card" key={c.id}><div className="card-head"><div><p className="eyebrow">{c.kind} · {c.relationship||'care network'}</p><h3>{c.name}</h3></div><span className="status-pill">{c.is_active?'Active':'Inactive'}</span></div><p>{c.capabilities.map((x:string)=><span className="chip" key={x}>{x.replace(/_/g,' ')}</span>)}</p><p className="muted">Daily limit {c.max_activities_per_day} activities · weekly limit {c.max_hours_per_week} hours {c.phone?`· ${c.phone}`:''}</p>{canManage||c.user_id===me.data?.id?<><div className="chips">{['Anytime','Weekdays 9–18','Weekends only','Evenings 17–21','Mornings 6–12'].map(x=><button key={x} onClick={()=>preset(c,x)}>{x}</button>)}</div><label>Unavailable from<input type="datetime-local" value={overrideStart} onChange={e=>setOverrideStart(e.target.value)}/></label><label>Until<input type="datetime-local" value={overrideEnd} onChange={e=>setOverrideEnd(e.target.value)}/></label><button onClick={()=>void markUnavailable(c)}>Mark unavailable</button><button onClick={()=>setScheduleId(scheduleId===c.id?'':c.id)}>View schedule</button>{scheduleId===c.id&&<ScheduleView caregiverId={c.id}/>}</>:null}</section>)}</div></>;
}
function ScheduleView({caregiverId}:{caregiverId:string}){const q=useQuery({queryKey:['schedule',caregiverId],queryFn:()=>api<{windows:WeeklyWindow[]}>(`/api/v1/caregivers/${caregiverId}/schedule`)});return <ul>{q.data?.windows.map((w,i)=><li key={i}>Day {w.weekday}: {w.start_min}–{w.end_min}</li>)}</ul>}
function CarePlan({role}:{role:string}) {
  const {id,picker}=usePatient(); const client=useQueryClient();
  const activities=useQuery({queryKey:['activities',id],queryFn:()=>api<{items:Activity[]}>(`/api/v1/patients/${id}/activities?limit=100`),enabled:!!id});
  const caregivers=useQuery({queryKey:['caregivers',id],queryFn:()=>api<{items:Caregiver[]}>(`/api/v1/patients/${id}/caregivers`),enabled:!!id});
  const [title,setTitle]=useState('');const [category,setCategory]=useState('APPOINTMENT');const [support,setSupport]=useState('TRANSPORT');const [start,setStart]=useState(nowLocalInput());const [end,setEnd]=useState('');const [caregiverId,setCaregiverId]=useState('');const [message,setMessage]=useState('');
  const patient=useQuery({queryKey:['patient',id],queryFn:()=>api<PatientDetails>(`/api/v1/patients/${id}`),enabled:!!id});const canManage=patient.data?.my_permissions?.includes('plan:manage')||role==='ADMIN';
  async function addActivity(e:FormEvent){e.preventDefault();try{const made=await api<Activity>(`/api/v1/patients/${id}/activities`,{method:'POST',body:JSON.stringify({title,category,scheduled_start:localInputToIso(start),scheduled_end:localInputToIso(end),required_support:[support],requires_caregiver:true,importance:'MEDIUM'})});setMessage(made.warnings?.length?made.warnings.map((w)=>w.message).join(' '):'Activity added.');setTitle('');await client.invalidateQueries({queryKey:['activities',id]});}catch(err){setMessage(err instanceof Error?err.message:'Could not create activity.');}}
  async function assign(activityId:string){if(!caregiverId)return;try{const result=await api<{warnings:Warning[]}>(`/api/v1/activities/${activityId}/assignments`,{method:'POST',body:JSON.stringify({caregiver_id:caregiverId,role:'PRIMARY',confirm_now:true,scope:'THIS'})});setMessage(result.warnings?.length?result.warnings.map((w)=>w.message).join(' '):'Primary support confirmed.');await client.invalidateQueries({queryKey:['activities',id]});}catch(err){setMessage(err instanceof Error?err.message:'Could not assign caregiver.');}}
  async function action(assignmentId:string,verb:string){try{await api(`/api/v1/assignments/${assignmentId}/${verb}`,{method:'POST',body:verb==='decline'?JSON.stringify({reason:'Unable to attend'}):JSON.stringify({})});await client.invalidateQueries({queryKey:['activities',id]});setMessage(`Assignment ${verb} complete.`);}catch(err){setMessage(err instanceof Error?err.message:'Assignment update failed.');}}
  if(!id)return <section className="card">No patient is linked to this account.</section>;
  return <><div className="section-head"><div><p className="eyebrow">CARE PLAN</p><h3>Scheduled support</h3></div>{picker}</div>{message&&<p role="status" className="card">{message}</p>}{canManage&&<form className="card" onSubmit={addActivity}><h3>Add activity</h3><label>Title<input required value={title} onChange={e=>setTitle(e.target.value)}/></label><label>Category<select value={category} onChange={e=>setCategory(e.target.value)}>{['APPOINTMENT','TRANSPORT','PRESCRIPTION','MEDICATION','FOLLOW_UP','DAILY_ROUTINE','MOBILITY','LAB','SUPPLIES','POST_APPOINTMENT','OTHER'].map(x=><option key={x}>{x}</option>)}</select></label><label>Required support<select value={support} onChange={e=>setSupport(e.target.value)}>{['TRANSPORT','MEDICATION_ASSIST','PRESCRIPTION_PICKUP','DAILY_ASSIST','MOBILITY_ASSIST','LAB_ESCORT','SUPPLIES','CLINICAL_VISIT','APPOINTMENT_ESCORT'].map(x=><option key={x}>{x}</option>)}</select></label><label>Start (Asia/Kolkata)<input type="datetime-local" required value={start} onChange={e=>setStart(e.target.value)}/></label><label>End (Asia/Kolkata)<input type="datetime-local" required value={end} onChange={e=>setEnd(e.target.value)}/></label><button className="primary">Create activity</button></form>}<div className="grid">{activities.data?.items.map(a=><section className="card" key={a.id}><div className="card-head"><div><p className="eyebrow">{a.category} · {a.importance}</p><h3>{a.title}</h3></div><span className="status-pill">{a.lifecycle_status}</span></div><p>{formatAppTime(a.scheduled_start)} – {formatAppTime(a.scheduled_end)}</p><p><strong>{a.preliminary_support_status}</strong> <small>(preliminary — full coverage analysis arrives with the care-gap engine)</small></p><ul>{a.assignments?.map((x)=><li key={x.id}>{x.role}: {x.caregiver_name} · {x.status}{x.status==='PROPOSED'&&canManage&&<button onClick={()=>void action(x.id,'request-confirmation')}>Request confirmation</button>}{x.status==='AWAITING_CONFIRMATION'&&(canManage||x.is_mine)&&<><button onClick={()=>void action(x.id,'confirm')}>Confirm</button>{x.is_mine&&!canManage&&<button onClick={()=>void action(x.id,'decline')}>Decline</button>}{canManage&&<button onClick={()=>void action(x.id,'reject')}>Reject</button>}</>}{x.status==='CONFIRMED'&&canManage&&<button onClick={()=>void action(x.id,'cancel')}>Cancel assignment</button>}</li>)}</ul>{canManage&&<div><select aria-label="Assign caregiver" value={caregiverId} onChange={e=>setCaregiverId(e.target.value)}><option value="">Select caregiver</option>{caregivers.data?.items.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select><button onClick={()=>void assign(a.id)}>Assign and confirm primary</button></div>}</section>)}</div></>;
}
function HistoryPage(){const {id,picker}=usePatient();const history=useQuery({queryKey:['history',id],queryFn:()=>api<{items:HistoryEvent[];total:number}>(`/api/v1/patients/${id}/history?limit=100`),enabled:!!id});return <><div className="section-head"><div><p className="eyebrow">HISTORY</p><h3>Recent changes</h3></div>{picker}</div><section className="card"><ul className="history-list">{history.data?.items.map((x)=><li key={x.id}><i className="timeline-dot"/><span>{x.summary}<small>{x.event_type} · {formatAppTime(x.occurred_at)}</small></span></li>)}</ul>{history.data?.total===0&&<p>No activity history yet.</p>}</section></>}
export default App;
