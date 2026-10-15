import { describe, expect, it } from 'vitest';
import { bandOf, filterPatients, pctText, toCsv, trendText, type Insights, type PatientInsight } from './insights.ts';

const p = (over: Partial<PatientInsight>): PatientInsight => ({
  id: 'x', name: 'Test Patient', birth_year: 1950, care_code: 'CC-ABC123', due: 20, on_time: 15, late: 2, missed: 3, pending: 0, decided: 20, taken_pct: 85, on_time_pct: 75,
  recent: { due: 6, missed: 0, taken_pct: 100 }, trend: 'steady', needs_follow_up: false, flags: [], next_appointment: null, uncovered_appointments: 0, open_requests: 0, medicines: [], spark: [], ...over,
});

describe('bands and labels', () => {
  it('puts patients in the same bands as the backend', () => {
    expect(bandOf(p({ taken_pct: 96 }))).toBe('on_track');
    expect(bandOf(p({ taken_pct: 82 }))).toBe('watch');
    expect(bandOf(p({ taken_pct: 60, needs_follow_up: true }))).toBe('follow_up');
    expect(bandOf(p({ taken_pct: 67, decided: 3 }))).toBe('no_data');
    expect(bandOf(p({ taken_pct: null, decided: 0 }))).toBe('no_data');
  });
  it('formats numbers and trends', () => {
    expect(pctText(84.6)).toBe('85%');
    expect(pctText(null)).toBe('—');
    expect(trendText('slipping')).toBe('Slipping');
    expect(trendText('not_enough_data')).toBe('Not enough data');
  });
});

describe('filtering and export', () => {
  const list = [p({ name: 'Lalitha Krishnan', taken_pct: 96 }), p({ name: 'Mohan Das', care_code: 'CC-ZZZ999', taken_pct: 60, needs_follow_up: true })];
  it('filters by name, ID and band', () => {
    expect(filterPatients(list, 'lali', 'all').map(x => x.name)).toEqual(['Lalitha Krishnan']);
    expect(filterPatients(list, 'zzz', 'all').map(x => x.name)).toEqual(['Mohan Das']);
    expect(filterPatients(list, '', 'follow_up').map(x => x.name)).toEqual(['Mohan Das']);
  });
  it('writes a safe CSV', () => {
    const data = { patients: [p({ name: '=HYPERLINK("x")', next_appointment: { id: 'a', title: 'Review, annual', start: '2026-10-20T05:00:00Z', covered: true } })] } as unknown as Insights;
    const lines = toCsv(data).trim().split('\n');
    expect(lines[0].startsWith('Patient,CareCircle ID')).toBe(true);
    expect(lines[1].startsWith(`"'=HYPERLINK(""x"")"`)).toBe(true);
    expect(lines[1]).toContain('"Review, annual (2026-10-20)"');
  });
});
