import { describe, expect, it } from 'vitest';
import { compositeText, explanation, includedText, sourceLine, stars, starsLabel, type Reputation } from './reputation.ts';

describe('reputation text', () => {
  it('draws stars and labels them', () => {
    expect(stars(4)).toBe('★★★★☆');
    expect(stars(4.6)).toBe('★★★★★');
    expect(stars(null)).toBe('');
    expect(starsLabel(4)).toBe('4 out of 5 stars');
    expect(starsLabel(3.5)).toBe('3.5 out of 5 stars');
  });
  it('says when there is not enough history', () => {
    expect(compositeText({ composite: null, enough_history: false, rating_count: 0 })).toBe('Not enough history yet');
    expect(compositeText({ composite: 77.6, enough_history: false, rating_count: 1 })).toBe('Reputation 78/100 · not enough history yet');
    expect(compositeText({ composite: 81.2, enough_history: true, rating_count: 12 })).toBe('Reputation 81/100 · 12 ratings');
  });
  it('names the sources included and the ones missing', () => {
    expect(includedText(['metric', 'agency'])).toBe('Based on reliability record, agency rating; no doctor ratings, family reviews yet');
    expect(includedText(['metric', 'doctors', 'customers', 'agency'])).toBe('Based on reliability record, doctor ratings, family reviews, agency rating');
    expect(includedText([])).toBe('No sources yet');
  });
  it('describes each source in words', () => {
    expect(sourceLine('customers', { label: '', score: 60, count: 1, stars: 5, adjusted_stars: 3.9 })).toBe('5.0 average from 1 review, counted as 3.9');
    expect(sourceLine('doctors', { label: '', score: null, count: 0, stars: null })).toBe('No doctor ratings yet');
    expect(sourceLine('agency', { label: '', score: 75, count: 1, stars: 4 })).toBe('4.0 from the agency');
    expect(sourceLine('metric', { label: '', score: null, count: 3, tasks: 3 })).toBe('3 finished tasks in the window; more needed for a score');
    expect(sourceLine('metric', { label: '', score: 88.4, count: 40, tasks: 40 })).toBe('88/100 from 40 finished tasks');
  });
  it('explains the formula with the live policy and never as a medical judgement', () => {
    const lines = explanation({ weights: { metric: 40, doctors: 25, customers: 20, agency: 15 }, policy: { patient_review_weight: 0.5, shrinkage_k: 3, metric_window_days: 90, metric_min_tasks: 5, min_ratings_for_history: 3 } } as Pick<Reputation, 'weights' | 'policy'>);
    expect(lines[0]).toContain('reliability record 40');
    expect(lines.join(' ')).toContain('counts half as much');
    expect(lines.join(' ')).toContain('not the per-task fit score');
    expect(lines[lines.length - 1]).toContain('not a medical or clinical assessment');
  });
});
