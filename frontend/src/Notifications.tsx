import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Bell, BellRing, Check, CheckCheck, Info, X } from 'lucide-react';
import { api } from './api/client.ts';
import { DEFAULT_PREFS, ago, freshOnes, highest, loadPrefs, savePrefs, shouldPopUp, staysUntilDismissed, tabTitle, type AppNotification, type NotifyPrefs } from './lib/notify.ts';

type Feed = { items: AppNotification[]; unread_count: number };
const POLL_MS = 5000;
const BASE_TITLE = 'CareCircle';
const MAX_TOASTS = 4;

/** A short two-tone chime. Browsers only allow sound after the person has interacted with the page, so failures are silent. */
function chime(level: 'LOW' | 'MEDIUM' | 'HIGH') {
  try {
    const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Context) return;
    const ctx = new Context();
    const notes = level === 'HIGH' ? [880, 660, 880] : level === 'MEDIUM' ? [660, 880] : [740];
    notes.forEach((frequency, i) => {
      const osc = ctx.createOscillator(); const gain = ctx.createGain();
      osc.type = 'sine'; osc.frequency.value = frequency;
      const start = ctx.currentTime + i * 0.16;
      gain.gain.setValueAtTime(0.0001, start); gain.gain.exponentialRampToValueAtTime(0.16, start + 0.02); gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.15);
      osc.connect(gain).connect(ctx.destination); osc.start(start); osc.stop(start + 0.17);
    });
    window.setTimeout(() => void ctx.close().catch(() => undefined), 1200);
  } catch { /* sound is a nicety */ }
}

