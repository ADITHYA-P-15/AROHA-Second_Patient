import { supportLabel } from './plan.ts';
import type { ReputationSummary } from './reputation.ts';

export type Sector = { id: string; code: 'NORTH' | 'SOUTH' | 'EAST' | 'WEST'; name: string; states: string[] };
export type Agency = { id: string; name: string; city: string; sector: string; is_synthetic: boolean };
export type CaretakerCard = {
  id: string; name: string; gender: string; gender_label: string; origin_state: string; origin_city: string; current_state: string; current_city: string;
  sector: string | null; agency: { id: string; name: string } | null; languages: string[]; capabilities: string[]; years_experience: number; is_synthetic: boolean;
  reputation?: ReputationSummary;
  agency_rating?: number | null;
};
export type CaretakerDetail = CaretakerCard & {
  bio: string; max_activities_per_day: number; max_hours_per_week: number; on_my_team: boolean;
  private: { phone: string | null; notes: string; current_district: string } | null;
};
export type MyDirectoryProfile = Omit<CaretakerCard, 'id' | 'gender_label' | 'is_synthetic'> & {
  id: string | null; exists: boolean; bio: string; current_district: string; listed: boolean; gender_label?: string;
};
export type DirectoryPage = { items: CaretakerCard[]; total: number; limit: number; offset: number };
export type DirectoryFilters = {
  sector?: string; agency?: string; state?: string; city?: string; gender?: string; language?: string; capability?: string;
  min_experience?: number | string; min_agency_rating?: number | string; available_on?: string; sort?: 'name' | 'experience'; limit?: number; offset?: number;
};

export const PAGE_SIZE = 12;
export const MAX_PAGE = 50; // the server refuses more
export const GENDERS: [string, string][] = [['FEMALE', 'Female'], ['MALE', 'Male'], ['NON_BINARY', 'Non-binary'], ['UNDISCLOSED', 'Prefers not to say']];
export const AGENCY_STARS: [string, string][] = [['', 'Any'], ['3', '3★ and up'], ['3.5', '3.5★ and up'], ['4', '4★ and up'], ['4.5', '4.5★ and up']];
const KEYS: (keyof DirectoryFilters)[] = ['sector', 'agency', 'state', 'city', 'gender', 'language', 'capability', 'min_experience', 'min_agency_rating', 'available_on', 'sort', 'limit', 'offset'];

/** The query string for GET /api/v1/directory/caretakers: blanks dropped, text trimmed, paging kept inside the server's bounds. */
export function buildDirectoryQuery(filters: DirectoryFilters): string {
  const params = new URLSearchParams();
  for (const key of KEYS) {
    let value = filters[key];
    if (value === undefined || value === null) continue;
    if (typeof value === 'string') value = value.trim();
    if (value === '') continue;
    if (key === 'limit') value = Math.min(MAX_PAGE, Math.max(1, Math.floor(Number(value)) || PAGE_SIZE));
    if (key === 'offset') { value = Math.max(0, Math.floor(Number(value)) || 0); if (value === 0) continue; }
    if (key === 'min_experience') { const n = Math.floor(Number(value)); if (!Number.isFinite(n) || n <= 0) continue; value = Math.min(60, n); }
    if (key === 'min_agency_rating') { const n = Number(value); if (!Number.isFinite(n) || n < 1) continue; value = Math.min(5, n); }
    if (key === 'sort' && value === 'name') continue; // the default
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

export const place = (city: string, state: string) => [city, state].filter(Boolean).join(', ');

export function experienceText(years: number): string {
  if (years <= 0) return 'New to caretaking';
  return years === 1 ? '1 year of experience' : `${years} years of experience`;
}

/** The lines a result card shows, in reading order. Never includes contact details. */
export function cardText(card: CaretakerCard): { title: string; lines: string[]; skills: string[] } {
  const origin = place(card.origin_city, card.origin_state);
  const current = place(card.current_city, card.current_state);
  const lines = [
    [card.gender_label, origin && origin !== current ? `from ${origin}` : ''].filter(Boolean).join(' · '),
    current ? `Lives in ${current}` : 'Location not given',
    card.agency ? `Agency: ${card.agency.name}${card.agency_rating ? ` · rated ${card.agency_rating.toFixed(1)}★ by the agency` : ''}` : 'Independent caretaker',
    card.languages.length ? `Speaks ${card.languages.join(', ')}` : '',
    experienceText(card.years_experience),
  ].filter(Boolean);
  return { title: card.name, lines, skills: card.capabilities.map(supportLabel) };
}

export function pageLabel(page: Pick<DirectoryPage, 'total' | 'limit' | 'offset'>, shown: number): string {
  if (!page.total) return 'No caretakers match';
  return `${page.offset + 1}–${page.offset + shown} of ${page.total}`;
}

/** "Tamil, english , ,Hindi" becomes ["Tamil", "english", "Hindi"]; the server capitalises and removes repeats. */
export const splitLanguages = (text: string) => text.split(',').map(s => s.trim()).filter(Boolean);
