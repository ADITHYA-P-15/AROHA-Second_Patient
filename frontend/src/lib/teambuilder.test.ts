import { describe, expect, it } from 'vitest';
import { compareRows, filterMatches, requestStatusText, toggleCompare, type Match } from './teambuilder.ts';

const m = (id: string, over: Partial<Match> = {}): Match => ({ caregiver_id: id, name: `Person ${id}`, score: 0, points: [], why: [], composite: 70, metric: null, city: 'Pune',
  state: 'Maharashtra', sector: 'WEST', gender: 'FEMALE', languages: ['Marathi'], capabilities: ['TRANSPORT'], years_experience: 4, unrated: false, ...over });

describe('builder filtering', () => {
  const items = [m('a'), m('b', { composite: null, unrated: true, city: 'Mumbai' }), m('c', { languages: ['Tamil'] })];
  it('keeps server order and narrows by text, rating and language', () => {
    expect(filterMatches(items, {}).map(x => x.caregiver_id)).toEqual(['a', 'b', 'c']);
    expect(filterMatches(items, { text: 'mumbai' }).map(x => x.caregiver_id)).toEqual(['b']);
    expect(filterMatches(items, { ratedOnly: true }).map(x => x.caregiver_id)).toEqual(['a', 'c']);
    expect(filterMatches(items, { language: 'tamil' }).map(x => x.caregiver_id)).toEqual(['c']);
  });
});

describe('compare view', () => {
  it('holds at most three, in the order picked', () => {
    let s: string[] = [];
    for (const id of ['a', 'b', 'c', 'd']) s = toggleCompare(s, id);
    expect(s).toEqual(['a', 'b', 'c']);
    expect(toggleCompare(s, 'b')).toEqual(['a', 'c']);
  });
  it('lines attributes up per caretaker and labels unrated plainly', () => {
    const rows = compareRows([m('a', { composite: 81.6, why: ['Speaks Marathi'] }), m('b', { composite: null, metric: 55, years_experience: 0 })]);
    const get = (label: string) => rows.find(r => r.label === label)!.values;
    expect(get('Reputation')).toEqual(['82/100', 'Not rated yet']);
    expect(get('Reliability record')).toEqual(['Not enough history', '55/100']);
    expect(get('Experience')).toEqual(['4 years', 'New']);
    expect(get('Can help with')).toEqual(['Transport', 'Transport']);
    expect(get('Why suggested')).toEqual(['Speaks Marathi', '—']);
  });
});

describe('request status wording', () => {
  const base = { caretaker: { id: 'c', name: 'Asha' }, expires_at: '2026-10-20T00:00:00Z' };
  it('says what happens next and never promises SMS or calls', () => {
    const now = Date.parse('2026-10-15T00:00:00Z');
    expect(requestStatusText({ ...base, status: 'PENDING' }, now)).toBe('Waiting for Asha to answer in the app · expires in 5 days');
    expect(requestStatusText({ ...base, status: 'ACCEPTED' })).toContain('Contact details are in Care Team');
    for (const status of ['DECLINED', 'WITHDRAWN', 'EXPIRED'] as const) expect(requestStatusText({ ...base, status })).toContain('Nothing was shared');
    const all = (['PENDING', 'ACCEPTED', 'DECLINED', 'WITHDRAWN', 'EXPIRED'] as const).map(status => requestStatusText({ ...base, status }, now)).join(' ');
    expect(all).not.toMatch(/sms|text message|call|phone/i);
  });
});
