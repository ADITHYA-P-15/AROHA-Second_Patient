import { FormEvent, useState } from 'react';
import { Link, Route, Routes, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, Bell, HeartHandshake, LogOut, Users } from 'lucide-react';
import { api } from './api/client.ts';

type User = { id: string; email: string; name: string; role: string };
type Patient = { id: string; name: string; birth_year?: number; care_notes: string; clinical_notes?: string | null; is_synthetic: boolean };
const demo: Record<string, string> = { FAMILY: 'anita.iyer@secondpatient.demo', PATIENT: 'ramesh.iyer@secondpatient.demo', HOUSEHELP: 'savitha@secondpatient.demo', NURSE: 'divya.menon@secondpatient.demo', DOCTOR: 'dr.arjun.nair@secondpatient.demo', ADMIN: 'admin@secondpatient.demo' };
const roleNav: Record<string, [string,string][]> = {
  FAMILY: [['Dashboard','/'],['Patient Profile','/patient-profile'],['Care Network','/care-network'],['Care Plan','/care-plan'],['Risk & Resolution','/risk-resolution'],['Dependency Graph','/dependency-graph'],['AI Assistant','/ai-assistant'],['History','/history']],
  PATIENT: [['My Day','/'],['Care Plan','/care-plan'],['Request Help','/request-help'],['Voice Note to Doctor','/voice-note'],['Medicines','/medicines']],
  HOUSEHELP: [['My Tasks','/'],['Availability','/availability'],['Cover Requests','/cover-requests']],
  NURSE: [['My Patients','/'],['Visits','/visits'],['Escalations','/escalations'],['Availability','/availability']],
  DOCTOR: [['Patients','/'],['Appointments & Follow-ups','/appointments'],['Instructions','/instructions'],['Voice Notes','/voice-notes']],
  ADMIN: [['Dashboard','/'],['Patient Profile','/patient-profile'],['Care Network','/care-network'],['Care Plan','/care-plan'],['Risk & Resolution','/risk-resolution'],['Dependency Graph','/dependency-graph'],['AI Assistant','/ai-assistant'],['History','/history'],['Admin','/admin']]
};
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
  return <><main className="login"><div className="brand"><span className="brand-icon"><HeartHandshake/></span><span>The Second Patient</span></div><p className="eyebrow">CARE CONTINUITY, TOGETHER</p><h1>{registering ? 'Start a care circle.' : 'Support that stays connected.'}</h1><p className="muted">{registering ? 'Create a family coordinator account to get started.' : 'Sign in to coordinate the everyday care around someone you love.'}</p><form onSubmit={submit}>{registering&&<label>Your name<input required minLength={1} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label>}<label>Email<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<input type="password" required minLength={8} value={password} onChange={e=>setPassword(e.target.value)}/></label>{error&&<p className="error">{error}</p>}<button className="primary">{registering?'Create account':'Sign in'}</button></form><button className="text-button" onClick={()=>{setRegistering(!registering);setError('');}}>{registering?'Already have an account? Sign in':'Create a family account'}</button>{demoMode&&!registering&&<><p className="eyebrow demo-label">DEMO ACCOUNTS</p><div className="chips">{Object.keys(demo).map(role=><button key={role} onClick={()=>setEmail(demo[role])}>{role}</button>)}</div><p className="muted small">Demo password: Demo@1234</p></>}</main><div className="login-disclaimer">Operational care-coordination tool — not a diagnostic or emergency service. Demo data is fictional.</div></>;
}
function App() {
  const queryClient = useQueryClient(); const navigate = useNavigate();
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<User>('/api/v1/auth/me'), retry: false });
  const meta = useQuery({ queryKey: ['meta'], queryFn: () => api<{phase:number;version:string;demo_mode:boolean}>('/api/v1/meta') });
  if (me.isLoading) return <div className="loading">Loading your workspace…</div>;
  if (me.isError) return <Login demoMode={meta.data?.demo_mode ?? false} onLogin={u=>{ queryClient.setQueryData(['me'],u); navigate('/'); }} />;
  const user = me.data!;
  const logout = async()=>{ await api('/api/v1/auth/logout',{method:'POST'}); queryClient.clear(); navigate('/'); };
  const menu=roleNav[user.role] ?? roleNav.FAMILY;
  return <div className="app"><aside><div className="brand"><span className="brand-icon"><HeartHandshake/></span><span>Second Patient</span></div>{meta.data?.demo_mode&&<div className="demo-tag">DEMO · SYNTHETIC DATA</div>}<nav>{menu.map(([title,path],i)=><Link key={path} to={path}>{i===0?<Activity size={18}/>:i===1?<Users size={18}/>:<span className="nav-dot"/>}{title}</Link>)}</nav><div className="side-bottom"><span className="avatar">{user.name[0]}</span><div className="identity"><strong>{user.name}</strong><small>{user.role}</small></div><button className="icon-button" aria-label="Log out" onClick={logout}><LogOut size={18}/></button></div></aside><main className="workspace"><header><div><p className="eyebrow">YOUR CARE CIRCLE</p><h2>{user.role === 'FAMILY' || user.role === 'ADMIN' ? 'Family dashboard' : `${user.role[0]}${user.role.slice(1).toLowerCase()} portal`}</h2></div><button className="icon-button" aria-label="Notifications"><Bell/></button></header><Routes><Route path="/" element={user.role==='FAMILY'||user.role==='ADMIN'?<Dashboard/>:<Placeholder role={user.role} title={menu[0][0]}/>}/>{menu.slice(1).map(([title,path])=><Route key={path} path={path} element={<Placeholder role={user.role} title={`${title} · Coming in Phase 2`}/>}/>)}<Route path="*" element={<Placeholder role={user.role} title="Page not found"/>}/></Routes><footer>Operational care-coordination tool — not a diagnostic or emergency service. Demo data is fictional.<span>Phase {meta.data?.phase ?? 1} · v{meta.data?.version ?? '0.1.0'}</span></footer></main></div>;
}
function Dashboard() {
  const patients = useQuery({ queryKey:['patients'], queryFn:()=>api<{items:Patient[];total:number}>('/api/v1/patients') });
  const [selected, setSelected] = useState(''); const id=selected||patients.data?.items[0]?.id;
  const team = useQuery({queryKey:['team',id],queryFn:()=>api<{items:{name:string;team_role:string}[]}>(`/api/v1/patients/${id}/care-team`),enabled:!!id});
  const history = useQuery({queryKey:['history',id],queryFn:()=>api<{items:{summary:string;occurred_at:string}[]}>(`/api/v1/patients/${id}/history`),enabled:!!id});
  const health = useQuery({queryKey:['health'],queryFn:()=>api<{status:string}>('/api/health')});
  return <><section className="welcome"><div><p className="eyebrow">A LITTLE MORE PEACE OF MIND</p><h1>Care works better together.</h1><p>Keep your family's support connected, informed, and ready to help.</p></div><div className="welcome-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="heart"><HeartHandshake size={46}/></div></div></section><div className="section-head"><div><p className="eyebrow">PATIENTS IN YOUR CARE</p><h3>Your people</h3></div><select aria-label="Select patient" value={id??''} onChange={e=>setSelected(e.target.value)}>{patients.data?.items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>{patients.isLoading?<div className="card skeleton"/>:patients.data?.items.length?<section className="patient-card"><div className="patient-avatar">{patients.data.items.find(p=>p.id===id)?.name.split(' ').map(s=>s[0]).join('')}</div><div className="patient-info"><span className="status-pill"><i/> Care circle active</span><h3>{patients.data.items.find(p=>p.id===id)?.name}</h3><p>{patients.data.items.find(p=>p.id===id)?.care_notes}</p></div><div className="patient-age">{patients.data.items.find(p=>p.id===id)?.birth_year?new Date().getFullYear()-patients.data.items.find(p=>p.id===id)!.birth_year!+' years':''}</div></section>:<div className="card empty">Your patient list is empty. Add a patient when you are ready to organize their support.</div>}<div className="grid"><section className="card"><div className="card-head"><div><p className="eyebrow">YOUR SUPPORT NETWORK</p><h3>Care team</h3></div><Users className="soft-icon"/></div>{team.isLoading?<div className="skeleton"/>:<ul className="team-list">{team.data?.items.map((m,i)=><li key={m.name}><span className={'person p'+i}>{m.name[0]}</span><span><strong>{m.name}</strong><small>{m.team_role.toLowerCase().replace('_',' ')}</small></span><i className="online"/></li>)}</ul>}</section><section className="card"><div className="card-head"><div><p className="eyebrow">RECENT ACTIVITY</p><h3>History</h3></div><Activity className="soft-icon"/></div>{history.isLoading?<div className="skeleton"/>:<ul className="history-list">{history.data?.items.length?history.data.items.slice(0,4).map((h,i)=><li key={i}><i className="timeline-dot"/><span>{h.summary}<small>{new Date(h.occurred_at).toLocaleString()}</small></span></li>):<li className="muted">No activity yet</li>}</ul>}</section></div><section className="system"><div><span className="system-icon"><Activity/></span><span><strong>System status</strong><small>Care workspace is running normally</small></span></div><span className="status-pill"><i/> {health.data?.status==='ok'?'All systems operational':'Checking'}</span></section></>;
}
function Placeholder({role,title}:{role:string;title:string}){return <section className="card placeholder"><p className="eyebrow">{role} WORKSPACE</p><h2>{title}</h2><p>This part of the care continuity workspace is planned for a later phase.</p></section>}
export default App;
