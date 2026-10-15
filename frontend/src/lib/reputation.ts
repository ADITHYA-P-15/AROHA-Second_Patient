export type SourceKey = 'metric' | 'doctors' | 'customers' | 'agency';
export type MetricComponent = { key: string; label: string; value: number | null; weight: number; detail: string; included: boolean };
export type Source = {
  label: string; score: number | null; count: number; stars?: number | null; adjusted_stars?: number; prior?: number; effective_count?: number;
  by_author?: Record<'PRIMARY_CONTACT' | 'PATIENT', { count: number; stars: number | null }>;
  components?: MetricComponent[]; enough_history?: boolean; tasks?: number;
};
export type Reputation = {
  caregiver_id: string; name: string; composite: number | null; included: SourceKey[]; effective_weights: Partial<Record<SourceKey, number>>;
  sources: Record<SourceKey, Source>; weights: Record<SourceKey, number>; rating_count: number; enough_history: boolean;
  policy: { patient_review_weight: number; shrinkage_k: number; metric_window_days: number; metric_min_tasks: number; min_ratings_for_history: number };
};
export type ReputationSummary = { composite: number | null; enough_history: boolean; rating_count: number; included: SourceKey[] };
export type ReviewItem = { id: string; rating: number; text: string | null; author_role: 'PRIMARY_CONTACT' | 'PATIENT'; created_at: string; edited: boolean; is_mine: boolean; editable: boolean; is_synthetic: boolean };
export type Rateable = {
  caregiver_id: string; name: string; completed_tasks: number; kind: 'review' | 'doctor'; eligible: boolean; needed_tasks?: number; optional?: boolean;
  mine: { id: string; rating: number; text?: string | null; note?: string; editable: boolean } | null;
};

export const SOURCE_ORDER: SourceKey[] = ['metric', 'doctors', 'customers', 'agency'];
export const SOURCE_LABEL: Record<SourceKey, string> = { metric: 'Reliability record', doctors: 'Doctor ratings', customers: 'Family reviews', agency: 'Agency rating' };

/** "★★★★☆" for 4 (rounded to the nearest whole star), for screen readers use starsLabel. */
export function stars(value: number | null | undefined): string {
  if (value === null || value === undefined) return '';
  const n = Math.max(0, Math.min(5, Math.round(value)));
  return '★'.repeat(n) + '☆'.repeat(5 - n);
}
export const starsLabel = (value: number) => `${value.toFixed(1).replace(/\.0$/, '')} out of 5 stars`;
export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The headline on a card or profile. Never a medical or clinical judgement: it summarises coordination records and ratings. */
export function compositeText(r: Pick<ReputationSummary, 'composite' | 'enough_history' | 'rating_count'>): string {
  if (r.composite === null) return 'Not enough history yet';
  const score = `Reputation ${Math.round(r.composite)}/100`;
  return r.enough_history ? `${score} · ${plural(r.rating_count, 'rating')}` : `${score} · not enough history yet`;
}

export function includedText(included: SourceKey[]): string {
  if (!included.length) return 'No sources yet';
  const missing = SOURCE_ORDER.filter(s => !included.includes(s));
  return `Based on ${included.map(s => SOURCE_LABEL[s].toLowerCase()).join(', ')}` + (missing.length ? `; no ${missing.map(s => SOURCE_LABEL[s].toLowerCase()).join(', ')} yet` : '');
}

/** One line per source for the breakdown. */
export function sourceLine(key: SourceKey, s: Source): string {
  if (key === 'metric') {
    if (s.score === null) return s.tasks ? `${plural(s.tasks, 'finished task')} in the window; more needed for a score` : 'No finished tasks on record yet';
    return `${Math.round(s.score)}/100 from ${plural(s.tasks ?? 0, 'finished task')}`;
  }
  if (key === 'agency') return s.stars ? `${s.stars.toFixed(1)} from the agency` : 'No agency rating';
  if (!s.count || s.stars === null || s.stars === undefined) return key === 'doctors' ? 'No doctor ratings yet' : 'No reviews yet';
  const what = key === 'doctors' ? plural(s.count, 'rating') : plural(s.count, 'review');
  return `${s.stars.toFixed(1)} average from ${what}` + (s.adjusted_stars !== undefined && Math.abs(s.adjusted_stars - s.stars) >= 0.05 ? `, counted as ${s.adjusted_stars.toFixed(1)}` : '');
}

/** The explanation behind "How this is calculated", with this deployment's numbers. */
export function explanation(r: Pick<Reputation, 'weights' | 'policy'>): string[] {
  const w = r.weights; const p = r.policy;
  return [
    `Weights: reliability record ${w.metric}, doctor ratings ${w.doctors}, family reviews ${w.customers}, agency rating ${w.agency}. Sources without data are left out and the rest are scaled up to 100%.`,
    `Stars become a 0–100 score: 1 star is 0, 3 stars is 50, 5 stars is 100.`,
    `Few ratings are pulled toward the regional average, as if ${p.shrinkage_k} average ratings had already been given, so one review cannot put anyone first.`,
    `A patient's own review counts ${p.patient_review_weight === 0.5 ? 'half' : `${p.patient_review_weight}×`} as much as a family member's.`,
    `The reliability record uses the last ${p.metric_window_days} days of tasks (at least ${p.metric_min_tasks}): on-time completion, tasks not missed, on-time check-ins and cover offers accepted. It is not the per-task fit score shown when finding cover.`,
    'This summarises care-coordination records and ratings. It is not a medical or clinical assessment.',
  ];
}

export const authorLabel = (role: ReviewItem['author_role']) => role === 'PATIENT' ? 'Patient' : 'Family member';
