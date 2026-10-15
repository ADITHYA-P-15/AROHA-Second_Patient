import { supportLabel } from './plan.ts';

export type Point = { label: string; points: number };
export type Match = {
  caregiver_id: string; name: string; score: number; points: Point[]; why: string[]; composite: number | null; metric: number | null; city: string; state: string;
  sector: string | null; gender: string; languages: string[]; capabilities: string[]; years_experience: number; unrated: boolean; request_pending?: boolean;
  agency?: string | null; agency_rating?: number | null;
};
export type Preferences = { gender: string | null; gender_mode: 'HARD' | 'SOFT'; languages: string[]; city: string; sector_code: string | null; min_rating: number | null; capabilities: string[]; set?: boolean };
export type HireStatus = 'PENDING' | 'ACCEPTED' | 'DECLINED' | 'WITHDRAWN' | 'EXPIRED';
export type HireRequest = {
  id: string; patient: { id: string; name: string }; caretaker: { id: string; name: string }; requested_by: string | null; intended_role: 'MAIN' | 'BACKUP';
  message: string; status: HireStatus; status_text: string; decline_reason: string; created_at: string; expires_at: string; responded_at: string | null; capacity_note?: string | null;
};
export type Suggestion = { caregiver_id: string; name: string; composite: number | null; city: string; why: string[]; prompt: string };

export const MAX_COMPARE = 3;

/** Client-side narrowing of the ranked matches (the server already applied hard preferences). Order is kept. */
export function filterMatches(items: Match[], f: { text?: string; ratedOnly?: boolean; language?: string; minAgencyRating?: number | null }): Match[] {
  const text = (f.text ?? '').trim().toLowerCase();
  const lang = (f.language ?? '').trim().toLowerCase();
  return items.filter(m => (!text || m.name.toLowerCase().includes(text) || m.city.toLowerCase().includes(text))
    && (!f.ratedOnly || m.composite !== null)
    && (!lang || m.languages.some(l => l.toLowerCase() === lang))
    // Agency rating: caretakers without one (independent, or not rated by their agency) drop out once a minimum is set.
    && (!f.minAgencyRating || (m.agency_rating ?? 0) >= f.minAgencyRating));
}

/** Pick up to three to compare; picking a fourth replaces nothing and returns the same list. */
export function toggleCompare(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter(x => x !== id);
  return selected.length >= MAX_COMPARE ? selected : [...selected, id];
}

const fmtScore = (v: number | null) => v === null ? 'Not rated yet' : `${Math.round(v)}/100`;

/** Rows of the side-by-side view: one attribute per row, one column per caretaker, in the order picked. */
export function compareRows(items: Match[]): { label: string; values: string[] }[] {
  return [
    { label: 'Reputation', values: items.map(m => fmtScore(m.composite)) },
    { label: 'Agency rating', values: items.map(m => m.agency_rating ? `${m.agency_rating.toFixed(1)}★ (${m.agency ?? 'agency'})` : m.agency ? `Not rated (${m.agency})` : 'Independent') },
    { label: 'Reliability record', values: items.map(m => m.metric === null ? 'Not enough history' : `${Math.round(m.metric)}/100`) },
    { label: 'Lives in', values: items.map(m => [m.city, m.state].filter(Boolean).join(', ') || 'Not given') },
    { label: 'Languages', values: items.map(m => m.languages.join(', ') || 'Not given') },
    { label: 'Experience', values: items.map(m => m.years_experience ? `${m.years_experience} years` : 'New') },
    { label: 'Can help with', values: items.map(m => m.capabilities.map(supportLabel).join(', ') || 'Not set') },
    { label: 'Why suggested', values: items.map(m => m.why.join('; ') || '—') },
  ];
}

/** What the family reads for a request; in-app only, so it never promises SMS or calls. */
export function requestStatusText(r: Pick<HireRequest, 'status' | 'expires_at' | 'caretaker'>, now: number = Date.now()): string {
  const name = r.caretaker.name;
  switch (r.status) {
    case 'PENDING': {
      const days = Math.max(0, Math.ceil((new Date(r.expires_at).getTime() - now) / 86_400_000));
      return `Waiting for ${name} to answer in the app · expires in ${days} day${days === 1 ? '' : 's'}`;
    }
    case 'ACCEPTED': return `${name} accepted and is on the care team. Contact details are in Care Team.`;
    case 'DECLINED': return `${name} declined. Nothing was shared.`;
    case 'WITHDRAWN': return 'You withdrew this request. Nothing was shared.';
    case 'EXPIRED': return `${name} did not answer within 7 days. Nothing was shared.`;
  }
}

export const roleText = (role: HireRequest['intended_role']) => role === 'MAIN' ? 'Main caretaker' : 'Backup';