/** The bell, the pop-up alerts, sound, desktop alerts and the unread count in the tab title. */
export function NotificationCenter() {
  const client = useQueryClient(); const navigate = useNavigate();
  const [open, setOpen] = useState(false); const [prefs, setPrefsState] = useState<NotifyPrefs>(() => loadPrefs());
  const [toasts, setToasts] = useState<AppNotification[]>([]);
  const seen = useRef<Set<string> | null>(null); const timers = useRef<Map<string, number>>(new Map());
  const feed = useQuery({ queryKey: ['notifications'], queryFn: () => api<Feed>('/api/v1/notifications?limit=40'), refetchInterval: POLL_MS, refetchIntervalInBackground: true });
  const permission = typeof Notification === 'undefined' ? 'unsupported' : Notification.permission;

  const setPrefs = (next: NotifyPrefs) => { setPrefsState(next); savePrefs(next); };
  const dismiss = useCallback((id: string) => {
    setToasts(list => list.filter(t => t.id !== id));
    const timer = timers.current.get(id); if (timer) { window.clearTimeout(timer); timers.current.delete(id); }
  }, []);

  const open_ = async (n: AppNotification) => {
    dismiss(n.id); setOpen(false);
    if (!n.read_at) { await api(`/api/v1/notifications/${n.id}/read`, { method: 'POST' }).catch(() => undefined); await client.invalidateQueries({ queryKey: ['notifications'] }); }
    navigate(n.link || (n.incident_id ? '/incidents' : '/'));
  };

  // New arrivals: pop up, chime, and (when the tab is in the background) raise a desktop notification.
  useEffect(() => {
    const items = feed.data?.items; if (!items) return;
    if (seen.current === null) {
      seen.current = new Set(items.map(i => i.id));
      const waiting = items.filter(i => !i.read_at);
      if (waiting.length > 0) {
        const urgent = waiting.find(i => staysUntilDismissed(i));
        setToasts([urgent ?? { id: 'summary', patient_id: '', kind: 'STATUS', severity: highest(waiting) ?? 'LOW', title: `You have ${waiting.length} unread notification${waiting.length === 1 ? '' : 's'}`,
          body: 'Open the bell to see what happened.', requires_ack: false, channel: 'ALERT', created_at: new Date().toISOString() }]);
      }
      return;
    }
    const arrived = freshOnes(items, seen.current);
    arrived.forEach(a => seen.current!.add(a.id));
    const shown = arrived.filter(a => shouldPopUp(a, prefs));
    if (shown.length === 0) return;
    setToasts(list => [...list, ...shown].slice(-MAX_TOASTS));
    shown.filter(a => !staysUntilDismissed(a)).forEach(a => {
      timers.current.set(a.id, window.setTimeout(() => dismiss(a.id), 9000));
    });
    const level = highest(shown);
    if (prefs.sound && level) chime(level);
    if (prefs.desktop && permission === 'granted' && document.hidden) {
      shown.slice(-3).forEach(a => {
        try { const n = new Notification(a.title, { body: a.body, tag: a.id }); n.onclick = () => { window.focus(); void open_(a); n.close(); }; } catch { /* some browsers need a service worker */ }
      });
    }
  }, [feed.data]);

  useEffect(() => { document.title = tabTitle(BASE_TITLE, feed.data?.unread_count ?? 0); return () => { document.title = BASE_TITLE; }; }, [feed.data?.unread_count]);
  useEffect(() => () => { timers.current.forEach(t => window.clearTimeout(t)); }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const unread = feed.data?.unread_count ?? 0;
  const items = useMemo(() => feed.data?.items ?? [], [feed.data]);
  async function markAll() { await api('/api/v1/notifications/read-all', { method: 'POST' }).catch(() => undefined); setToasts([]); await client.invalidateQueries({ queryKey: ['notifications'] }); }
  async function enableDesktop() {
    if (permission === 'unsupported') return;
    const result = permission === 'granted' ? 'granted' : await Notification.requestPermission();
    setPrefs({ ...prefs, desktop: result === 'granted' });
  }

  return <div className="notification-menu">
    <button className="icon-button" aria-label={`Notifications, ${unread} unread`} aria-expanded={open} onClick={() => setOpen(!open)}>
      {unread > 0 ? <BellRing/> : <Bell/>}{unread > 0 && <span>{unread > 99 ? '99+' : unread}</span>}
    </button>

    {open && <section className="card nc-panel" aria-label="Notifications">
      <div className="nc-head"><h3>Notifications</h3>
        <button className="nc-link" onClick={() => void markAll()} disabled={unread === 0}><CheckCheck size={15} aria-hidden="true"/>Mark all read</button></div>
      <details className="nc-settings"><summary>Alert settings</summary>
        <label className="nc-row"><span>Pop-ups for</span>
          <select value={prefs.level} onChange={e => setPrefs({ ...prefs, level: e.target.value as NotifyPrefs['level'] })}>
            <option value="all">Every update</option><option value="important">Important only</option></select></label>
        <label className="nc-row"><span>Play a sound</span><input type="checkbox" checked={prefs.sound} onChange={e => { setPrefs({ ...prefs, sound: e.target.checked }); if (e.target.checked) chime('LOW'); }}/></label>
        <div className="nc-row"><span>Desktop alerts when this tab is hidden</span>
          {permission === 'unsupported' ? <small className="muted">Not supported here</small>
            : permission === 'denied' ? <small className="muted">Blocked in the browser</small>
            : prefs.desktop && permission === 'granted' ? <button className="nc-link" onClick={() => setPrefs({ ...prefs, desktop: false })}>Turn off</button>
            : <button className="nc-link" onClick={() => void enableDesktop()}>Turn on</button>}</div>
      </details>
      {items.length === 0 ? <p className="muted nc-empty">Nothing yet. Updates and reminders will appear here.</p>
        : <ul className="nc-list">{items.slice(0, 30).map(n => <li key={n.id}>
          <button className={`nc-item nc-${n.severity.toLowerCase()}${n.read_at ? ' nc-read' : ''}`} onClick={() => void open_(n)}>
            <span className="nc-icon" aria-hidden="true">{n.severity === 'HIGH' ? <AlertTriangle size={16}/> : n.kind === 'REMINDER' ? <BellRing size={16}/> : n.read_at ? <Check size={16}/> : <Info size={16}/>}</span>
            <span className="nc-text"><strong>{n.title}</strong>{n.body && <small>{n.body}</small>}<em>{ago(n.created_at)}</em></span>
          </button></li>)}</ul>}
    </section>}

    <div className="nc-toasts" aria-live="polite" aria-label="New notifications">
      {toasts.map(t => <div key={t.id} role={t.severity === 'HIGH' ? 'alert' : 'status'} className={`nc-toast nc-${t.severity.toLowerCase()}`}>
        <button className="nc-toast-main" onClick={() => void open_(t)}>
          <span className="nc-icon" aria-hidden="true">{t.severity === 'HIGH' ? <AlertTriangle size={18}/> : t.kind === 'REMINDER' ? <BellRing size={18}/> : <Info size={18}/>}</span>
          <span className="nc-text"><strong>{t.title}</strong>{t.body && <small>{t.body}</small>}</span>
        </button>
        <button className="nc-x" aria-label="Dismiss" onClick={() => dismiss(t.id)}><X size={16}/></button>
      </div>)}
    </div>
  </div>;
}

export { DEFAULT_PREFS };
