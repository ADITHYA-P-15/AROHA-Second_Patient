export type AppNotification = {
  id: string; patient_id: string; incident_id?: string | null; kind: string; severity: 'LOW' | 'MEDIUM' | 'HIGH'; title: string; body: string;
  requires_ack: boolean; channel: string; link?: string | null; read_at?: string | null; created_at: string;
};
export type NotifyPrefs = { level: 'all' | 'important'; sound: boolean; desktop: boolean };
export const DEFAULT_PREFS: NotifyPrefs = { level: 'all', sound: true, desktop: false };
const KEY = 'carecircle.notify.prefs';

export function loadPrefs(storage: Pick<Storage, 'getItem'> | null = typeof localStorage === 'undefined' ? null : localStorage): NotifyPrefs {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_PREFS;
    const value = JSON.parse(raw) as Partial<NotifyPrefs>;
    return { level: value.level === 'important' ? 'important' : 'all', sound: value.sound !== false, desktop: value.desktop === true };
  } catch { return DEFAULT_PREFS; }
}

export function savePrefs(prefs: NotifyPrefs, storage: Pick<Storage, 'setItem'> | null = typeof localStorage === 'undefined' ? null : localStorage): void {
  try { storage?.setItem(KEY, JSON.stringify(prefs)); } catch { /* private mode: preferences last for this page only */ }
}

/** "Important" means medium or high, or anything that asks for an answer. Everything else is a quiet update. */
export const isImportant = (n: Pick<AppNotification, 'severity' | 'requires_ack'>): boolean => n.severity !== 'LOW' || n.requires_ack;
export const shouldPopUp = (n: Pick<AppNotification, 'severity' | 'requires_ack'>, prefs: NotifyPrefs): boolean => prefs.level === 'all' || isImportant(n);
/** Urgent alerts stay on screen until someone looks at them; the rest fade. */
export const staysUntilDismissed = (n: Pick<AppNotification, 'severity' | 'requires_ack'>): boolean => n.severity === 'HIGH' || n.requires_ack;

/** Which new notifications to show, given the ids already seen. Anything already read, or already seen, is skipped. */
export function freshOnes(items: AppNotification[], seen: Set<string>): AppNotification[] {
  return items.filter(i => !seen.has(i.id) && !i.read_at).sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function highest(items: Pick<AppNotification, 'severity'>[]): 'LOW' | 'MEDIUM' | 'HIGH' | null {
  if (items.some(i => i.severity === 'HIGH')) return 'HIGH';
  if (items.some(i => i.severity === 'MEDIUM')) return 'MEDIUM';
  return items.length ? 'LOW' : null;
}

export function ago(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export const tabTitle = (base: string, unread: number): string => (unread > 0 ? `(${unread > 99 ? '99+' : unread}) ${base}` : base);
