import { describe, expect, it } from 'vitest';
import { coverLine, groupByDay, holderSummary, kindLabel, scheduleSummary } from './plan.ts';

const a = (status: string, name = 'Savitha', is_mine = false, role = 'PRIMARY') => ({ id: name + status, caregiver_id: name, caregiver_name: name, role, status, is_mine });

describe('holderSummary', () => {
  it('names the confirmed caretaker and ignores superseded history', () => {
    const s = holderSummary({ assignments: [a('SUPERSEDED', 'Anita'), a('CONFIRMED')] });
    expect(s.text).toBe('Savitha');
    expect(s.tone).toBe('ok');
  });
  it('says who is being asked while nobody has accepted', () => {
    expect(holderSummary({ assignments: [a('AWAITING_CONFIRMATION', 'Lakshmi')] }).text).toBe('Waiting for Lakshmi to accept');
    expect(holderSummary({ assignments: [a('AWAITING_CONFIRMATION', 'Lakshmi', true)] }).text).toBe('You are asked to take this');
  });
  it('flags a task with nobody on it', () => {
    expect(holderSummary({ assignments: [a('DECLINED')] })).toMatchObject({ text: 'No caretaker yet', tone: 'none' });
    expect(holderSummary({ assignments: [], requires_caregiver: false }).tone).toBe('muted');
  });
});

describe('plan grouping', () => {
  it('labels today and tomorrow in the app timezone', () => {
    const now = new Date('2026-10-15T04:00:00Z'); // 09:30 IST
    const groups = groupByDay([{ scheduled_start: '2026-10-16T05:00:00Z' }, { scheduled_start: '2026-10-15T14:30:00Z' }, { scheduled_start: '2026-10-14T19:00:00Z' }], now);
    expect(groups.map(g => g.label.split(' · ')[0])).toEqual(['Today', 'Tomorrow']);
    expect(groups[0].items).toHaveLength(2); // 00:30 IST on the 15th belongs to today
  });
  it('names the kind of activity', () => {
    expect(kindLabel({ source: 'PRESCRIPTION', category: 'MEDICATION' })).toBe('Medicine');
    expect(kindLabel({ source: 'MANUAL', category: 'DAILY_ROUTINE' })).toBe('Home task');
  });
});

describe('scheduleSummary', () => {
  it('reads like a sentence', () => {
    expect(scheduleSummary(Array.from({ length: 7 }, (_, weekday) => ({ weekday, start_min: 420, end_min: 1290 })))).toBe('Every day 07:00–21:30');
    expect(scheduleSummary([0, 1, 2, 3, 4].map(weekday => ({ weekday, start_min: 540, end_min: 1080 })))).toBe('Weekdays 09:00–18:00');
    expect(scheduleSummary([{ weekday: 5, start_min: 0, end_min: 1440 }, { weekday: 6, start_min: 0, end_min: 1440 }])).toBe('Weekends all day');
    expect(scheduleSummary([])).toBe('No regular hours set');
  });
});

describe('coverLine', () => {
  it('says who is being asked, only when the viewer may know', () => {
    expect(coverLine(null)).toBe('');
    expect(coverLine({ status: 'OFFERED', offered_to: 'Lakshmi Rao', offered_to_me: false })).toBe('Finding cover: Lakshmi Rao has been asked');
    expect(coverLine({ status: 'OFFERED', offered_to: null, offered_to_me: false })).toBe('Finding cover: a replacement is being asked');
  });
});
