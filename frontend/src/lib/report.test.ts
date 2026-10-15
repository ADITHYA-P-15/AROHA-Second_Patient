import { describe, expect, it } from 'vitest';
import { groupFacts, reportToText, type ProgressReport } from './report.ts';

const report: ProgressReport = {
  patient_id: 'p', days: 30, as_of: '2026-10-15T00:00:00Z', limits: ['Counts what was recorded.'], narrated_by: 'ai', provider: 'groq', dropped: 1, status: 'DRAFT', reviewed: false,
  notice: 'Draft for your review.',
  facts: [{ id: 'F2', section: 'adherence', key: 'adherence', text: '80% given.' }, { id: 'F1', section: 'course', key: 'course_active', text: 'Metformin 500 mg.' }],
  summary: [{ text: 'Eighty percent were given.', facts: ['F2'] }],
};

describe('progress report helpers', () => {
  it('orders sections for reading and skips empty ones', () => {
    expect(groupFacts(report.facts).map(g => g.section)).toEqual(['course', 'adherence']);
  });
  it('exports plain text that starts as a draft and keeps fact ids', () => {
    const text = reportToText(report, 'Asha');
    expect(text.startsWith('DRAFT progress report: Asha')).toBe(true);
    expect(text).toContain('- Eighty percent were given. [F2]');
    expect(text).toContain('- Metformin 500 mg. [F1]');
  });
});
