export const candidateLabels: Record<string, string> = {
  ELIGIBLE: 'Can take it', COMMITTED: 'Already committed', AT_LIMIT: 'At limit', UNAVAILABLE: 'Unavailable',
  MISSING_CAPABILITY: 'Missing capability', PREFERENCE: 'Family preference', NOT_QUALIFIED: 'Needs professional', DECLINED_REQUEST: 'Said no', INACTIVE: 'Inactive', REPLACED: 'Being replaced',
};
export const resolutionLabels: Record<string, string> = { MATCHER: 'via matcher', MANUAL: 'arranged directly' };

export function candidateLabel(status: string) { return candidateLabels[status] ?? status.replace(/_/g, ' ').toLowerCase(); }
export function resolutionLabel(value?: string | null) { return value ? (resolutionLabels[value] ?? value.toLowerCase()) : ''; }

/** "<1 min", "12 min", "2 h 5 min", "—" when unknown. */
export function formatMinutes(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) return '—';
  if (value < 1) return '<1 min';
  const total = Math.round(value);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60); const m = total % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined || !Number.isFinite(value) ? '—' : `${Math.round(value)}%`;
}

/** Signed points with a true minus sign: "+15", "−10", "0". */
export function signedPoints(points: number) {
  return points > 0 ? `+${points}` : points < 0 ? `−${Math.abs(points)}` : '0';
}

/** Eligible candidates (already rank-ordered by the backend) first; the first `top` stay expanded. */
export function splitCandidates<T extends { eligible: boolean; rank?: number }>(candidates: T[], top = 3) {
  const eligible = candidates.filter(c => c.eligible).sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  const others = candidates.filter(c => !c.eligible);
  return { shown: eligible.slice(0, top), rest: [...eligible.slice(top), ...others] };
}
